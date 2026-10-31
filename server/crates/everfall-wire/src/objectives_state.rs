//! The mask-selected body of state type index 3857, decoded by the client's readers.
//!
//! `codec.objectives-replicated-state` is Atlas card 3857: the Javelin
//! `ObjectivesComponentReplicatedState` state fragment (key 22). Its body is not a
//! flat field list, which is why the generated codec refuses the card: the reader
//! picks members out of a presence mask, and each present member is itself a
//! container whose elements are fixed-size records. This module is the hand-written
//! codec for exactly that shape, and every rule in it comes from one decompiled
//! reader on build 30fe6461:
//!
//! * class reader `0x1417b5080` — one mask byte per chunk of eight registered
//!   members, then each present member's reader;
//! * group reader `0x1417b5330` — one 7-bit mask byte per chunk of eight in-group
//!   members, `0x80` marking a further mask byte, then each present member's
//!   reader at the member's vtable `+0x30`;
//! * member readers `0x143a69a10` (`activeObjectives`) and `0x143a69710`
//!   (`taskStates`) — a prefix-varint delta count, and when it is zero a boolean
//!   presence byte with an optional prefix-varint, then a prefix-varint snapshot
//!   count and that many elements;
//! * element readers `0x145cea3e0`/`0x145b520f0`/`0x145b55b70` and
//!   `0x143adec40` — the field order and widths below.
//!
//! Only the delta count `0` branch is measured: the client's non-zero branch (a
//! mask byte per chunk, then per element a prefix-varint id and a presence byte)
//! is recovered but has no instance in the recorded bundles, so it is refused
//! rather than guessed. A refusal names what it refused; it never invents a layout.

use core::fmt;

use crate::framing::{Reader, WireError, Writer};

/// A body that does not match the layout Atlas card 3857 says it has.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub enum StateError {
    /// A primitive ran out of bytes or left bytes behind.
    Wire(WireError),
    /// A zero-or-one byte held something else, which the client also refuses.
    NotBoolean {
        /// The field holding the offending value.
        field: &'static str,
        /// The value found.
        value: u8,
    },
    /// A member whose reader this crate has not recovered is set in a mask.
    Unsupported {
        /// What kind of member was set, e.g. `"state group"`.
        what: &'static str,
        /// Its index within its mask.
        value: u64,
    },
}

impl fmt::Display for StateError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Wire(error) => write!(f, "{error}"),
            Self::NotBoolean { field, value } => {
                write!(f, "field {field} is {value}, not zero or one")
            }
            Self::Unsupported { what, value } => {
                write!(f, "{what} {value} has no recovered reader")
            }
        }
    }
}

impl std::error::Error for StateError {}

impl From<WireError> for StateError {
    fn from(error: WireError) -> Self {
        Self::Wire(error)
    }
}

/// A whole 3857 body: a mask over the registered members and those it selects.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ObjectivesStateBody {
    /// Bit `i` set means registered member `i` is on the wire, in the order
    /// `taskStartTimes`, `trackedObjectives`, `completedObjectives`,
    /// `activeObjectives`, `taskStates`, `objectivePoiEntityIds`,
    /// `gracePeriodEndTime`, `dynamicPoiIndices`.
    pub group_mask: u8,
    /// The present members, in that order.
    pub groups: Vec<StateGroup>,
}

/// One present registered member and the in-group members it selects.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StateGroup {
    /// Bit `i` set means in-group member `i` is on the wire. Only group 1 — the
    /// seven containers — has a recovered entry mask.
    pub entry_mask: u8,
    /// The present in-group members, in registration order.
    pub entries: Vec<StateEntry>,
}

/// An in-group member that has a recovered reader.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StateEntry {
    /// In-group member 3, `activeObjectives`.
    ActiveObjectives(ActiveObjectives),
    /// In-group member 4, `taskStates`.
    TaskStates(TaskStates),
}

/// `activeObjectives`: a delta count, a presence marker, then a snapshot.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActiveObjectives {
    /// The prefix-varint delta count. Only `Some(0)` is measured.
    pub delta: Option<u64>,
    /// The snapshot elements.
    pub elements: Vec<ActiveObjective>,
}

/// `taskStates`: a delta count, a presence marker, then a snapshot.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TaskStates {
    /// The prefix-varint delta count. Only `Some(0)` is measured.
    pub delta: Option<u64>,
    /// The snapshot elements.
    pub elements: Vec<TaskState>,
}

