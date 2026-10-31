//! The newtype for a byte run whose meaning the Atlas has not named.

/// A raw byte run that keeps its Atlas id and refuses to be read as data.
///
/// A byte run carries a field id (`<card uid>.<field name>`) from the Atlas, so
/// a caller can see *what it is* and never *what it says*. The bytes are private
/// and the type exposes no slice accessor, no `Deref`, and no `AsRef`; the only
/// way to turn a run into something usable is to name the field in a card. This
/// is what stops a generated codec from being a byte shuttle.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Opaque {
    id: &'static str,
    bytes: Vec<u8>,
}

impl Opaque {
    /// The Atlas id of the field this run was decoded from.
    pub const fn id(&self) -> &'static str {
        self.id
    }

    /// Number of bytes in the run.
    pub const fn len(&self) -> usize {
        self.bytes.len()
    }

    /// True when the run is empty.
    pub const fn is_empty(&self) -> bool {
        self.bytes.is_empty()
    }

    /// The id and width, for an operator reading a failed comparison.
    ///
    /// The bytes are deliberately not shown: printing them is the first step of
    /// interpreting an unnamed field, which is the thing this type prevents.
    pub fn describe(&self) -> String {
        format!("{}[{}]", self.id, self.bytes.len())
    }

    /// Build a run from an id and its bytes.
    pub(crate) fn new(id: &'static str, bytes: Vec<u8>) -> Self {
        Self { id, bytes }
    }

    /// The raw bytes, for the encoder only.
    pub(crate) fn as_slice(&self) -> &[u8] {
        &self.bytes
    }
}
