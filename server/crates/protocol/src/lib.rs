//! Javelin wire codecs, ported from the Python prototype with parity tests.
//!
//! WHY THIS CRATE EXISTS. `docs/ROADMAP.md` section 4 names the wire codecs as the one
//! genuinely port-ready piece of this project: they have round-trip tests against the
//! captured corpus in Python and they do not depend on the replay scaffolding that will
//! be replaced once the server owns the world state. Porting them now gives the later
//! server a shape to build on instead of one to invent, and the parity tests in
//! `tests/parity.rs` keep the two implementations honest against the SAME fixture.
//!
//! WHAT IS DELIBERATELY NOT HERE: the replay pump, the response-scheduling policy and
//! anything else in `services/world/src/azoth_world/rep.py` that exists to make a capture
//! behave. Those are scaffolding, not protocol.
//!
//! Reference implementation: `services/world/src/azoth_world/javelin/` (`varint.py`,
//! `bundle.py`). Where the two disagree, Python is right until a measurement says
//! otherwise, and `scripts/gen-protocol-fixture.py --check` fails if the fixture the
//! Rust tests read stops matching it.

pub mod bundle;
pub mod varint;

pub use bundle::{
    compose_bundle, decode_bundle, encode_bundle, encode_type_marker, looks_like_state_bundle,
    read_type_marker, split_record_payload, with_replication_seq, BundleBody, BundleError,
    Fragment, Record, PROLOGUE_TAIL, STATE_BUNDLE_TYPE, TYPE_MARKER,
};
pub use varint::{decode, decode_from, encode, encode_into, size_of, VarintError, MAX_VALUE};

/// Decode one fragment from a slice delimited by a known boundary.
///
/// Free function so callers do not have to import the module path; mirrors
/// `bundle.parse_fragment` in Python.
pub fn parse_fragment_checked(bytes: &[u8]) -> Result<Fragment, BundleError> {
    Fragment::parse(bytes)
}
