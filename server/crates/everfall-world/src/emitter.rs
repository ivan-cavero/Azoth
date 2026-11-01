//! Turning a decision into the state the server replicates.
//!
//! This is the emission half of the boundary. A [`Decision`] says what the world
//! did with a request; the client never receives a reply (the Objectives family
//! has no reply message), so the answer it can observe is the replicated-state
//! component. One bundle is decoded, the decision is applied to that component in
//! typed form, and the bundle is assembled again by the generic framing.
//!
//! Three of the record's nine fragments are typed today (keys 19, 22 and 74), so
//! the bundle re-emits them from typed values rather than replaying their bytes.
//! The other six are still `Opaque` runs copied from the recorded body, and
//! [`Emission::authored_payload_bytes`] counts the difference: it is the KPI this
//! milestone is measured by, not a cosmetic number. Replaying a fragment is an
//! emulator standing in for a server, so every run that remains is named in
//! [`Emission::replayed_fragments`].
//!
//! Why the correction lands on `activeObjectives`: the one recovered body of
//! `codec.objectives-replicated-state` carries `activeObjectives` and
//! `taskStates`, and its tracked and completed members have their mask bits
//! clear. The Atlas declares no member layout for the cleared members, so
//! `activeObjectives` is the only set of objectives this server can put on the
//! wire today, and a decision that drops objectives the world cannot resolve
//! drops them there.
//!
//! Which element a correction removes is an ASSUMPTION, not a measurement: no
//! field of `codec.objectives-active-objective` has a proven identity meaning, so
//! nothing in the record says which element the dropped id was. The removal takes
//! the tail, and that choice is stated here instead of being hidden in the diff.
//!
//! Nothing here opens a socket. [`Emission`] holds a bundle and reports the
//! chunk ranges a transport would need; the carrier layer does not exist yet, so
//! the bytes cannot leave the process.

use core::fmt;
use core::ops::Range;

use everfall_sim::Decision;
use everfall_wire::generated::{
    CodecObjectivesActiveObjectives, CodecObjectivesReplicatedState,
    CodecObjectivesReplicatedStateEntry,
};
use everfall_wire::{
    Bundle, BundleError, FragmentExtent, FragmentPayload, LocalPlayerState, StateComponent,
    WireError, Writer, chunk_ranges,
};

/// Why a decided bundle could not be assembled.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub enum EmitError {
    /// The bundle carries no `activeObjectives` member to drop from.
    NoActiveObjectives,
    /// The decision drops more objectives than the state holds.
    NotEnoughObjectives {
        /// Active objectives the state carries.
        held: usize,
        /// Objectives the decision dropped.
        remove: usize,
    },
    /// The bundle framing refused to decode or encode.
    Bundle(BundleError),
    /// A card's codec refused a value.
    Codec(WireError),
}

impl From<BundleError> for EmitError {
    fn from(source: BundleError) -> Self {
        Self::Bundle(source)
    }
}

impl From<WireError> for EmitError {
    fn from(source: WireError) -> Self {
        Self::Codec(source)
    }
}

impl fmt::Display for EmitError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NoActiveObjectives => {
                write!(f, "the bundle carries no activeObjectives member")
            }
            Self::NotEnoughObjectives { held, remove } => write!(
                f,
                "the decision drops {remove} objective(s), the state holds {held}"
            ),
            Self::Bundle(source) => write!(f, "bundle: {source}"),
            Self::Codec(source) => write!(f, "codec: {source}"),
        }
    }
}

impl std::error::Error for EmitError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Bundle(source) => Some(source),
            Self::Codec(source) => Some(source),
            _ => None,
        }
    }
}

/// A bundle the world has decided on and is ready to emit.
#[derive(Debug, Clone, PartialEq)]
pub struct Emission {
    state: Bundle<LocalPlayerState>,
    removed: usize,
}

/// Assemble the state the world emits for one decided request.
///
/// The bundle is the recorded state the world holds; `decision` is the
/// simulation's answer to the request that changed it. The returned emission
/// carries the same prologue, the same record id, the same fragment keys and the
/// same untouched fragments, with the decided change applied to the objectives
/// component. Every fragment the Atlas has a layout for is re-emitted from its
/// typed value; the rest are the recorded runs.
///
/// # Errors
/// Returns [`EmitError`] when the bundle carries no objectives component, when the
/// decision drops more objectives than the state holds, or when the framing
/// refuses to encode the result.
pub fn emit(
    mut state: Bundle<LocalPlayerState>,
    decision: &Decision,
) -> Result<Emission, EmitError> {
    let component = state
        .components_mut()
        .find_map(LocalPlayerState::objectives_mut)
        .ok_or(EmitError::NoActiveObjectives)?;
    let removed = drop_objectives(component, decision)?;
    Ok(Emission { state, removed })
}

