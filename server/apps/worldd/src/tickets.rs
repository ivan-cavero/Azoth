//! The tickets this world will accept, and where they come from in this phase.
//!
//! WHY THE WORLD HOLDS THEM AT ALL
//! ===============================
//! A session enters the world only with a validated ticket (`odd/tasks/phase-3-world.md` S6): the
//! V3 `client_signature` is `sig:<ticket_id>`, the ticket has not expired, and it has not been
//! consumed before. The world cannot derive that from the registration body — the body names a
//! ticket id and nothing more — so the world has to hold the ticket the region minted and match the
//! two. That is the whole job of this module: a store keyed by ticket id that hands a ticket over
//! **once**.
//!
//! IN THIS PHASE THE TICKETS COME FROM A FILE WRITTEN BY `regiond`
//! =============================================================
//! [`TicketStore::load`] reads a JSON array of tickets from a path, and that file is written by
//! `regiond`. This is a development shape and it is temporary.
//!
//! The durable version is a **region-to-world message**, not a file. Plan §7.3 says the world owns
//! topology and placement and the region stores a committed *projection* of it; a file the world
//! reads is a second copy of the region's decisions, so two authorities hold the same fact and
//! nothing can tell which one is stale. A file also has no author, no arrival order and no
//! observable failure: if `regiond` stops writing, the world keeps validating against a set that
//! only ages — which is exactly the "silently different experiment" shape `config.rs` documents for
//! the prototype's environment variables. A message has all three: it is addressed, it is ordered
//! against the claim that produced it, and its absence is a timeout the world can log.
//!
//! THE FILE'S FIELD NAMES ARE `regiond`'s OWN
//! ==========================================
//! `TicketId`, `Signature`, `WorldId`, `CharacterId`, `PersonaId` and `RepAddress` are the keys
//! `regiond` already puts in the HTTP ticket (`apps/regiond/src/routes/game.rs`), so the writer that
//! replaces this file with a message has nothing to rename. `ExpiresAtUnix` is the one addition:
//! the HTTP ticket carries `IssueTime` and no deadline, and a ticket with no deadline cannot be
//! validated — an expired ticket is one of the three rules S6 names, so the expiry has to be a
//! field rather than a constant this module invents.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use azoth_session::LoginTicket;
use serde::Deserialize;

/// Where `regiond` writes the tickets this world accepts, relative to the repository root.
///
/// It lives under the ignored private runtime directory for the same reason the client profile
/// does: a ticket is a credential, and a credential does not belong in Git.
pub const DEFAULT_PATH: &str = "private-client/runtime/tickets.json";

/// The tickets this world will accept. Fed by the region; in this phase, by a file.
#[derive(Debug, Clone, Default)]
pub struct TicketStore {
    tickets: HashMap<String, LoginTicket>,
}

impl TicketStore {
    /// Load from a JSON file: an array of tickets with the fields [`LoginTicket`] needs.
    ///
    /// # Errors
    /// [`TicketError::Read`] when the file cannot be read, [`TicketError::Json`] when it is not the
    /// expected shape, and [`TicketError::Invalid`] / [`TicketError::Duplicate`] when an entry is
    /// one this world must not accept.
    pub fn load(path: &Path) -> Result<Self, TicketError> {
        let text = std::fs::read_to_string(path).map_err(|source| TicketError::Read {
            path: path.to_path_buf(),
            source,
        })?;
        let entries: Vec<TicketFile> =
            serde_json::from_str(&text).map_err(|source| TicketError::Json {
                path: path.to_path_buf(),
                source,
            })?;
        let mut store = Self::empty();
        for (index, entry) in entries.into_iter().enumerate() {
            let ticket = entry.into_ticket(index)?;
            if store.tickets.contains_key(&ticket.ticket_id) {
                return Err(TicketError::Duplicate {
                    ticket_id: ticket.ticket_id,
                });
            }
            store.insert(ticket);
        }
        Ok(store)
    }

    /// An empty store, for tests.
    #[must_use]
    pub fn empty() -> Self {
        Self::default()
    }

    /// Add a ticket, replacing any ticket with the same id.
    ///
    /// Replacement rather than rejection because a re-minted ticket for the same claim is a
    /// legitimate retry, and the newest one is the one the region will hand to the client.
    pub fn insert(&mut self, ticket: LoginTicket) {
        self.tickets.insert(ticket.ticket_id.clone(), ticket);
    }

    /// Take a ticket by id, consuming it. `None` when unknown or already consumed.
    ///
    /// Removing is the point: S6 requires that a ticket is used once, and a store that could look
    /// the same ticket up twice would let two clients register as one player — the defect the
    /// prototype had, where it accepted any registration and rewrote the character id per session.
    pub fn consume(&mut self, ticket_id: &str) -> Option<LoginTicket> {
        self.tickets.remove(ticket_id)
    }

    /// How many unconsumed tickets are held.
    #[must_use]
    pub fn len(&self) -> usize {
        self.tickets.len()
    }

    /// Whether the store holds no unconsumed tickets.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.tickets.is_empty()
    }
}

/// One ticket as `regiond` writes it.
#[derive(Debug, Deserialize)]
#[serde(rename_all = "PascalCase")]
struct TicketFile {
    ticket_id: String,
    signature: String,
    world_id: String,
    character_id: String,
    persona_id: String,
    rep_address: String,
    expires_at_unix: i64,
}