/// One `activeObjectives` element, 56 bytes in the measured body.
///
/// Field names carry the offset the client's reader stores to, because no field's
/// meaning is established: the reader fixes the order and the widths, nothing more.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActiveObjective {
    /// Element `+0x08`, read by `0x145b54090`.
    pub u32_a08: u32,
    /// Element `+0x10`, read by `0x145cea3e0`.
    pub u64_a10: u64,
    /// Element `+0x18`, read by `0x145cea3e0`.
    pub u32_a18: u32,
    /// Element `+0x1c`, sixteen raw bytes read by `0x145b520f0`.
    pub guid_a1c: [u8; 16],
    /// Element `+0x38`, read by `0x145b520f0`.
    pub u64_a38: u64,
    /// Element `+0x40`, a big-endian `u16` read by `0x14087a360`.
    pub u16_a40: u16,
    /// Element `+0x42`, a zero-or-one byte read by `0x145b520f0`.
    pub u8_a42: u8,
    /// Element `+0x43`, a zero-or-one byte read by `0x145b520f0`.
    pub u8_a43: u8,
    /// Element `+0x44`, a zero-or-one byte read by `0x145b520f0`.
    pub u8_a44: u8,
    /// Element `+0x45`, a zero-or-one byte read by `0x145b55b70`.
    pub u8_a45: u8,
    /// Element `+0x50`, read by `0x145b55b70`.
    pub u64_a50: u64,
    /// Element `+0x58`, a zero-or-one byte read by `0x145b55b70`.
    pub u8_a58: u8,
    /// The element's trailing `u32` list at `+0x60`, at most seven, read by
    /// `0x145b55b70`.
    pub index_list: Vec<u32>,
}

/// One `taskStates` element, 18 bytes in the measured body, read by `0x143adec40`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TaskState {
    /// Element `+0x10`.
    pub u64_a10: u64,
    /// Element `+0x18`, a raw byte.
    pub u8_a18: u8,
    /// Element `+0x1c`, a big-endian `u32`.
    pub u32_a1c: u32,
    /// Element `+0x20`, a big-endian `u32`.
    pub u32_a20: u32,
    /// Element `+0x24`, a raw byte.
    pub u8_a24: u8,
}

/// The largest trailing index list `0x145b55b70` accepts.
const MAX_INDEX_LIST: u64 = 7;

/// Reads a zero-or-one byte; anything else is refused, as the client refuses it.
fn boolean(reader: &mut Reader<'_>, field: &'static str) -> Result<u8, StateError> {
    let value = reader.u8(field)?;
    if value > 1 {
        return Err(StateError::NotBoolean { field, value });
    }
    Ok(value)
}

/// Reads the client's `0`-delta branch: a boolean, an optional varint, a snapshot.
fn delta(reader: &mut Reader<'_>, field: &'static str) -> Result<Option<u64>, StateError> {
    if boolean(reader, field)? == 0 {
        return Ok(None);
    }
    Ok(Some(reader.prefix_varint(field)?))
}

fn read_active(reader: &mut Reader<'_>) -> Result<ActiveObjectives, StateError> {
    if reader.prefix_varint("activeObjectives.count")? != 0 {
        return Err(StateError::Unsupported {
            what: "non-zero activeObjectives delta count",
            value: 0,
        });
    }
    let delta = delta(reader, "activeObjectives.delta")?;
    let count = reader.prefix_varint("activeObjectives.snapshot.count")?;
    let mut elements = Vec::new();
    for _ in 0..count {
        elements.push(read_active_element(reader)?);
    }
    Ok(ActiveObjectives { delta, elements })
}

fn read_active_element(reader: &mut Reader<'_>) -> Result<ActiveObjective, StateError> {
    Ok(ActiveObjective {
        u32_a08: reader.u32be("active.u32_a08")?,
        u64_a10: reader.u64be("active.u64_a10")?,
        u32_a18: reader.u32be("active.u32_a18")?,
        guid_a1c: reader
            .take("active.guid_a1c", 16)?
            .try_into()
            .expect("take(16) returns sixteen bytes"),
        u64_a38: reader.u64be("active.u64_a38")?,
        u16_a40: reader.u16be("active.u16_a40")?,
        u8_a42: boolean(reader, "active.u8_a42")?,
        u8_a43: boolean(reader, "active.u8_a43")?,
        u8_a44: boolean(reader, "active.u8_a44")?,
        u8_a45: boolean(reader, "active.u8_a45")?,
        u64_a50: reader.u64be("active.u64_a50")?,
        u8_a58: boolean(reader, "active.u8_a58")?,
        index_list: {
            let len = reader.prefix_varint("active.index_list")?;
            if len > MAX_INDEX_LIST {
                return Err(StateError::Unsupported {
                    what: "active index list longer than seven",
                    value: len,
                });
            }
            let mut list = Vec::new();
            for _ in 0..len {
                list.push(reader.u32be("active.index_list[]")?);
            }
            list
        },
    })
}

