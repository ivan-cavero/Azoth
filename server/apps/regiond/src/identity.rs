//! Who the player is: the seeded account, its persona, its character, and the registry that says
//! which world that character lives on.
//!
//! WHY THE SEED IS DATA IN THE DATABASE AND NOT A RESPONSE
//! ======================================================
//! The prototype answers every login with the same hardcoded placeholder
//! (`routes/identity.py`: one `AZOTH_PERSONA`, one `AZOTH_CHARACTER_ID`), so a second character
//! cannot exist and nothing written before a restart is readable after one. The acceptance for this
//! phase is the opposite property — "restart the region, log in again, and the same character
//! returns" — and that is a property of storage. So the account, its platform identity, its persona
//! and its character are **rows**, and every route reads them.
//!
//! WHY THE PERSONA IS AN `identities` ROW
//! ======================================
//! The persona is load-bearing: the client's credentials reader only accepts a value starting with
//! `amzn1.` (`routes/credentials.py`), and it ties the token exchange, the character panel and the
//! queue ticket to one player. Schema version 1 of `azoth-store` has no persona column, and
//! `identities(provider, provider_id, account_id)` is exactly the durable "identifier → account"
//! mapping a persona needs, so the persona is seeded there under the provider name `persona`. A
//! dedicated `personas` table is a later `azoth-store` migration, not something this binary invents.
//!
//! WHY THE CHARACTER IS CREATED AT STARTUP, WITH A DERIVED NAME
//! ===========================================================
//! "Reach character select" requires one `CharacterMetadata` the client can render and start a login
//! from (`routes/registry.py::_seed_character`); real create-from-zero is a later phase with its own
//! validation rules (§6.4 item `#24`). A restart must return the **same** character — the client's
//! savedata is keyed by it — so the id is minted once and stored, and the name is a pure function of
//! the persona. (The measured cost of a shared name is in `_seed_character`: a second client
//! rendered the placeholder name and its Play button did nothing.)

use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use azoth_region::registry::Registry;
use azoth_store::{Account, Character, Store, StoreError};

use crate::config::Config;

/// The one account this region serves, as the prototype spells it.
///
/// It is the prototype's single hardcoded identity placeholder
/// (`routes/identity.py::AZOTH_CHARACTER_ID`) reused as the **account** id: the account is the
/// durable row a login resolves to, and the character id is now minted by [`mint_uuid_v4`].
pub const AZOTH_ACCOUNT_ID: &str = "11111111-1111-1111-1111-111111111111";

/// What the operator sees for that account. Not the character name.
pub const AZOTH_DISPLAY_NAME: &str = "Azoth";

/// The Steam id the platform account carries through the whole login chain.
pub const AZOTH_STEAM_ID: &str = "76561197960287930";

/// The Steam app id the client sends and the entitlement refers to (`STEAM_APP_ID.1063730`).
pub const AZOTH_STEAM_APP_ID: u32 = 1_063_730;

/// The persona the token exchange, the character panel and the queue ticket all name.
///
/// The `amzn1.developerPersonaId.<uuid>` prefix is not cosmetic: the client's credentials reader
/// looks for a value starting with `amzn1.` and crashes on a response without one.
pub const AZOTH_PERSONA: &str = "amzn1.developerPersonaId.fc906c07-42a2-2dd1-f59f-9c56cf4f212c";

/// The `identities.provider` value for the Steam identity.
pub const STEAM_PROVIDER: &str = "steam";

/// The `identities.provider` value for the account's persona. See the module docs for why.
pub const PERSONA_PROVIDER: &str = "persona";

/// The `accounts.status` value for an account that may log in.
const ACCOUNT_STATUS_ACTIVE: &str = "active";

/// A startup failure. Each variant is a different decision, which is why they are not one string.
#[derive(Debug)]
pub enum IdentityError {
    /// The service cannot start from this configuration or database state. The message names the
    /// path or the inconsistent row.
    Startup(String),
    /// The identity database refused an operation.
    Store(StoreError),
    /// The registry is not renderable or allocatable.
    Region(azoth_region::RegionError),
}

impl std::fmt::Display for IdentityError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Startup(message) => write!(f, "regiond cannot start: {message}"),
            Self::Store(err) => write!(f, "identity database: {err}"),
            Self::Region(err) => write!(f, "world/region registry: {err}"),
        }
    }
}

impl std::error::Error for IdentityError {}

impl From<StoreError> for IdentityError {
    fn from(err: StoreError) -> Self {
        Self::Store(err)
    }
}

impl From<azoth_region::RegionError> for IdentityError {
    fn from(err: azoth_region::RegionError) -> Self {
        Self::Region(err)
    }
}

