//! The queries: one `rusqlite` connection and the statements the login and character paths issue
//! against it.
//!
//! WHY ONE CONNECTION AND NO POOL
//! ==============================
//! The identity database's write pattern is "rare, transactional" and its read pattern is "small
//! rows, per login, high burst at launch" (`docs/PLAN-backend-rust.md` §9.1). A single connection
//! behind whatever concurrency the caller already owns is the honest shape for that: WAL gives
//! concurrent readers, and a pool would be a second policy to get wrong before there is a
//! measurement that needs one. `rusqlite::Connection` is `Send` and not `Sync`, so sharing the
//! store across threads is a decision the caller makes explicitly, not one this type hides.
//!
//! WHY CONSTRAINT CODES, NOT PRE-CHECKS
//! ====================================
//! `create_account` and `create_character` map a specific SQLite constraint violation to a specific
//! variant instead of running a `SELECT` first. A pre-check is a race (two writers both see "absent"
//! and both insert) and a second place where the rule lives. The database states the invariant; the
//! code translates its answer.
//!
//! WHY DELETION IS AN UPDATE
//! =========================
//! §6.4: `regiond` marks the directory row deleted and enqueues a world-side purge. A hard delete
//! would make "this character was deleted" indistinguishable from "this character was never here"
//! for any world still holding a reference, so the row stays and [`Character::deleted`] carries the
//! fact.

use std::path::Path;

use rusqlite::{Connection, OptionalExtension, Row, params};

use crate::error::sqlite;
use crate::{Account, Character, StoreError, migrate, read_version};

/// The identity database.
#[derive(Debug)]
pub struct Store {
    conn: Connection,
}

impl Store {
    /// Open (creating if absent) the identity database at `path`, applying migrations.
    ///
    /// The parent directory must already exist: a mistyped path should fail loudly at startup
    /// rather than silently create a database somewhere nobody looks.
    ///
    /// # Errors
    /// [`StoreError::SchemaAhead`] when the database is newer than this binary, and
    /// [`StoreError::Sqlite`] for any driver failure, including a migration that fails.
    pub fn open(path: &Path) -> Result<Self, StoreError> {
        let conn = Connection::open(path).map_err(|err| sqlite("open", &err))?;
        Self::from_connection(conn)
    }

    /// Open an in-memory database, for tests.
    ///
    /// It reports journal mode `memory`: WAL is a property of a file, so the pragma is a no-op here
    /// and the returned mode is not asserted.
    ///
    /// # Errors
    /// [`StoreError::Sqlite`] if the driver cannot create the database or a migration fails.
    pub fn open_in_memory() -> Result<Self, StoreError> {
        let conn = Connection::open_in_memory().map_err(|err| sqlite("open in memory", &err))?;
        Self::from_connection(conn)
    }

    /// Set the pragmas the schema depends on, then bring the schema up to date.
    fn from_connection(conn: Connection) -> Result<Self, StoreError> {
        // Off by default in SQLite, and the whole point of the `characters.account_id` foreign key
        // is that a character cannot outlive its account.
        conn.execute_batch("PRAGMA foreign_keys = ON;")
            .map_err(|err| sqlite("enable foreign keys", &err))?;
        // Concurrent readers with one writer: the region reads directories while a login writes.
        conn.query_row("PRAGMA journal_mode = WAL", [], |_| Ok(()))
            .map_err(|err| sqlite("set journal mode", &err))?;
        migrate(&conn)?;
        Ok(Self { conn })
    }

    /// Insert an account.
    ///
    /// # Errors
    /// [`StoreError::DuplicateAccount`] if the id exists, [`StoreError::Sqlite`] otherwise.
    pub fn create_account(&self, account: &Account) -> Result<(), StoreError> {
        self.conn
            .execute(
                "INSERT INTO accounts (account_id, display_name, status, created_at)
                 VALUES (?1, ?2, ?3, ?4)",
                params![
                    account.account_id,
                    account.display_name,
                    account.status,
                    account.created_at
                ],
            )
            .map_err(|err| {
                if is_primary_key(&err) {
                    StoreError::DuplicateAccount(account.account_id.clone())
                } else {
                    sqlite("create account", &err)
                }
            })?;
        Ok(())
    }

    /// The account for a platform identity (provider + provider id).
    ///
    /// `None` means no account is linked to that identity, which is the shape of a first login.
    ///
    /// # Errors
    /// [`StoreError::Sqlite`].
    pub fn account_for_identity(
        &self,
        provider: &str,
        provider_id: &str,
    ) -> Result<Option<Account>, StoreError> {
        self.conn
            .query_row(
                "SELECT a.account_id, a.display_name, a.status, a.created_at
                   FROM identities i
                   JOIN accounts a ON a.account_id = i.account_id
                  WHERE i.provider = ?1 AND i.provider_id = ?2",
                params![provider, provider_id],
                row_to_account,
            )
            .optional()
            .map_err(|err| sqlite("account for identity", &err))
    }

    /// Link a platform identity to an account.
    ///
    /// One account can hold several identities; `(provider, provider_id)` may belong to exactly one
    /// account. Linking an identity that is already linked fails: silently repointing it would move
    /// a player's characters to whoever logged in second.
    ///
    /// # Errors
    /// [`StoreError::UnknownAccount`] when the account does not exist, and [`StoreError::Sqlite`]
    /// when the identity is already linked or the insert fails.
    pub fn create_identity(
        &self,
        provider: &str,
        provider_id: &str,
        account_id: &str,
    ) -> Result<(), StoreError> {
        self.conn
            .execute(
                "INSERT INTO identities (provider, provider_id, account_id) VALUES (?1, ?2, ?3)",
                params![provider, provider_id, account_id],
            )
            .map_err(|err| {
                if is_foreign_key(&err) {
                    StoreError::UnknownAccount(account_id.to_string())
                } else {
                    sqlite("create identity", &err)
                }
            })?;
        Ok(())
    }

