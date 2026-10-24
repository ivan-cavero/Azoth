//! `TicketStore::refresh`, driven against real files and no socket.
//!
//! WHY THIS FILE EXISTS
//! ====================
//! The world loaded its ticket file once, at startup, and that was a measured defect: `regiond`
//! published the tickets *after* `worldd` had read the file, so the client completed its DTLS
//! handshake, sent its V3 registration, and never got an answer — the world held zero tickets.
//! These tests pin the reload itself, including the security-relevant part: **a reload is not a
//! reset**, so re-reading the file must not put an accepted ticket back into play.
//!
//! WHY THE MODULE IS INCLUDED BY `#[path]`
//! ======================================
//! `worldd` is a binary crate, so an integration test cannot `use worldd::tickets::…`. Including the
//! real source file compiles the same code the binary runs, which is the only way these assertions
//! prove anything about what the world accepts. It is the arrangement `tests/entry.rs` uses.
//!
//! WHY EVERY WRITE SLEEPS
//! ======================
//! `refresh` decides whether to read by comparing the file's stamp, so a test has to produce a *new*
//! stamp to reach the read path. The stamp is (mtime, length); the sleep is there because mtime
//! resolution is coarse on some filesystems, and two writes inside one resolution tick to files of
//! equal length would otherwise look unchanged. Where a test asserts "adds nothing", a stamp that
//! did *not* change gives the same answer, so the sleep is a helper rather than a hidden assumption.

#[path = "../src/tickets.rs"]
mod tickets;

use std::path::{Path, PathBuf};
use std::time::Duration;

use azoth_session::LoginTicket;

use crate::tickets::{TicketError, TicketStore};

/// A scratch directory outside the worktree, removed when the test ends.
struct Scratch {
    path: PathBuf,
}