/// The loaded identity: everything a login route needs, read once at startup.
///
/// WHY NOTHING HERE READS THE DATABASE PER REQUEST
/// ==============================================
/// `azoth-store` is blocking on purpose, so a handler that touched it would have to go through
/// `spawn_blocking` or stall the executor. These rows are "small, per login" (§9.1) and change only
/// when a character is created, so they are read once and the routes answer from memory. Writes
/// (character create/delete) arrive in a later phase and will own their own path.
#[derive(Debug)]
pub struct Identity {
    account: Account,
    persona: String,
    characters: Vec<Character>,
    registry: Registry,
}

impl Identity {
    /// Load the registry, open the database, seed it idempotently, and read the identity back.
    ///
    /// # Errors
    /// [`IdentityError`] naming the missing file or directory, the database failure, or the seed
    /// state this service cannot start from.
    pub fn load(config: &Config) -> Result<Self, IdentityError> {
        let registry = config.registry().map_err(IdentityError::Startup)?;
        let database = config.database_path.as_path();
        let directory = database.parent().unwrap_or(Path::new("."));
        config
            .require_directory(directory, "the identity database's directory")
            .map_err(IdentityError::Startup)?;

        let store = Store::open(database)?;
        let account = seed_account(&store)?;
        let persona = seed_persona(&store, &account)?;
        let characters = seed_characters(&store, &account, &persona, &registry)?;

        Ok(Self {
            account,
            persona,
            characters,
            registry,
        })
    }

    /// The seeded account.
    #[must_use]
    pub fn account(&self) -> &Account {
        &self.account
    }

    /// The persona of the seeded account.
    ///
    /// Delegates to [`Identity::persona_for`] so there is one lookup path and no second value that
    /// could disagree with it.
    #[must_use]
    pub fn persona(&self) -> &str {
        self.persona_for(&self.account.account_id)
            .unwrap_or(&self.persona)
    }

    /// The persona for `account_id`, if that account has one.
    #[must_use]
    pub fn persona_for(&self, account_id: &str) -> Option<&str> {
        if self.account.account_id == account_id {
            Some(self.persona.as_str())
        } else {
            None
        }
    }

    /// Every character belonging to `account_id`, in the directory's order.
    #[must_use]
    pub fn characters_for(&self, account_id: &str) -> Vec<&Character> {
        self.characters
            .iter()
            .filter(|character| character.account_id == account_id)
            .collect()
    }

    /// The one character a login presents: the account's first directory row.
    #[must_use]
    pub fn primary_character(&self) -> Option<&Character> {
        self.characters_for(&self.account.account_id).first().copied()
    }

    /// The region/world registry this region serves.
    #[must_use]
    pub fn registry(&self) -> &Registry {
        &self.registry
    }

    /// A one-line description for the startup log.
    ///
    /// A service that starts with no character and says nothing looks identical to one that is
    /// working, so what was loaded is printed before the socket opens.
    #[must_use]
    pub fn summary(&self) -> String {
        let account = self.account();
        format!(
            "account {} ({}), persona {}, {} character(s); registry {} region(s), {} world(s)",
            account.account_id,
            account.display_name,
            self.persona(),
            self.characters_for(&account.account_id).len(),
            self.registry.regions.len(),
            self.registry.worlds.len()
        )
    }
}

/// Seed the account and its Steam identity, tolerating a database that already has them.
///
/// Check-then-insert rather than a blind insert: seeding runs on one thread at startup, so the race
/// the store's own docs warn about cannot happen here, and the duplicate variants are tolerated so a
/// second `regiond` pointed at the same file starts instead of failing.
fn seed_account(store: &Store) -> Result<Account, IdentityError> {
    if store
        .account_for_identity(STEAM_PROVIDER, AZOTH_STEAM_ID)?
        .is_none()
    {
        let account = Account {
            account_id: AZOTH_ACCOUNT_ID.to_string(),
            display_name: AZOTH_DISPLAY_NAME.to_string(),
            status: ACCOUNT_STATUS_ACTIVE.to_string(),
            created_at: now_unix_seconds(),
        };
        match store.create_account(&account) {
            // The id is our constant, so an existing row already is this account.
            Ok(()) | Err(StoreError::DuplicateAccount(_)) => {}
            Err(err) => return Err(IdentityError::Store(err)),
        }
        store.create_identity(STEAM_PROVIDER, AZOTH_STEAM_ID, AZOTH_ACCOUNT_ID)?;
    }
    store
        .account_for_identity(STEAM_PROVIDER, AZOTH_STEAM_ID)?
        .ok_or_else(|| {
            IdentityError::Startup(format!(
                "steam identity {AZOTH_STEAM_ID} still resolves to no account after seeding"
            ))
        })
}