/// Remove from `state` the objectives the decision could not resolve.
fn drop_objectives(
    state: &mut CodecObjectivesReplicatedState,
    decision: &Decision,
) -> Result<usize, EmitError> {
    let remove = match decision {
        Decision::Accepted | Decision::Rejected(_) => 0,
        Decision::Corrected(dropped) => dropped.unknown,
    };
    if remove == 0 {
        return Ok(0);
    }

    let active = active_objectives_mut(state).ok_or(EmitError::NoActiveObjectives)?;
    let held = active.elements.len();
    if held < remove {
        return Err(EmitError::NotEnoughObjectives { held, remove });
    }
    active.elements.truncate(held - remove);
    Ok(remove)
}

/// The `activeObjectives` member of the replicated objectives state.
fn active_objectives_mut(
    state: &mut CodecObjectivesReplicatedState,
) -> Option<&mut CodecObjectivesActiveObjectives> {
    state
        .groups
        .iter_mut()
        .flat_map(|group| group.entries.iter_mut())
        .find_map(|entry| match entry {
            CodecObjectivesReplicatedStateEntry::ActiveObjectives(active) => Some(active),
            CodecObjectivesReplicatedStateEntry::TaskStates(_) => None,
        })
}

impl Emission {
    /// How many active objectives the decision removed.
    pub const fn removed(&self) -> usize {
        self.removed
    }

    /// The decided bundle, for a caller that reads it instead of encoding it.
    pub const fn state(&self) -> &Bundle<LocalPlayerState> {
        &self.state
    }

    /// Payload bytes the emission AUTHORS from typed values.
    ///
    /// The anti-emulator KPI: bytes this server composed from state, not bytes it
    /// copied out of a recording. A typed fragment counts in full.
    ///
    /// # Errors
    /// Returns [`EmitError`] when a component's card refuses to encode.
    pub fn authored_payload_bytes(&self) -> Result<usize, EmitError> {
        let mut authored = 0;
        for record in self.state.records() {
            for fragment in record.fragments() {
                if let FragmentPayload::Component(component) = fragment.payload() {
                    let mut body = Vec::new();
                    component.write_body(&mut Writer::new(&mut body))?;
                    authored += body.len();
                }
            }
        }
        Ok(authored)
    }

    /// Total fragment payload bytes the emission carries.
    ///
    /// # Errors
    /// Returns [`EmitError`] when a component's card refuses to encode.
    pub fn total_payload_bytes(&self) -> Result<usize, EmitError> {
        Ok(self
            .extents()?
            .iter()
            .map(|extent| extent.payload_len)
            .sum())
    }

    /// The fragments still replayed from the recording, as `(key, type, bytes)`.
    ///
    /// Each entry is a component this server cannot author yet; the Atlas has no
    /// recovered payload layout for its type, so its bytes are copied.
    pub fn replayed_fragments(&self) -> Vec<(u64, u64, usize)> {
        let mut out = Vec::new();
        for record in self.state.records() {
            for fragment in record.fragments() {
                if let FragmentPayload::Unrecovered { type_index, run } = fragment.payload() {
                    out.push((fragment.key(), *type_index, run.len()));
                }
            }
        }
        out
    }

    /// The bytes, marker and prologue included.
    ///
    /// # Errors
    /// Returns [`EmitError`] when the framing refuses to encode the bundle.
    pub fn encode(&self) -> Result<Vec<u8>, EmitError> {
        self.state.encode().map_err(EmitError::from)
    }

    /// The fragment extents this emission's own bytes declare.
    ///
    /// A fragment has no length field, so decoding the emitted bytes needs the
    /// widths: each typed component states its own (its codec's body length), and
    /// an unrecovered fragment keeps the measured width of the run it carries.
    ///
    /// # Errors
    /// Returns [`EmitError`] when a component's card refuses to encode.
    pub fn extents(&self) -> Result<Vec<FragmentExtent>, EmitError> {
        let mut out = Vec::new();
        for record in self.state.records() {
            for fragment in record.fragments() {
                let (type_index, payload_len) = match fragment.payload() {
                    FragmentPayload::Component(component) => {
                        let mut body = Vec::new();
                        component.write_body(&mut Writer::new(&mut body))?;
                        (component.type_index(), body.len())
                    }
                    FragmentPayload::Unrecovered { type_index, run } => (*type_index, run.len()),
                };
                out.push(FragmentExtent {
                    key: fragment.key(),
                    type_index,
                    payload_len,
                });
            }
        }
        Ok(out)
    }

    /// The chunk offsets a transport would need to carry this emission.
    ///
    /// # Errors
    /// Returns [`EmitError`] when the framing refuses to encode the bundle.
    pub fn chunk_ranges(&self) -> Result<Vec<Range<usize>>, EmitError> {
        Ok(chunk_ranges(self.encode()?.len()))
    }
}
