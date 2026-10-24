//! The tickets this world will accept, and where they come from in this phase.
//!
//! WHY THE WORLD HOLDS THEM AT ALL
//! ===============================
//! A session enters the world only with a validated ticket (`docs/archive/odd-tasks/phase-3-world.md` S6): the
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
//! only ages. A message has all three — it is addressed, ordered against the claim that produced
//! it, and its absence is a timeout the world can log.
//!
//! THE FILE IS RE-READ, BECAUSE A TICKET CAN BE MINTED AFTER THE WORLD STARTS
//! ========================================================================
//! The world read the file once, at startup, and that was a measured defect: `regiond` published two
//! tickets *after* `worldd` had read it, the client completed its DTLS handshake and sent its V3
//! registration, and the world never answered — it held zero tickets, so there was nothing to match.
//! The transport, the handshake and the client were all fine. [`TicketStore::refresh`] is the fix,
//! and the tick calls it once per tick.
//!
//! A RELOAD IS NOT A RESET
//! =======================
//! `refresh` keeps every id this world has handed out in its `consumed` set and skips them on each
//! later read. Without that, re-reading the file would put an accepted ticket back into the store
//! and a second client could replay it — the replay S6 forbids. Consuming is permanent for the life
//! of the process, not per file version.
//!
//! A BAD FILE MUST NOT EMPTY A WORKING WORLD
//! =========================================
//! The world is serving players when the file is read again, so a missing, unreadable or
//! half-written file means "nothing new" rather than "no tickets": the previous set stays and only
//! [`TicketStore::load`] fails loudly. `regiond` writes atomically, so the malformed case is defence
//! in depth — but a refresh that emptied the store would reject every login for as long as the
//! damage lasted.
//!
//! THE FILE'S FIELD NAMES ARE `regiond`'s OWN
//! ==========================================
//! `TicketId`, `Signature`, `WorldId`, `CharacterId`, `PersonaId` and `RepAddress` are the keys
//! `regiond` already puts in the HTTP ticket (`apps/regiond/src/routes/game.rs`), so the writer that
//! replaces this file with a message has nothing to rename. `ExpiresAtUnix` is the one addition:
//! the HTTP ticket carries `IssueTime` and no deadline, and a ticket with no deadline cannot be
//! validated — an expired ticket is one of the three rules S6 names, so the expiry has to be a
//! field rather than a constant this module invents.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::time::SystemTime;

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
    /// Every id this world has handed out. A reload must not resurrect one of these.
    consumed: HashSet<String>,
    /// The file's stamp at the last read, so the tick can ask "changed?" without reading bytes.
    loaded: Option<Stamp>,
}

impl TicketStore {
    /// Load from a JSON file: an array of tickets with the fields [`LoginTicket`] needs.
    ///
    /// # Errors
    /// [`TicketError::Read`] when the file cannot be read, [`TicketError::Json`] when it is not the
    /// expected shape, and [`TicketError::Invalid`] / [`TicketError::Duplicate`] when an entry is
    /// one this world must not accept.
    pub fn load(path: &Path) -> Result<Self, TicketError> {
        // Stamped before the read: if the file changes while it is being read, the next `refresh`
        // still sees a different stamp and reads it again, which is the safe direction.
        let stamp = stamp_of(path);
        let mut store = Self::empty();
        for ticket in read(path)? {
            store.insert(ticket);
        }
        store.loaded = stamp;
        Ok(store)
    }

