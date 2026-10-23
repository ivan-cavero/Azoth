//! Durable character records for the identity database: accounts, the platform identities linked
//! to them, and the character directory.
//!
//! WHY THIS CRATE EXISTS
//! =====================
//! "Restart the region, log in again, and the same character comes back" is a property of storage,
//! not of a service. The prototype cannot express it: every login is handed the same hardcoded
//! character (`AZOTH_CHARACTER_ID = "11111111-1111-1111-1111-111111111111"` in
//! `services/gateway/src/azoth_gateway/routes/identity.py`), so a second character cannot exist and
//! nothing written before a restart is readable after one. `docs/PLAN-backend-rust.md` §6.4 makes
//! the create step a directory write by `regiond`, and this crate is that write plus the reads a
//! login performs against it: the account behind a platform identity, and the characters that
//! account owns.
//!
//! WHAT IS DELIBERATELY NOT HERE
//! =============================
//! No live character state. Position, vitals, inventory and progression belong to the **world**
//! database, which has a different load shape (§9.1): a directory row is small and read once per
//! login, a live aggregate is a large blob flushed off the tick. One store for both would make a
//! login pay the world's write amplification, and would couple a world restart to the login path.
//!
//! THE DRIVER IS BLOCKING ON PURPOSE
//! =================================
//! `rusqlite` is synchronous, and §9.1 keeps it that way: blocking work on the async executor
//! starves everything else, and a blocking driver makes calling the database from a tick
//! *impossible* rather than merely discouraged — every access has to go through
//! `tokio::task::spawn_blocking` or a dedicated persistence thread by necessity instead of by
//! discipline. Do not wrap this crate in an async façade that hides that; the compile error is the
//! feature.
//!
//! MIGRATIONS ARE FORWARD-ONLY
//! ===========================
//! [`MIGRATIONS`] is applied in order and there are no down migrations (§9.2). A private server can
//! restore a backup, and a down migration is a second code path that nothing in normal operation
//! ever exercises — so it is the path that is broken when it is finally needed. Forward-only keeps
//! one direction of history to prove.
//!
//! A NEWER DATABASE REFUSES TO OPEN
//! ================================
//! [`Store::open`] fails with [`StoreError::SchemaAhead`] when the database records a version this
//! binary does not understand. That is the check that stops a rolled-back binary from writing rows
//! in the shape of an older schema into a database that has moved on — the failure it prevents is
//! silent data loss, not a crash, which is exactly why it is enforced at open and not left to each
//! query.
//!
//! THE SCHEMA, VERSION 1
//! =====================
//! * `accounts` — one row per account; `account_id` is a `UUIDv4` minted by the caller.
//! * `identities` — `(provider, provider_id)` is the key, `account_id` is the account it resolves
//!   to. A table of its own because one account can hold several platform identities, and because
//!   the login path looks up by identity and never by account.
//! * `characters` — the directory row: name, world binding, timestamps and a tombstone flag.
//!   `account_id` is a foreign key, so a character cannot exist under an account that does not.
//! * `schema_version` — a single row recording the applied version.
//!
//! The schema is defined here and applied here, because the shape of the data is this crate's whole
//! subject; `store` holds the queries issued against it. Deletion is a tombstone
//! (`deleted = 1`), never a row delete (§6.4): a world-side purge is a separate, later step, and a
//! directory row that vanished would make a stale world reference indistinguishable from a
//! character that never existed.

#![forbid(unsafe_code)]

use rusqlite::{Connection, OptionalExtension};

pub mod error;
pub mod store;

pub use error::StoreError;
pub use store::Store;

/// The schema version this binary applies and understands.
pub const SCHEMA_VERSION: u32 = 1;

/// Every migration, in application order, forward-only.
///
/// Each entry is `(version, SQL)` and the SQL is responsible for recording its own version in
/// `schema_version`; the migration runner fails the migration if it does not. Keeping that write
/// inside the SQL means a new migration cannot be added and forgotten in the bookkeeping — the
/// statement that changes the schema also states which version the database is now at.
///
/// There are no down migrations on purpose (§9.2): a private server can restore a backup, and a
/// rollback path that nothing exercises is the path that is broken when it is needed.
pub const MIGRATIONS: &[(u32, &str)] = &[(1, V1_IDENTITY)];

/// Version 1: accounts, linked platform identities, and the character directory.
///
/// The index on `characters` is `(account_id, created_at, character_id)` rather than `account_id`
/// alone: it still answers "characters for this account", and it also supplies the order
/// [`Store::characters_for`] promises, so that query never sorts.
const V1_IDENTITY: &str = r"
CREATE TABLE accounts (
    account_id   TEXT PRIMARY KEY NOT NULL,
    display_name TEXT NOT NULL,
    status       TEXT NOT NULL,
    created_at   INTEGER NOT NULL
);