    /// Insert a character row for an account.
    ///
    /// # Errors
    /// [`StoreError::DuplicateCharacter`] if the id exists, [`StoreError::UnknownAccount`] if the
    /// owning account does not (the foreign key), [`StoreError::Sqlite`] otherwise.
    pub fn create_character(&self, character: &Character) -> Result<(), StoreError> {
        self.conn
            .execute(
                "INSERT INTO characters
                     (character_id, account_id, name, world_id, created_at, modified_at, deleted)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    character.character_id,
                    character.account_id,
                    character.name,
                    character.world_id,
                    character.created_at,
                    character.modified_at,
                    character.deleted
                ],
            )
            .map_err(|err| {
                if is_foreign_key(&err) {
                    StoreError::UnknownAccount(character.account_id.clone())
                } else if is_primary_key(&err) {
                    StoreError::DuplicateCharacter(character.character_id.clone())
                } else {
                    sqlite("create character", &err)
                }
            })?;
        Ok(())
    }

    /// Every character belonging to an account, ordered by `created_at` then id.
    ///
    /// Tombstoned rows are included: the caller decides whether a deleted character is listed, and
    /// the client's own panel is the authority on that. An account with no characters is an empty
    /// vector, not an error — a fresh account is the normal case, not a failure.
    ///
    /// # Errors
    /// [`StoreError::Sqlite`].
    pub fn characters_for(&self, account_id: &str) -> Result<Vec<Character>, StoreError> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT character_id, account_id, name, world_id, created_at, modified_at, deleted
                   FROM characters
                  WHERE account_id = ?1
                  ORDER BY created_at ASC, character_id ASC",
            )
            .map_err(|err| sqlite("prepare characters for account", &err))?;
        let rows = stmt
            .query_map(params![account_id], row_to_character)
            .map_err(|err| sqlite("characters for account", &err))?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|err| sqlite("read character row", &err))
    }

    /// One character by id.
    ///
    /// Returns tombstoned rows too: [`Store::delete_character`] is a tombstone, and a world that
    /// still holds the id must be able to learn that the character was deleted rather than that it
    /// never existed.
    ///
    /// # Errors
    /// [`StoreError::Sqlite`].
    pub fn character(&self, character_id: &str) -> Result<Option<Character>, StoreError> {
        self.conn
            .query_row(
                "SELECT character_id, account_id, name, world_id, created_at, modified_at, deleted
                   FROM characters
                  WHERE character_id = ?1",
                params![character_id],
                row_to_character,
            )
            .optional()
            .map_err(|err| sqlite("character by id", &err))
    }

    /// Mark a character deleted (tombstone; never a hard delete).
    ///
    /// Deleting an id that is already deleted, or that never existed, is a no-op: a retried delete
    /// after a timeout must not fail, and the caller has no way to distinguish the two cases anyway.
    ///
    /// # Errors
    /// [`StoreError::Sqlite`].
    pub fn delete_character(&self, character_id: &str) -> Result<(), StoreError> {
        self.conn
            .execute(
                "UPDATE characters SET deleted = 1 WHERE character_id = ?1",
                params![character_id],
            )
            .map_err(|err| sqlite("delete character", &err))?;
        Ok(())
    }

    /// The schema version currently applied.
    ///
    /// # Errors
    /// [`StoreError::Sqlite`].
    pub fn schema_version(&self) -> Result<u32, StoreError> {
        read_version(&self.conn)
    }
}

/// Build an account from a row selected in the column order every query above uses.
fn row_to_account(row: &Row<'_>) -> rusqlite::Result<Account> {
    Ok(Account {
        account_id: row.get(0)?,
        display_name: row.get(1)?,
        status: row.get(2)?,
        created_at: row.get(3)?,
    })
}

/// Build a character from a row selected in the column order every query above uses.
fn row_to_character(row: &Row<'_>) -> rusqlite::Result<Character> {
    Ok(Character {
        character_id: row.get(0)?,
        account_id: row.get(1)?,
        name: row.get(2)?,
        world_id: row.get(3)?,
        created_at: row.get(4)?,
        modified_at: row.get(5)?,
        deleted: row.get(6)?,
    })
}

/// The extended SQLite result code, when the failure is a constraint violation.
///
/// The extended code is what makes the translation honest: `SQLITE_CONSTRAINT` covers the primary
/// key, the foreign key and every `CHECK`, and a variant chosen from the plain code would report a
/// duplicate account for an unrelated constraint failure.
fn constraint_code(error: &rusqlite::Error) -> Option<i32> {
    match error {
        rusqlite::Error::SqliteFailure(inner, _)
            if inner.code == rusqlite::ErrorCode::ConstraintViolation =>
        {
            Some(inner.extended_code)
        }
        _ => None,
    }
}

/// Whether the failure is a duplicate primary key.
fn is_primary_key(error: &rusqlite::Error) -> bool {
    constraint_code(error) == Some(rusqlite::ffi::SQLITE_CONSTRAINT_PRIMARYKEY)
}

/// Whether the failure is a foreign key with no matching parent row.
fn is_foreign_key(error: &rusqlite::Error) -> bool {
    constraint_code(error) == Some(rusqlite::ffi::SQLITE_CONSTRAINT_FOREIGNKEY)
}
