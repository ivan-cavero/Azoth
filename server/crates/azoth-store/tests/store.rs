//! The identity store's public contract: what a login may rely on and what it may not.
//!
//! These tests drive only the public API. The one exception is the schema-ahead test, which bumps
//! the recorded version through a plain `rusqlite` connection: the guard being tested exists to
//! catch a *newer* binary's database, so changing the version through `Store` would test the wrong
//! thing.

use std::path::{Path, PathBuf};

use azoth_store::{Account, Character, SCHEMA_VERSION, Store, StoreError};

/// A unique, empty directory under the system temp dir, removed when it goes out of scope.
///
/// Nothing is written inside the repository: a test database in the worktree would be a scratch
/// path in `git status` and a lock on the next run.
struct TempDb {
    dir: PathBuf,
}

impl TempDb {
    fn new(tag: &str) -> Self {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |elapsed| elapsed.as_nanos());
        let dir = std::env::temp_dir().join(format!(
            "azoth-store-{tag}-{}-{nanos}",
            std::process::id()
        ));
        std::fs::create_dir_all(&dir).expect("create the temp directory");
        Self { dir }
    }

    fn path(&self) -> PathBuf {
        self.dir.join("identity.db")
    }
}

impl Drop for TempDb {
    fn drop(&mut self) {
        // The store is dropped before this by declaration order, so the files are unlocked.
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

fn account(id: &str) -> Account {
    Account {
        account_id: id.to_string(),
        display_name: "Ivan".to_string(),
        status: "active".to_string(),
        created_at: 1_700_000_000,
    }
}

fn character(id: &str, account_id: &str, created_at: i64) -> Character {
    Character {
        character_id: id.to_string(),
        account_id: account_id.to_string(),
        name: format!("{id}-name"),
        world_id: "00000000-0000-4000-8000-000000000001".to_string(),
        created_at,
        modified_at: created_at + 5,
        deleted: false,
    }
}

/// A store with one account already in it, which most of the tests below start from.
fn store_with_account(id: &str) -> Store {
    let store = Store::open_in_memory().expect("open in memory");
    store.create_account(&account(id)).expect("create account");
    store
}

#[test]
fn open_in_memory_applies_migrations() {
    let store = Store::open_in_memory().expect("open in memory");
    assert_eq!(store.schema_version().expect("schema version"), 1);
    assert_eq!(SCHEMA_VERSION, 1);
}

#[test]
fn an_account_round_trips_through_its_identity() {
    let store = store_with_account("acct-1");
    store
        .create_identity("steam", "76561197960287930", "acct-1")
        .expect("link identity");

    let found = store
        .account_for_identity("steam", "76561197960287930")
        .expect("lookup")
        .expect("the identity resolves");
    assert_eq!(found, account("acct-1"));
    assert_eq!(found.display_name, "Ivan");
    assert_eq!(found.status, "active");
    assert_eq!(found.created_at, 1_700_000_000);
}

#[test]
fn an_unlinked_identity_resolves_to_nothing() {
    let store = store_with_account("acct-1");
    assert_eq!(
        store
            .account_for_identity("steam", "76561197960287930")
            .expect("lookup"),
        None
    );
    // A provider that exists on another identity must not match either.
    store
        .create_identity("steam", "76561197960287930", "acct-1")
        .expect("link identity");
    assert_eq!(
        store
            .account_for_identity("epic", "76561197960287930")
            .expect("lookup"),
        None
    );
}

#[test]
fn a_duplicate_account_is_rejected_and_leaves_the_row_alone() {
    let store = store_with_account("acct-1");
    store
        .create_identity("steam", "76561197960287930", "acct-1")
        .expect("link identity");

    let mut clash = account("acct-1");
    clash.display_name = "Someone else".to_string();
    let error = store
        .create_account(&clash)
        .expect_err("a duplicate id must be rejected");
    assert!(
        matches!(&error, StoreError::DuplicateAccount(id) if id == "acct-1"),
        "{error:?}"
    );

    // The rejected write must not have overwritten anything.
    let stored = store
        .account_for_identity("steam", "76561197960287930")
        .expect("lookup")
        .expect("the identity still resolves");
    assert_eq!(stored.display_name, "Ivan");
}

#[test]
fn a_character_round_trips_through_the_account_list() {
    let store = store_with_account("acct-1");
    store
        .create_character(&character("char-1", "acct-1", 100))
        .expect("create character");

    let listed = store.characters_for("acct-1").expect("list");
    assert_eq!(listed, vec![character("char-1", "acct-1", 100)]);
    assert_eq!(store.character("char-1").expect("lookup"), Some(character("char-1", "acct-1", 100)));
}

#[test]
fn characters_come_back_in_created_at_order_not_insert_order() {
    let store = store_with_account("acct-1");
    // Inserted newest first, so an implementation that returned insertion order would fail.
    for (id, created_at) in [("char-3", 300), ("char-1", 100), ("char-2", 200)] {
        store
            .create_character(&character(id, "acct-1", created_at))
            .expect("create character");
    }

    let ids: Vec<String> = store
        .characters_for("acct-1")
        .expect("list")
        .into_iter()
        .map(|c| c.character_id)
        .collect();
    assert_eq!(ids, vec!["char-1", "char-2", "char-3"]);
}

#[test]
fn an_account_with_no_characters_lists_nothing() {
    let store = store_with_account("acct-1");
    assert_eq!(store.characters_for("acct-1").expect("list"), Vec::new());
    // An account id that was never created is also empty, not an error: the caller cannot tell the
    // two apart, and a login for a fresh account must not fail.
    assert_eq!(store.characters_for("acct-absent").expect("list"), Vec::new());
}

#[test]
fn a_character_for_an_unknown_account_is_rejected() {
    let store = store_with_account("acct-1");
    let error = store
        .create_character(&character("char-1", "acct-absent", 100))
        .expect_err("the foreign key must reject an unknown account");
    assert!(
        matches!(&error, StoreError::UnknownAccount(id) if id == "acct-absent"),
        "{error:?}"
    );
    // The rejected insert left nothing behind.
    assert_eq!(store.character("char-1").expect("lookup"), None);
    assert_eq!(store.characters_for("acct-absent").expect("list"), Vec::new());
}

#[test]
fn deleting_a_character_tombstones_it() {
    let store = store_with_account("acct-1");
    store
        .create_character(&character("char-1", "acct-1", 100))
        .expect("create character");

    store.delete_character("char-1").expect("delete");

    let after = store
        .character("char-1")
        .expect("lookup")
        .expect("the row is still there");
    assert!(after.deleted);
    // Everything except the tombstone flag is untouched.
    assert_eq!(
        after,
        Character {
            deleted: true,
            ..character("char-1", "acct-1", 100)
        }
    );
    // A second delete is a no-op, not an error.
    store.delete_character("char-1").expect("delete again");
    store
        .delete_character("char-never-existed")
        .expect("delete an unknown id");
}

#[test]
fn a_character_survives_closing_and_reopening_the_database() {
    let db = TempDb::new("reopen");
    let path = db.path();
    let owner = account("acct-1");
    let hero = character("char-1", "acct-1", 100);

    {
        let store = Store::open(&path).expect("open");
        store.create_account(&owner).expect("create account");
        store
            .create_identity("steam", "76561197960287930", "acct-1")
            .expect("link identity");
        store.create_character(&hero).expect("create character");
    }

    let reopened = Store::open(&path).expect("reopen");
    assert_eq!(reopened.schema_version().expect("schema version"), 1);
    assert_eq!(
        reopened.character("char-1").expect("lookup"),
        Some(hero.clone())
    );
    assert_eq!(reopened.characters_for("acct-1").expect("list"), vec![hero]);
    assert_eq!(
        reopened
            .account_for_identity("steam", "76561197960287930")
            .expect("lookup"),
        Some(owner)
    );
}

#[test]
fn a_newer_database_refuses_to_open() {
    let db = TempDb::new("schema-ahead");
    let path = db.path();
    {
        let store = Store::open(&path).expect("open");
        assert_eq!(store.schema_version().expect("schema version"), 1);
    }
    bump_version(&path, 99);

    let Err(error) = Store::open(&path) else {
        panic!("a database newer than the binary must not open");
    };
    match error {
        StoreError::SchemaAhead { database, binary } => {
            assert_eq!(database, 99);
            assert_eq!(binary, SCHEMA_VERSION);
        }
        other => panic!("expected SchemaAhead, got {other:?}"),
    }
}

/// Write `version` into the database behind the store's back, as a newer binary would have.
fn bump_version(path: &Path, version: i64) {
    let conn = rusqlite::Connection::open(path).expect("open the file directly");
    conn.execute("UPDATE schema_version SET version = ?1", [version])
        .expect("bump the recorded version");
}