CREATE TABLE identities (
    provider    TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    account_id  TEXT NOT NULL REFERENCES accounts (account_id),
    PRIMARY KEY (provider, provider_id)
);

CREATE TABLE characters (
    character_id TEXT PRIMARY KEY NOT NULL,
    account_id   TEXT NOT NULL REFERENCES accounts (account_id),
    name         TEXT NOT NULL,
    world_id     TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    modified_at  INTEGER NOT NULL,
    deleted      INTEGER NOT NULL
);

CREATE INDEX characters_by_account ON characters (account_id, created_at, character_id);

INSERT INTO schema_version (version) VALUES (1);
";

/// The `schema_version` table itself.
///
/// It cannot be a migration: the runner has to read the applied version before it can know which
/// migration to apply. Creating it `IF NOT EXISTS` before that first read is therefore the one
/// piece of DDL outside the list.
const SCHEMA_VERSION_TABLE: &str =
    "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);";

/// An account: the durable identity a login resolves to.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Account {
    /// `UUIDv4` string, minted by the caller. The primary key.
    pub account_id: String,
    /// What the operator sees. Not unique: the client shows the character name, not this.
    pub display_name: String,
    /// `"active"` or `"locked"`. A `String` rather than an enum because the vocabulary is a policy
    /// the database stores, and a schema migration is the wrong place to discover a new value.
    pub status: String,
    /// Creation time, unix seconds. Supplied by the caller so a restored backup keeps its history.
    pub created_at: i64,
}

/// A character directory row: who owns it, what it is called, and which world it lives on.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Character {
    /// `UUIDv4` string, minted by the caller (`regiond` at create time, §6.4). The primary key.
    pub character_id: String,
    /// The owning account. A foreign key to [`Account::account_id`].
    pub account_id: String,
    /// The character name the player typed. Validation belongs to the caller: the rule is not yet
    /// measured on 1.460 (§6.4 names it as item `#24`).
    pub name: String,
    /// The world this character is bound to.
    pub world_id: String,
    /// Creation time, unix seconds.
    pub created_at: i64,
    /// Last change to this row, unix seconds. The caller owns it; this crate never invents a clock.
    pub modified_at: i64,
    /// Tombstone. `true` means deleted, and the row stays.
    pub deleted: bool,
}

/// Apply every migration newer than the recorded version, in order, each in its own transaction.
///
/// A migration that fails leaves the database at the previous version: the transaction is dropped
/// without committing, so a half-applied schema is not a state this crate can produce.
pub(crate) fn migrate(conn: &Connection) -> Result<(), StoreError> {
    conn.execute_batch(SCHEMA_VERSION_TABLE)
        .map_err(|err| error::sqlite("create schema_version", &err))?;
    let applied = read_version(conn)?;
    if applied > SCHEMA_VERSION {
        return Err(StoreError::SchemaAhead {
            database: applied,
            binary: SCHEMA_VERSION,
        });
    }
    for (version, sql) in MIGRATIONS {
        if *version <= applied {
            continue;
        }
        let tx = conn
            .unchecked_transaction()
            .map_err(|err| error::sqlite("begin migration", &err))?;
        tx.execute_batch(sql)
            .map_err(|err| error::sqlite("apply migration", &err))?;
        let recorded = read_version(&tx)?;
        if recorded != *version {
            return Err(StoreError::Sqlite(format!(
                "migration {version} recorded version {recorded}; a migration must record its own version"
            )));
        }
        tx.commit()
            .map_err(|err| error::sqlite("commit migration", &err))?;
    }
    let final_version = read_version(conn)?;
    if final_version != SCHEMA_VERSION {
        return Err(StoreError::Sqlite(format!(
            "schema is at version {final_version}, this binary expects {SCHEMA_VERSION}"
        )));
    }
    Ok(())
}

/// The recorded schema version; `0` for a database that has never been migrated.
pub(crate) fn read_version(conn: &Connection) -> Result<u32, StoreError> {
    let version: Option<i64> = conn
        .query_row("SELECT version FROM schema_version LIMIT 1", [], |row| {
            row.get(0)
        })
        .optional()
        .map_err(|err| error::sqlite("read schema version", &err))?;
    match version {
        None => Ok(0),
        Some(raw) => u32::try_from(raw).map_err(|_| {
            StoreError::Sqlite(format!("schema_version holds {raw}, which is not a version"))
        }),
    }
}
