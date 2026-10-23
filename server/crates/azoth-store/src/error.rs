//! The identity database's error type.
//!
//! WHY TYPED VARIANTS AND NOT ONE OPAQUE ERROR
//! ==========================================
//! A caller does not merely log these: it decides. A duplicate account id is a bug in the caller
//! (it minted an id twice) and must not be retried; an unknown account is a bad foreign key and is
//! a client-visible rejection; a database that is ahead of the binary is an operator mistake that
//! must stop the process rather than be retried at all. Collapsing them into one opaque error moves
//! that decision to whoever reads the log, which is too late.
//!
//! WHY `Sqlite` CARRIES A STRING AND NOT `rusqlite::Error`
//! ======================================================
//! Keeping the driver's own type in this enum would put `rusqlite` in every downstream crate's
//! type space and pin its version inside their signatures. The variant keeps the message and the
//! operation that produced it and drops the type. The cost is that a caller cannot match on a
//! SQLite result code; nothing in this design needs to, because every code the login path cares
//! about is already a variant of its own.

use std::fmt;

/// A failure from the identity database.
#[derive(Debug)]
pub enum StoreError {
    /// An account with this id already exists.
    DuplicateAccount(String),
    /// A character with this id already exists.
    DuplicateCharacter(String),
    /// A character or identity names an account that does not exist.
    ///
    /// Raised from the foreign key rather than from a pre-check, so two writers racing on the same
    /// account cannot both pass a "does it exist" read and then both insert.
    UnknownAccount(String),
    /// The database's schema version is newer than this binary understands.
    ///
    /// `open` refuses instead of guessing: writing an older schema's rows into a newer database is
    /// how a rolled-back binary corrupts data that the newer one still expects.
    SchemaAhead {
        /// The version recorded in the database.
        database: u32,
        /// The highest version this binary can apply.
        binary: u32,
    },
    /// Any `rusqlite` failure, wrapped with a short context string.
    Sqlite(String),
}

impl fmt::Display for StoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DuplicateAccount(id) => write!(f, "account {id} already exists"),
            Self::DuplicateCharacter(id) => write!(f, "character {id} already exists"),
            Self::UnknownAccount(id) => write!(f, "account {id} does not exist"),
            Self::SchemaAhead { database, binary } => write!(
                f,
                "database schema version {database} is newer than this binary's {binary}; refusing to open"
            ),
            Self::Sqlite(context) => write!(f, "sqlite: {context}"),
        }
    }
}

impl std::error::Error for StoreError {}

/// Wrap a driver failure with the operation that produced it.
///
/// The operation is the part that matters in a log: SQLite's own message names the constraint but
/// never the query, and "UNIQUE constraint failed" without "create account" in front of it sends
/// the reader looking at the wrong table.
pub(crate) fn sqlite(context: &str, error: &rusqlite::Error) -> StoreError {
    StoreError::Sqlite(format!("{context}: {error}"))
}