impl Scratch {
    /// A fresh directory per test, so two tests in one process cannot collide.
    fn new(name: &str) -> Self {
        let dir = std::env::temp_dir().join(format!("azoth-tickets-{}-{name}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("scratch directory");
        Self {
            path: dir.join("tickets.json"),
        }
    }

    /// Replace the ticket file, then let its stamp settle (see the module docs).
    fn write(&self, body: &str) {
        std::fs::write(&self.path, body).expect("scratch write");
        std::thread::sleep(Duration::from_millis(20));
    }

    fn path(&self) -> &Path {
        &self.path
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
        if let Some(dir) = self.path.parent() {
            let _ = std::fs::remove_dir(dir);
        }
    }
}

/// One ticket in the field names `regiond` writes.
fn ticket(id: &str) -> String {
    format!(
        r#"{{"TicketId":"{id}","Signature":"sig:{id}","WorldId":"world-1","CharacterId":"character-{id}","PersonaId":"persona-1","RepAddress":"127.0.0.1:27000","ExpiresAtUnix":4000000000}}"#
    )
}

/// A ticket file holding exactly `ids`.
fn file(ids: &[&str]) -> String {
    let entries: Vec<String> = ids.iter().map(|id| ticket(id)).collect();
    format!("[{}]", entries.join(","))
}

/// Load a store from a scratch file holding `ids`.
fn loaded(scratch: &Scratch, ids: &[&str]) -> TicketStore {
    scratch.write(&file(ids));
    TicketStore::load(scratch.path()).expect("the scratch file loads")
}

/// 1. An unchanged file adds nothing, twice: the stamp short-circuits before any read.
#[test]
fn an_unchanged_file_adds_nothing() {
    let scratch = Scratch::new("unchanged");
    let mut store = loaded(&scratch, &["t1"]);
    assert_eq!(store.len(), 1);

    assert_eq!(store.refresh(scratch.path()).expect("refresh"), 0);
    assert_eq!(store.refresh(scratch.path()).expect("refresh"), 0);
    assert_eq!(store.len(), 1, "the held set is untouched");
}

/// 2. A ticket minted after the world started is added, and is immediately usable.
#[test]
fn a_ticket_minted_after_startup_is_added() {
    let scratch = Scratch::new("minted");
    let mut store = loaded(&scratch, &["t1"]);

    scratch.write(&file(&["t1", "t2"]));
    assert_eq!(store.refresh(scratch.path()).expect("refresh"), 1);
    assert_eq!(store.len(), 2);
    let consumed = store.consume("t2").expect("the new ticket is consumable");
    assert_eq!(consumed.signature, "sig:t2");
    assert_eq!(consumed.world_id, "world-1");
}

/// 3. The security assertion: a consumed ticket is not resurrected by a reload.
///
/// `regiond` keeps up to 64 tickets in the file, so an accepted one stays listed. If a reload
/// re-added it, a second client could replay a ticket the world already used.
#[test]
fn a_reload_does_not_resurrect_a_consumed_ticket() {
    let scratch = Scratch::new("resurrect");
    let mut store = loaded(&scratch, &["t1"]);
    assert!(store.consume("t1").is_some(), "the first client registers");

    // The region's file still lists t1, and a second claim arrives.
    scratch.write(&file(&["t1", "t2"]));
    assert_eq!(
        store.refresh(scratch.path()).expect("refresh"),
        1,
        "only the ticket that was never used is added"
    );
    assert!(
        store.consume("t1").is_none(),
        "a reload is not a reset: replaying a consumed ticket must fail"
    );
    assert!(store.consume("t2").is_some(), "the new ticket still works");
}

/// 4. A missing file means "nothing new", not "no tickets": the players inside keep playing.
#[test]
fn a_missing_file_is_not_an_error() {
    let scratch = Scratch::new("missing");
    let mut store = loaded(&scratch, &["t1"]);

    std::fs::remove_file(scratch.path()).expect("remove the scratch file");
    assert_eq!(store.refresh(scratch.path()).expect("refresh"), 0);
    assert_eq!(store.len(), 1, "the previous set is intact");
    assert!(store.consume("t1").is_some());
}

/// 5. A half-written file must not empty a working world.
#[test]
fn a_malformed_file_keeps_the_previous_set() {
    let scratch = Scratch::new("malformed");
    let mut store = loaded(&scratch, &["t1"]);

    scratch.write(r#"[{"TicketId":"t2","Sig"#);
    assert_eq!(store.refresh(scratch.path()).expect("refresh"), 0);
    assert_eq!(store.len(), 1, "the previous set is intact");
    assert!(store.consume("t1").is_some(), "and still consumable");
}

/// 6. Same content written again: the stamp changes, the ids do not, so nothing is added.
///
/// This is the mtime check in the direction that matters for the log line: a file the region
/// rewrites whole (which it does on every mint) does not re-announce the tickets already known.
#[test]
fn a_rewritten_file_whose_ids_are_known_adds_nothing() {
    let scratch = Scratch::new("rewritten");
    let body = file(&["t1"]);
    scratch.write(&body);
    let mut store = TicketStore::load(scratch.path()).expect("loads");

    scratch.write(&body);
    assert_eq!(store.refresh(scratch.path()).expect("refresh"), 0);
    assert_eq!(store.len(), 1, "the same ticket is not held twice");
}

// ---------------------------------------------------------------------------------------------
// The store's own unit tests, which used to sit inside `src/tickets.rs`.
//
// They live here because that module is at its 400-line limit and the prose there is the part worth
// keeping: `xtask` refuses a source file over the cap, and moving the tests is cheaper than
// deleting an explanation of why the store exists. Same assertions, same subject.
// ---------------------------------------------------------------------------------------------

/// One ticket, built in memory.
fn login_ticket(id: &str) -> LoginTicket {
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

/// Load a scratch file holding `body` and return the outcome.
fn load(scratch: &Scratch, body: &str) -> Result<TicketStore, TicketError> {
    scratch.write(body);
    TicketStore::load(scratch.path())
}

#[test]
fn loads_the_regiond_field_names() {
    let scratch = Scratch::new("field-names");
    let mut store = load(
        &scratch,
        r#"[{"TicketId":"t1","Signature":"sig:t1","WorldId":"w","CharacterId":"c",
             "PersonaId":"p","RepAddress":"127.0.0.1:9000","ExpiresAtUnix":4000000000}]"#,
    )
    .expect("loads");
    assert_eq!(store.len(), 1);
    let ticket = store.consume("t1").expect("the ticket that was loaded");
    assert_eq!(ticket.signature, "sig:t1");
    assert_eq!(ticket.expires_at_unix, 4_000_000_000);
}

#[test]
fn a_ticket_is_consumed_once() {
    let mut store = TicketStore::empty();
    store.insert(login_ticket("t2"));
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
    let scratch = Scratch::new("empty-credential");
    let err = load(
        &scratch,
        r#"[{"TicketId":"t3","Signature":"  ","WorldId":"w","CharacterId":"c",
             "PersonaId":"p","RepAddress":"a","ExpiresAtUnix":1}]"#,
    )
    .expect_err("must fail");
    assert!(
        matches!(err, TicketError::Invalid {
            field: "Signature",
            ..
        }),
        "{err}"
    );
}

#[test]
fn a_duplicate_id_is_refused() {
    let scratch = Scratch::new("duplicate");
    let one = r#"{"TicketId":"t4","Signature":"s","WorldId":"w","CharacterId":"c",
                  "PersonaId":"p","RepAddress":"a","ExpiresAtUnix":1}"#;
    let err = load(&scratch, &format!("[{one},{one}]")).expect_err("must fail");
    assert!(matches!(err, TicketError::Duplicate { .. }), "{err}");
}