impl TicketFile {
    fn into_ticket(self, index: usize) -> Result<LoginTicket, TicketError> {
        for (field, value) in [
            ("TicketId", &self.ticket_id),
            ("Signature", &self.signature),
            ("WorldId", &self.world_id),
            ("CharacterId", &self.character_id),
        ] {
            if value.trim().is_empty() {
                return Err(TicketError::Invalid { index, field });
            }
        }
        Ok(LoginTicket {
            ticket_id: self.ticket_id,
            signature: self.signature,
            world_id: self.world_id,
            character_id: self.character_id,
            persona_id: self.persona_id,
            rep_address: self.rep_address,
            expires_at_unix: self.expires_at_unix,
        })
    }
}

/// Everything that stops a ticket file from becoming a [`TicketStore`].
#[derive(Debug)]
pub enum TicketError {
    /// The file could not be read.
    Read {
        /// The path that was tried.
        path: PathBuf,
        /// The underlying I/O failure.
        source: std::io::Error,
    },
    /// The file is not a JSON array of ticket objects.
    Json {
        /// The path that was tried.
        path: PathBuf,
        /// The parser's report, which names the line and column.
        source: serde_json::Error,
    },
    /// A required field was empty at this index.
    Invalid {
        /// The entry's position in the array.
        index: usize,
        /// The field that was empty.
        field: &'static str,
    },
    /// Two entries carried the same ticket id, so "which one was consumed" would be ambiguous.
    Duplicate {
        /// The id that appeared twice.
        ticket_id: String,
    },
}

impl std::fmt::Display for TicketError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Read { path, source } => write!(f, "cannot read {}: {source}", path.display()),
            Self::Json { path, source } => {
                write!(f, "{} is not a ticket array: {source}", path.display())
            }
            Self::Invalid { index, field } => {
                write!(f, "ticket {index} has an empty {field}")
            }
            Self::Duplicate { ticket_id } => {
                write!(f, "ticket {ticket_id} appears more than once")
            }
        }
    }
}

impl std::error::Error for TicketError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Read { source, .. } => Some(source),
            Self::Json { source, .. } => Some(source),
            Self::Invalid { .. } | Self::Duplicate { .. } => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ticket(id: &str) -> LoginTicket {
        LoginTicket {
            ticket_id: id.to_string(),
            signature: format!("sig:{id}"),
            world_id: "world-1".to_string(),
            character_id: "character-1".to_string(),
            persona_id: "persona-1".to_string(),
            rep_address: "127.0.0.1:9000".to_string(),
            expires_at_unix: 4_000_000_000,
        }
    }

    /// Write `body` to a scratch file outside the worktree and load it.
    fn load(body: &str) -> Result<TicketStore, TicketError> {
        let path = std::env::temp_dir().join(format!(
            "azoth-tickets-{}-{:?}.json",
            std::process::id(),
            std::thread::current().id()
        ));
        std::fs::write(&path, body).expect("scratch file");
        let loaded = TicketStore::load(&path);
        let _ = std::fs::remove_file(&path);
        loaded
    }

    #[test]
    fn loads_the_regiond_field_names() {
        let store = load(
            r#"[{"TicketId":"t1","Signature":"sig:t1","WorldId":"w","CharacterId":"c",
                 "PersonaId":"p","RepAddress":"127.0.0.1:9000","ExpiresAtUnix":4000000000}]"#,
        )
        .expect("loads");
        assert_eq!(store.len(), 1);
        let ticket = store.ticket("t1");
        assert_eq!(ticket.signature, "sig:t1");
        assert_eq!(ticket.expires_at_unix, 4_000_000_000);
    }

    #[test]
    fn a_ticket_is_consumed_once() {
        let mut store = TicketStore::empty();
        store.insert(ticket("t2"));
        assert!(store.consume("t2").is_some());
        assert!(store.consume("t2").is_none(), "a consumed ticket is gone");
        assert!(store.consume("never-seen").is_none());
        assert!(store.is_empty());
    }

    #[test]
    fn a_missing_file_is_an_error_naming_the_path() {
        let path = Path::new("does/not/exist.json");
        let err = TicketStore::load(path).expect_err("must fail");
        assert!(err.to_string().contains("exist.json"), "{err}");
    }

    #[test]
    fn an_empty_credential_is_refused() {
        let err = load(
            r#"[{"TicketId":"t3","Signature":"  ","WorldId":"w","CharacterId":"c",
                 "PersonaId":"p","RepAddress":"a","ExpiresAtUnix":1}]"#,
        )
        .expect_err("must fail");
        assert!(matches!(err, TicketError::Invalid { field: "Signature", .. }), "{err}");
    }

    #[test]
    fn a_duplicate_id_is_refused() {
        let one = r#"{"TicketId":"t4","Signature":"s","WorldId":"w","CharacterId":"c",
                      "PersonaId":"p","RepAddress":"a","ExpiresAtUnix":1}"#;
        let err = load(&format!("[{one},{one}]")).expect_err("must fail");
        assert!(matches!(err, TicketError::Duplicate { .. }), "{err}");
    }
}

#[cfg(test)]
impl TicketStore {
    /// A ticket still in the store, for the loader test only.
    fn ticket(&self, id: &str) -> &LoginTicket {
        self.tickets.get(id).expect("the ticket that was loaded")
    }
}