fn read_task_states(reader: &mut Reader<'_>) -> Result<TaskStates, StateError> {
    if reader.prefix_varint("taskStates.count")? != 0 {
        return Err(StateError::Unsupported {
            what: "non-zero taskStates delta count",
            value: 0,
        });
    }
    let delta = delta(reader, "taskStates.delta")?;
    let count = reader.prefix_varint("taskStates.snapshot.count")?;
    let mut elements = Vec::new();
    for _ in 0..count {
        elements.push(TaskState {
            u64_a10: reader.u64be("task.u64_a10")?,
            u8_a18: reader.u8("task.u8_a18")?,
            u32_a1c: reader.u32be("task.u32_a1c")?,
            u32_a20: reader.u32be("task.u32_a20")?,
            u8_a24: reader.u8("task.u8_a24")?,
        });
    }
    Ok(TaskStates { delta, elements })
}

/// Decode one 3857 body. The body must be consumed exactly.
///
/// # Errors
///
/// Returns [`StateError`] when a primitive is truncated, a mask selects a member
/// whose reader is not recovered, a zero-or-one byte holds another value, or the
/// body has bytes left after its last field.
pub fn decode(body: &[u8]) -> Result<ObjectivesStateBody, StateError> {
    let mut reader = Reader::new(body);
    let group_mask = reader.u8("group_mask")?;
    let mut groups = Vec::new();
    for index in 0..8u64 {
        if group_mask & (1 << index) == 0 {
            continue;
        }
        if index != 1 {
            return Err(StateError::Unsupported {
                what: "state group",
                value: index,
            });
        }
        let entry_mask = reader.u8("entry_mask")?;
        let mut entries = Vec::new();
        for entry in 0..7u64 {
            if entry_mask & (1 << entry) == 0 {
                continue;
            }
            entries.push(match entry {
                3 => StateEntry::ActiveObjectives(read_active(&mut reader)?),
                4 => StateEntry::TaskStates(read_task_states(&mut reader)?),
                _ => {
                    return Err(StateError::Unsupported {
                        what: "in-group member",
                        value: entry,
                    });
                }
            });
        }
        groups.push(StateGroup {
            entry_mask,
            entries,
        });
    }
    reader.finish()?;
    Ok(ObjectivesStateBody { group_mask, groups })
}

fn write_delta(writer: &mut Writer<'_>, delta: Option<u64>) -> Result<(), StateError> {
    match delta {
        None => writer.u8(0),
        Some(value) => {
            writer.u8(1);
            writer.prefix_varint(value)?;
        }
    }
    Ok(())
}

/// Encode one 3857 body back to its bytes.
///
/// # Errors
///
/// Returns [`StateError`] when a count or prefix varint does not fit the wire
/// form, which is the only value a decoded body can provoke.
pub fn encode(body: &ObjectivesStateBody) -> Result<Vec<u8>, StateError> {
    let mut out = Vec::new();
    let mut writer = Writer::new(&mut out);
    writer.u8(body.group_mask);
    for group in &body.groups {
        writer.u8(group.entry_mask);
        for entry in &group.entries {
            match entry {
                StateEntry::ActiveObjectives(active) => {
                    writer.prefix_varint(0)?;
                    write_delta(&mut writer, active.delta)?;
                    writer.prefix_varint(active.elements.len() as u64)?;
                    for element in &active.elements {
                        writer.u32be(element.u32_a08);
                        writer.u64be(element.u64_a10);
                        writer.u32be(element.u32_a18);
                        writer.raw(&element.guid_a1c);
                        writer.u64be(element.u64_a38);
                        writer.u16be(element.u16_a40);
                        writer.u8(element.u8_a42);
                        writer.u8(element.u8_a43);
                        writer.u8(element.u8_a44);
                        writer.u8(element.u8_a45);
                        writer.u64be(element.u64_a50);
                        writer.u8(element.u8_a58);
                        writer.prefix_varint(element.index_list.len() as u64)?;
                        for index in &element.index_list {
                            writer.u32be(*index);
                        }
                    }
                }
                StateEntry::TaskStates(tasks) => {
                    writer.prefix_varint(0)?;
                    write_delta(&mut writer, tasks.delta)?;
                    writer.prefix_varint(tasks.elements.len() as u64)?;
                    for element in &tasks.elements {
                        writer.u64be(element.u64_a10);
                        writer.u8(element.u8_a18);
                        writer.u32be(element.u32_a1c);
                        writer.u32be(element.u32_a20);
                        writer.u8(element.u8_a24);
                    }
                }
            }
        }
    }
    Ok(out)
}