    /// Reload from `path` when the file's modification time changed since the last load.
    ///
    /// Returns how many tickets were added. Consumed ids stay consumed across a reload: re-reading
    /// the file must not resurrect a ticket the world already accepted, or a second client could
    /// replay one. A missing or malformed file is `Ok(0)` — the world keeps the set it has, because
    /// a bad file must not lock out the players already inside — while a file that is there but
    /// cannot be read at all is a [`TicketError::Read`] for the caller to log.
    pub fn refresh(&mut self, path: &Path) -> Result<usize, TicketError> {
        let Some(stamp) = stamp_of(path) else {
            // Missing, or not ours to look at: nothing new rather than nothing left.
            return Ok(0);
        };
        if self.loaded.as_ref() == Some(&stamp) {
            // The common case at 50 Hz: one `metadata` call and no read.
            return Ok(0);
        }
        match read(path) {
            Ok(tickets) => {
                // Stamped from before the read, so a file that changes while it is being read still
                // looks changed next tick.
                self.loaded = Some(stamp);
                Ok(self.merge(tickets))
            }
            // Present but unreadable: an operator problem, and the stamp is deliberately not
            // recorded, so the next tick retries instead of waiting for the file to change again.
            Err(err @ TicketError::Read { .. }) => Err(err),
            Err(err) => {
                // Malformed or unacceptable: keep what the world has, and say so once per change
                // rather than 50 times a second.
                self.loaded = Some(stamp);
                eprintln!("[worldd] ticket file {} ignored: {err}", path.display());
                Ok(0)
            }
        }
    }

    /// Add the tickets a reload found, reporting how many are new.
    ///
    /// A consumed id is skipped rather than re-added (a reload is not a reset), and an id already
    /// held is replaced in place: a re-minted ticket for the same claim is a legitimate retry.
    fn merge(&mut self, tickets: Vec<LoginTicket>) -> usize {
        let mut added = 0;
        for ticket in tickets {
            if self.consumed.contains(&ticket.ticket_id) {
                continue;
            }
            if !self.tickets.contains_key(&ticket.ticket_id) {
                added += 1;
            }
            self.insert(ticket);
        }
        added
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
        let ticket = self.tickets.remove(ticket_id)?;
        // Remembered so a later `refresh` cannot put the same ticket back.
        self.consumed.insert(ticket_id.to_owned());
        Some(ticket)
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

/// The 32-byte session token the client stores: the ticket id without its dashes.
///
/// For a UUID ticket id that is exactly 32 bytes, the form first-light measured the client echoing
/// back. The value is opaque to the client, so a shorter id is zero-padded rather than refused.
///
/// It lives here rather than in `entry.rs` because it is derived from a ticket id, and `entry.rs` is
/// at its line limit.
#[must_use]
pub fn session_token(ticket_id: &str) -> [u8; 32] {
    let mut token = [0u8; 32];
    for (slot, byte) in token
        .iter_mut()
        .zip(ticket_id.bytes().filter(|byte| *byte != b'-'))
    {
        *slot = byte;
    }
    token
}

/// A file's identity at the moment it was read.
///
/// The modification time is the primary signal and the length is the secondary one, because some
/// filesystems stamp mtime at one-second resolution: two writes inside one second to files of equal
/// length would otherwise look unchanged. The pair costs one `metadata` call per tick.
#[derive(Debug, Clone, PartialEq, Eq)]
struct Stamp {
    modified: Option<SystemTime>,
    len: u64,
}

/// The stamp of `path`, or `None` when it cannot be stat'ed.
fn stamp_of(path: &Path) -> Option<Stamp> {
    let metadata = std::fs::metadata(path).ok()?;
    Some(Stamp {
        modified: metadata.modified().ok(),
        len: metadata.len(),
    })
}

/// Read and validate one ticket file.
fn read(path: &Path) -> Result<Vec<LoginTicket>, TicketError> {
    let text = std::fs::read_to_string(path).map_err(|source| TicketError::Read {
        path: path.to_path_buf(),
        source,
    })?;
    let entries: Vec<TicketFile> =
        serde_json::from_str(&text).map_err(|source| TicketError::Json {
            path: path.to_path_buf(),
            source,
        })?;
    let mut seen = HashSet::new();
    let mut tickets = Vec::with_capacity(entries.len());
    for (index, entry) in entries.into_iter().enumerate() {
        let ticket = entry.into_ticket(index)?;
        if !seen.insert(ticket.ticket_id.clone()) {
            return Err(TicketError::Duplicate {
                ticket_id: ticket.ticket_id,
            });
        }
        tickets.push(ticket);
    }
    Ok(tickets)
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