/// Seed the persona row and verify it belongs to the seeded account.
fn seed_persona(store: &Store, account: &Account) -> Result<String, IdentityError> {
    if store
        .account_for_identity(PERSONA_PROVIDER, AZOTH_PERSONA)?
        .is_none()
    {
        store.create_identity(PERSONA_PROVIDER, AZOTH_PERSONA, &account.account_id)?;
    }
    match store.account_for_identity(PERSONA_PROVIDER, AZOTH_PERSONA)? {
        Some(owner) if owner.account_id == account.account_id => Ok(AZOTH_PERSONA.to_string()),
        // A persona linked to another account would hand this player someone else's characters.
        Some(owner) => Err(IdentityError::Startup(format!(
            "persona {AZOTH_PERSONA} belongs to account {}, not {}",
            owner.account_id, account.account_id
        ))),
        None => Err(IdentityError::Startup(format!(
            "persona {AZOTH_PERSONA} still resolves to no account after seeding"
        ))),
    }
}

/// Seed exactly one character when the account has none, then return the directory rows.
///
/// The world binding is the registry's first world, which is this region's world: a character bound
/// to a world the login response does not list renders as "world unavailable" and the Play button
/// does nothing (`routes/registry.py::getlogininfo_doc`).
fn seed_characters(
    store: &Store,
    account: &Account,
    persona: &str,
    registry: &Registry,
) -> Result<Vec<Character>, IdentityError> {
    let existing = store.characters_for(&account.account_id)?;
    if !existing.is_empty() {
        return Ok(existing);
    }
    let world = registry.worlds.first().ok_or_else(|| {
        IdentityError::Startup(
            "the world/region registry lists no worlds, so a character cannot be bound to one"
                .to_string(),
        )
    })?;
    let now = now_unix_seconds();
    let character = Character {
        character_id: mint_uuid_v4(),
        account_id: account.account_id.clone(),
        name: character_name_for(persona),
        world_id: world.id.0.clone(),
        created_at: now,
        modified_at: now,
        deleted: false,
    };
    match store.create_character(&character) {
        Ok(()) | Err(StoreError::DuplicateCharacter(_)) => {}
        Err(err) => return Err(IdentityError::Store(err)),
    }
    Ok(store.characters_for(&account.account_id)?)
}

/// The wall clock, unix seconds.
///
/// `0` rather than an error when the clock is before the epoch: a wire body carrying `0` is
/// parseable and a panic in a startup path is not.
#[must_use]
pub fn now_unix_seconds() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |elapsed| i64::try_from(elapsed.as_secs()).unwrap_or(0))
}

/// The wall clock, unix milliseconds: the access token's `iat`/`exp` are in **milliseconds**
/// ("AGS Auth token iat %lldms").
#[must_use]
pub fn now_unix_millis() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |elapsed| {
            i64::try_from(elapsed.as_millis()).unwrap_or(0)
        })
}

/// A counter that makes two generators seeded in the same nanosecond differ.
static SEED_COUNTER: AtomicU64 = AtomicU64::new(0);

/// A small xorshift generator for identifiers that must not repeat within a process.
///
/// WHY NOT A `rand` DEPENDENCY: nothing generated here is a secret. A ticket id, a character id and
/// the mock credentials' keys only have to differ from each other (the credentials charset is
/// validated, its entropy is not), so a generator that is small and deterministic to test beats a
/// dependency whose job is cryptographic strength this service does not need.
#[derive(Debug, Clone)]
pub struct Rng(u64);

impl Rng {
    /// Seed from the clock and a process counter, so two instances never share a stream.
    #[must_use]
    pub fn from_clock() -> Self {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |elapsed| elapsed.subsec_nanos() as u64 ^ elapsed.as_secs());
        let count = SEED_COUNTER.fetch_add(1, Ordering::Relaxed);
        // splitmix64's constant, and `| 1` keeps the state out of xorshift's fixed point.
        Self((nanos ^ count.wrapping_mul(0x9E37_79B9_7F4A_7C15)) | 1)
    }

    /// The next value: xorshift64*, which has a full period for any non-zero state.
    pub fn next_u64(&mut self) -> u64 {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
}

/// Mint a `UUIDv4` string.
///
/// The version and variant nibbles are forced so the value is a well-formed v4, which is what the
/// client's character and ticket readers expect.
#[must_use]
pub fn mint_uuid_v4() -> String {
    let mut rng = Rng::from_clock();
    let mut bytes = [0_u8; 16];
    for chunk in bytes.chunks_mut(8) {
        chunk.copy_from_slice(&rng.next_u64().to_be_bytes());
    }
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    let hex: String = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
    format!(
        "{}-{}-{}-{}-{}",
        &hex[0..8],
        &hex[8..12],
        &hex[12..16],
        &hex[16..20],
        &hex[20..32]
    )
}

/// The character name for a persona: stable for one persona, different for another.
///
/// FNV-1a rather than a cryptographic hash for the same reason [`Rng`] is hand-rolled — the name
/// only has to be stable across restarts and distinct per persona. The `Azoth_` prefix keeps it
/// recognisably a seed character in a screenshot.
#[must_use]
pub fn character_name_for(persona: &str) -> String {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in persona.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x1000_0000_01b3);
    }
    format!("Azoth_{:08x}", hash & 0xffff_ffff)
}

