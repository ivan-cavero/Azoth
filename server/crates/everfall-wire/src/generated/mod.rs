// GENERATED FILE -- do not edit by hand.
//!
//! Typed messages and nested sub-codecs derived from the Atlas cards.
//!
//! Produced by `reverse/tools/atlas/ontology-gen.py` (`python ef.py re
//! ontology-gen`) from `research/atlas/ontology/schema.json` and the Atlas
//! concept cards. One struct per codegen-ready card: its fields are that card's
//! body fields under the card's own names, and a raw byte run is an [`Opaque`]
//! that carries its Atlas id.
//!
//! This exact text is written to
//! `server/crates/everfall-wire/src/generated/mod.rs` and mirrored here for
//! review. The record envelope (`00 01` plus the prefix-varint type) is framing
//! owned by `crate::framing` and is never a field.

use crate::framing::{Reader, WireError, Writer};
use crate::opaque::Opaque;

/// `flow.world-entry.rung.registration` — one Atlas card.
///
/// Message card, wire id `3`.
#[expect(
    clippy::struct_excessive_bools,
    reason = "the card models one bool byte per trailing flag"
)]
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FlowWorldEntryRungRegistration {
    /// Body field `unresolved_u32` (`u32be`); meaning unnamed.
    pub unresolved_u32: u32,
    /// Body field `unresolved_u64` (`u64be`); meaning unnamed.
    pub unresolved_u64: u64,
    /// Body field `unresolved_block` (`prefixed_bytes`); meaning unnamed.
    pub unresolved_block: Opaque,
    /// Body field `server_version` (`prefixed_string`).
    pub server_version: String,
    /// Body field `trailing_bool_0` (`bool_byte`); meaning unnamed.
    pub trailing_bool_0: bool,
    /// Body field `trailing_bool_1` (`bool_byte`); meaning unnamed.
    pub trailing_bool_1: bool,
    /// Body field `trailing_bool_2` (`bool_byte`); meaning unnamed.
    pub trailing_bool_2: bool,
    /// Body field `trailing_bool_3` (`bool_byte`); meaning unnamed.
    pub trailing_bool_3: bool,
}

impl FlowWorldEntryRungRegistration {
    /// The Atlas card id.
    pub const UID: &'static str = "flow.world-entry.rung.registration";
    /// The card wire id.
    pub const WIRE_ID: u32 = 3;

    /// Decode one `flow.world-entry.rung.registration` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            unresolved_u32: reader.u32be("unresolved_u32")?,
            unresolved_u64: reader.u64be("unresolved_u64")?,
            unresolved_block: reader.prefixed_opaque(
                "unresolved_block",
                "flow.world-entry.rung.registration.unresolved_block",
            )?,
            server_version: reader.prefixed_string("server_version")?,
            trailing_bool_0: reader.bool_byte("trailing_bool_0")?,
            trailing_bool_1: reader.bool_byte("trailing_bool_1")?,
            trailing_bool_2: reader.bool_byte("trailing_bool_2")?,
            trailing_bool_3: reader.bool_byte("trailing_bool_3")?,
        })
    }

    /// Encode one `flow.world-entry.rung.registration` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u32be(self.unresolved_u32);
        writer.u64be(self.unresolved_u64);
        writer.prefixed_opaque(&self.unresolved_block)?;
        writer.prefixed_string(&self.server_version)?;
        writer.u8(u8::from(self.trailing_bool_0));
        writer.u8(u8::from(self.trailing_bool_1));
        writer.u8(u8::from(self.trailing_bool_2));
        writer.u8(u8::from(self.trailing_bool_3));
        Ok(())
    }
}

/// `msg.update` — one Atlas card.
///
/// Message card, wire id `106`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MsgUpdate {
    /// Body field `blob` (`prefixed_bytes`); meaning unnamed.
    pub blob: Opaque,
}

impl MsgUpdate {
    /// The Atlas card id.
    pub const UID: &'static str = "msg.update";
    /// The card wire id.
    pub const WIRE_ID: u32 = 106;

    /// Decode one `msg.update` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            blob: {
                let value = reader.prefixed_opaque("blob", "msg.update.blob")?;
                if value.len() as u64 > 512 {
                    return Err(WireError::OutOfRange {
                        field: "blob",
                        max: 512,
                        value: value.len() as u64,
                    });
                }
                value
            },
        })
    }

    /// Encode one `msg.update` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.prefixed_opaque(&self.blob)?;
        Ok(())
    }
}

/// `msg.set-replicate-storage` — one Atlas card.
///
/// Message card, wire id `387`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MsgSetReplicateStorage {
    /// Body field `local_facet_id` (`u64be`).
    pub local_facet_id: u64,
    /// Body field `local_actor_id_word0` (`u64be`).
    pub local_actor_id_word0: u64,
    /// Body field `field_c` (`bytes(16)`); meaning unnamed.
    pub field_c: Opaque,
}

impl MsgSetReplicateStorage {
    /// The Atlas card id.
    pub const UID: &'static str = "msg.set-replicate-storage";
    /// The card wire id.
    pub const WIRE_ID: u32 = 387;

    /// Decode one `msg.set-replicate-storage` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            local_facet_id: reader.u64be("local_facet_id")?,
            local_actor_id_word0: reader.u64be("local_actor_id_word0")?,
            field_c: reader.opaque("field_c", "msg.set-replicate-storage.field_c", 16)?,
        })
    }

    /// Encode one `msg.set-replicate-storage` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u64be(self.local_facet_id);
        writer.u64be(self.local_actor_id_word0);
        writer.opaque(&self.field_c);
        Ok(())
    }
}

/// `msg.objectives-update-tracked-objectives` — one Atlas card.
///
/// Message card, wire id `1458`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MsgObjectivesUpdateTrackedObjectives {
    /// Body field `local_facet_id` (`u64be`).
    pub local_facet_id: u64,
    /// Body field `local_actor_id_word0` (`u64be`).
    pub local_actor_id_word0: u64,
    /// Body field `tracked_objective_ids` (`vec<u64be>`).
    pub tracked_objective_ids: Vec<u64>,
}

impl MsgObjectivesUpdateTrackedObjectives {
    /// The Atlas card id.
    pub const UID: &'static str = "msg.objectives-update-tracked-objectives";
    /// The card wire id.
    pub const WIRE_ID: u32 = 1458;

    /// Decode one `msg.objectives-update-tracked-objectives` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            local_facet_id: reader.u64be("local_facet_id")?,
            local_actor_id_word0: reader.u64be("local_actor_id_word0")?,
            tracked_objective_ids: {
                let count = reader.prefix_varint("tracked_objective_ids")?;
                if count > 8 {
                    return Err(WireError::OutOfRange {
                        field: "tracked_objective_ids",
                        max: 8,
                        value: count,
                    });
                }
                let mut value = Vec::new();
                for _ in 0..count {
                    value.push(reader.u64be("tracked_objective_ids")?);
                }
                value
            },
        })
    }

    /// Encode one `msg.objectives-update-tracked-objectives` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u64be(self.local_facet_id);
        writer.u64be(self.local_actor_id_word0);
        writer.prefix_varint(self.tracked_objective_ids.len() as u64)?;
        for value in &self.tracked_objective_ids {
            writer.u64be(*value);
        }
        Ok(())
    }
}

/// `msg.request-spend-attribute-points` — one Atlas card.
///
/// Message card, wire id `1502`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MsgRequestSpendAttributePoints {
    /// Body field `local_facet_id` (`u64be`).
    pub local_facet_id: u64,
    /// Body field `local_actor_id_word0` (`u64be`).
    pub local_actor_id_word0: u64,
    /// Body field `attribute_indices` (`vec<u32be>`).
    pub attribute_indices: Vec<u32>,
    /// Body field `points` (`vec<u32be>`).
    pub points: Vec<u32>,
}

impl MsgRequestSpendAttributePoints {
    /// The Atlas card id.
    pub const UID: &'static str = "msg.request-spend-attribute-points";
    /// The card wire id.
    pub const WIRE_ID: u32 = 1502;

    /// Decode one `msg.request-spend-attribute-points` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            local_facet_id: reader.u64be("local_facet_id")?,
            local_actor_id_word0: reader.u64be("local_actor_id_word0")?,
            attribute_indices: {
                let count = reader.prefix_varint("attribute_indices")?;
                if count > 4 {
                    return Err(WireError::OutOfRange {
                        field: "attribute_indices",
                        max: 4,
                        value: count,
                    });
                }
                let mut value = Vec::new();
                for _ in 0..count {
                    value.push(reader.u32be("attribute_indices")?);
                }
                value
            },
            points: {
                let count = reader.prefix_varint("points")?;
                if count > 700 {
                    return Err(WireError::OutOfRange {
                        field: "points",
                        max: 700,
                        value: count,
                    });
                }
                let mut value = Vec::new();
                for _ in 0..count {
                    value.push(reader.u32be("points")?);
                }
                value
            },
        })
    }

    /// Encode one `msg.request-spend-attribute-points` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u64be(self.local_facet_id);
        writer.u64be(self.local_actor_id_word0);
        writer.prefix_varint(self.attribute_indices.len() as u64)?;
        for value in &self.attribute_indices {
            writer.u32be(*value);
        }
        writer.prefix_varint(self.points.len() as u64)?;
        for value in &self.points {
            writer.u32be(*value);
        }
        Ok(())
    }
}

/// `flow.world-entry.rung.self-identification` — one Atlas card.
///
/// Message card, wire id `1628`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FlowWorldEntryRungSelfIdentification {
    /// Body field `prefix_lead` (`u8`); meaning unnamed.
    pub prefix_lead: u8,
    /// Body field `identity_guid_prefix` (`guid16`).
    pub identity_guid_prefix: Opaque,
    /// Body field `vtable_tag` (`u32be`).
    pub vtable_tag: u32,
    /// Body field `prefix_data` (`bytes(107)`); meaning unnamed.
    pub prefix_data: Opaque,
    /// Body field `grid_side` (`u8`).
    pub grid_side: u8,
    /// Body field `grid_header` (`bytes(2)`); meaning unnamed.
    pub grid_header: Opaque,
    /// Body field `grid_cells` (`bytes(12544)`).
    pub grid_cells: Opaque,
    /// Body field `tail_zeros` (`bytes(10)`); meaning unnamed.
    pub tail_zeros: Opaque,
    /// Body field `tail_lead` (`u8`); meaning unnamed.
    pub tail_lead: u8,
    /// Body field `identity_guid_tail` (`guid16`).
    pub identity_guid_tail: Opaque,
}

impl FlowWorldEntryRungSelfIdentification {
    /// The Atlas card id.
    pub const UID: &'static str = "flow.world-entry.rung.self-identification";
    /// The card wire id.
    pub const WIRE_ID: u32 = 1628;

    /// Decode one `flow.world-entry.rung.self-identification` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            prefix_lead: reader.u8("prefix_lead")?,
            identity_guid_prefix: reader.opaque(
                "identity_guid_prefix",
                "flow.world-entry.rung.self-identification.identity_guid_prefix",
                16,
            )?,
            vtable_tag: reader.u32be("vtable_tag")?,
            prefix_data: reader.opaque(
                "prefix_data",
                "flow.world-entry.rung.self-identification.prefix_data",
                107,
            )?,
            grid_side: reader.u8("grid_side")?,
            grid_header: reader.opaque(
                "grid_header",
                "flow.world-entry.rung.self-identification.grid_header",
                2,
            )?,
            grid_cells: reader.opaque(
                "grid_cells",
                "flow.world-entry.rung.self-identification.grid_cells",
                12544,
            )?,
            tail_zeros: reader.opaque(
                "tail_zeros",
                "flow.world-entry.rung.self-identification.tail_zeros",
                10,
            )?,
            tail_lead: reader.u8("tail_lead")?,
            identity_guid_tail: reader.opaque(
                "identity_guid_tail",
                "flow.world-entry.rung.self-identification.identity_guid_tail",
                16,
            )?,
        })
    }

    /// Encode one `flow.world-entry.rung.self-identification` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u8(self.prefix_lead);
        writer.opaque(&self.identity_guid_prefix);
        writer.u32be(self.vtable_tag);
        writer.opaque(&self.prefix_data);
        writer.u8(self.grid_side);
        writer.opaque(&self.grid_header);
        writer.opaque(&self.grid_cells);
        writer.opaque(&self.tail_zeros);
        writer.u8(self.tail_lead);
        writer.opaque(&self.identity_guid_tail);
        Ok(())
    }
}

/// `flow.world-entry.rung.level-info` — one Atlas card.
///
/// Message card, wire id `1635`.
#[derive(Debug, Clone, PartialEq)]
pub struct FlowWorldEntryRungLevelInfo {
    /// Body field `level_name` (`prefixed_string`).
    pub level_name: String,
    /// Body field `level_path` (`prefixed_string`).
    pub level_path: String,
    /// Body field `level_bounds` (`vec<f32be>[4]`).
    pub level_bounds: [f32; 4],
    /// Body field `unresolved_u64` (`u64be`); meaning unnamed.
    pub unresolved_u64: u64,
    /// Body field `unresolved_u32` (`u32be`); meaning unnamed.
    pub unresolved_u32: u32,
    /// Body field `session_nonce` (`u64be`).
    pub session_nonce: u64,
    /// Body field `unresolved_group` (`bytes(10)`); meaning unnamed.
    pub unresolved_group: Opaque,
    /// Body field `level_context_key` (`u64be`).
    pub level_context_key: u64,
}

impl FlowWorldEntryRungLevelInfo {
    /// The Atlas card id.
    pub const UID: &'static str = "flow.world-entry.rung.level-info";
    /// The card wire id.
    pub const WIRE_ID: u32 = 1635;

    /// Decode one `flow.world-entry.rung.level-info` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            level_name: reader.prefixed_string("level_name")?,
            level_path: reader.prefixed_string("level_path")?,
            level_bounds: {
                let mut value = [0.0; 4];
                for slot in &mut value {
                    *slot = reader.f32be("level_bounds")?;
                }
                value
            },
            unresolved_u64: reader.u64be("unresolved_u64")?,
            unresolved_u32: reader.u32be("unresolved_u32")?,
            session_nonce: reader.u64be("session_nonce")?,
            unresolved_group: reader.opaque(
                "unresolved_group",
                "flow.world-entry.rung.level-info.unresolved_group",
                10,
            )?,
            level_context_key: reader.u64be("level_context_key")?,
        })
    }

    /// Encode one `flow.world-entry.rung.level-info` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.prefixed_string(&self.level_name)?;
        writer.prefixed_string(&self.level_path)?;
        for value in &self.level_bounds {
            writer.f32be(*value);
        }
        writer.u64be(self.unresolved_u64);
        writer.u32be(self.unresolved_u32);
        writer.u64be(self.session_nonce);
        writer.opaque(&self.unresolved_group);
        writer.u64be(self.level_context_key);
        Ok(())
    }
}

/// `msg.receive-settings-from-client` — one Atlas card.
///
/// Message card, wire id `2515`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MsgReceiveSettingsFromClient {
    /// Body field `local_facet_id` (`u64be`).
    pub local_facet_id: u64,
    /// Body field `local_actor_id_word0` (`u64be`).
    pub local_actor_id_word0: u64,
    /// Body field `field_c` (`u32be`); meaning unnamed.
    pub field_c: u32,
}

impl MsgReceiveSettingsFromClient {
    /// The Atlas card id.
    pub const UID: &'static str = "msg.receive-settings-from-client";
    /// The card wire id.
    pub const WIRE_ID: u32 = 2515;

    /// Decode one `msg.receive-settings-from-client` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            local_facet_id: reader.u64be("local_facet_id")?,
            local_actor_id_word0: reader.u64be("local_actor_id_word0")?,
            field_c: reader.u32be("field_c")?,
        })
    }

    /// Encode one `msg.receive-settings-from-client` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u64be(self.local_facet_id);
        writer.u64be(self.local_actor_id_word0);
        writer.u32be(self.field_c);
        Ok(())
    }
}

/// `msg.contracts-lookup-contracts-by-participant` — one Atlas card.
///
/// Message card, wire id `2556`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MsgContractsLookupContractsByParticipant {
    /// Body field `local_facet_id` (`u64be`).
    pub local_facet_id: u64,
    /// Body field `local_actor_id_word0` (`u64be`).
    pub local_actor_id_word0: u64,
    /// Body field `participant_id` (`bytes(16)`); meaning unnamed.
    pub participant_id: Opaque,
    /// Body field `u32_be_1` (`u32be`); meaning unnamed.
    pub u32_be_1: u32,
    /// Body field `u32_be_2` (`u32be`); meaning unnamed.
    pub u32_be_2: u32,
    /// Body field `u32_be_3` (`u32be`); meaning unnamed.
    pub u32_be_3: u32,
    /// Body field `blob_64` (`prefixed_bytes`); meaning unnamed.
    pub blob_64: Opaque,
    /// Body field `blob_256` (`prefixed_bytes`); meaning unnamed.
    pub blob_256: Opaque,
    /// Body field `count_u32` (`u32be`); meaning unnamed.
    pub count_u32: u32,
    /// Body field `index_ids` (`vec<u32be>`); meaning unnamed.
    pub index_ids: Vec<u32>,
    /// Body field `type_ids` (`vec<u16be>`); meaning unnamed.
    pub type_ids: Vec<u16>,
    /// Body field `trailing_id` (`bytes(16)`); meaning unnamed.
    pub trailing_id: Opaque,
}

impl MsgContractsLookupContractsByParticipant {
    /// The Atlas card id.
    pub const UID: &'static str = "msg.contracts-lookup-contracts-by-participant";
    /// The card wire id.
    pub const WIRE_ID: u32 = 2556;

    /// Decode one `msg.contracts-lookup-contracts-by-participant` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            local_facet_id: reader.u64be("local_facet_id")?,
            local_actor_id_word0: reader.u64be("local_actor_id_word0")?,
            participant_id: reader.opaque(
                "participant_id",
                "msg.contracts-lookup-contracts-by-participant.participant_id",
                16,
            )?,
            u32_be_1: reader.u32be("u32_be_1")?,
            u32_be_2: reader.u32be("u32_be_2")?,
            u32_be_3: reader.u32be("u32_be_3")?,
            blob_64: {
                let value = reader.prefixed_opaque(
                    "blob_64",
                    "msg.contracts-lookup-contracts-by-participant.blob_64",
                )?;
                if value.len() as u64 > 64 {
                    return Err(WireError::OutOfRange {
                        field: "blob_64",
                        max: 64,
                        value: value.len() as u64,
                    });
                }
                value
            },
            blob_256: {
                let value = reader.prefixed_opaque(
                    "blob_256",
                    "msg.contracts-lookup-contracts-by-participant.blob_256",
                )?;
                if value.len() as u64 > 256 {
                    return Err(WireError::OutOfRange {
                        field: "blob_256",
                        max: 256,
                        value: value.len() as u64,
                    });
                }
                value
            },
            count_u32: reader.u32be("count_u32")?,
            index_ids: {
                let count = reader.prefix_varint("index_ids")?;
                if count > 3 {
                    return Err(WireError::OutOfRange {
                        field: "index_ids",
                        max: 3,
                        value: count,
                    });
                }
                let mut value = Vec::new();
                for _ in 0..count {
                    value.push(reader.u32be("index_ids")?);
                }
                value
            },
            type_ids: {
                let count = reader.prefix_varint("type_ids")?;
                if count > 25 {
                    return Err(WireError::OutOfRange {
                        field: "type_ids",
                        max: 25,
                        value: count,
                    });
                }
                let mut value = Vec::new();
                for _ in 0..count {
                    value.push(reader.u16be("type_ids")?);
                }
                value
            },
            trailing_id: reader.opaque(
                "trailing_id",
                "msg.contracts-lookup-contracts-by-participant.trailing_id",
                16,
            )?,
        })
    }

    /// Encode one `msg.contracts-lookup-contracts-by-participant` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u64be(self.local_facet_id);
        writer.u64be(self.local_actor_id_word0);
        writer.opaque(&self.participant_id);
        writer.u32be(self.u32_be_1);
        writer.u32be(self.u32_be_2);
        writer.u32be(self.u32_be_3);
        writer.prefixed_opaque(&self.blob_64)?;
        writer.prefixed_opaque(&self.blob_256)?;
        writer.u32be(self.count_u32);
        writer.prefix_varint(self.index_ids.len() as u64)?;
        for value in &self.index_ids {
            writer.u32be(*value);
        }
        writer.prefix_varint(self.type_ids.len() as u64)?;
        for value in &self.type_ids {
            writer.u16be(*value);
        }
        writer.opaque(&self.trailing_id);
        Ok(())
    }
}

/// `msg.objectives-set-objective-auto-pinning` — one Atlas card.
///
/// Message card, wire id `2709`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MsgObjectivesSetObjectiveAutoPinning {
    /// Body field `local_facet_id` (`u64be`).
    pub local_facet_id: u64,
    /// Body field `local_actor_id_word0` (`u64be`).
    pub local_actor_id_word0: u64,
    /// Body field `auto_pinning_flags` (`vec<bool_byte>`).
    pub auto_pinning_flags: Vec<bool>,
}

impl MsgObjectivesSetObjectiveAutoPinning {
    /// The Atlas card id.
    pub const UID: &'static str = "msg.objectives-set-objective-auto-pinning";
    /// The card wire id.
    pub const WIRE_ID: u32 = 2709;

    /// Decode one `msg.objectives-set-objective-auto-pinning` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            local_facet_id: reader.u64be("local_facet_id")?,
            local_actor_id_word0: reader.u64be("local_actor_id_word0")?,
            auto_pinning_flags: {
                let count = reader.prefix_varint("auto_pinning_flags")?;
                if count > 36 {
                    return Err(WireError::OutOfRange {
                        field: "auto_pinning_flags",
                        max: 36,
                        value: count,
                    });
                }
                let mut value = Vec::new();
                for _ in 0..count {
                    value.push(reader.bool_byte("auto_pinning_flags")?);
                }
                value
            },
        })
    }

    /// Encode one `msg.objectives-set-objective-auto-pinning` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u64be(self.local_facet_id);
        writer.u64be(self.local_actor_id_word0);
        writer.prefix_varint(self.auto_pinning_flags.len() as u64)?;
        for value in &self.auto_pinning_flags {
            writer.u8(u8::from(*value));
        }
        Ok(())
    }
}

/// `msg.server-equip-item` — one Atlas card.
///
/// Message card, wire id `3895`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MsgServerEquipItem {
    /// Body field `local_facet_id` (`u64be`).
    pub local_facet_id: u64,
    /// Body field `local_actor_id_word0` (`u64be`).
    pub local_actor_id_word0: u64,
    /// Body field `field_c` (`u32be`); meaning unnamed.
    pub field_c: u32,
    /// Body field `field_d` (`u32be`); meaning unnamed.
    pub field_d: u32,
    /// Body field `field_e` (`u32be`); meaning unnamed.
    pub field_e: u32,
    /// Body field `field_f` (`guid16`); meaning unnamed.
    pub field_f: Opaque,
    /// Body field `field_g` (`bool_byte`); meaning unnamed.
    pub field_g: bool,
}

impl MsgServerEquipItem {
    /// The Atlas card id.
    pub const UID: &'static str = "msg.server-equip-item";
    /// The card wire id.
    pub const WIRE_ID: u32 = 3895;

    /// Decode one `msg.server-equip-item` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            local_facet_id: reader.u64be("local_facet_id")?,
            local_actor_id_word0: reader.u64be("local_actor_id_word0")?,
            field_c: reader.u32be("field_c")?,
            field_d: reader.u32be("field_d")?,
            field_e: reader.u32be("field_e")?,
            field_f: reader.opaque("field_f", "msg.server-equip-item.field_f", 16)?,
            field_g: reader.bool_byte("field_g")?,
        })
    }

    /// Encode one `msg.server-equip-item` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u64be(self.local_facet_id);
        writer.u64be(self.local_actor_id_word0);
        writer.u32be(self.field_c);
        writer.u32be(self.field_d);
        writer.u32be(self.field_e);
        writer.opaque(&self.field_f);
        writer.u8(u8::from(self.field_g));
        Ok(())
    }
}

/// `msg.time-sync-to-client` — one Atlas card.
///
/// Message card, wire id `4248`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MsgTimeSyncToClient {
    /// Body field `local_facet_id` (`u64be`).
    pub local_facet_id: u64,
    /// Body field `local_actor_id_word0` (`u64be`).
    pub local_actor_id_word0: u64,
}

impl MsgTimeSyncToClient {
    /// The Atlas card id.
    pub const UID: &'static str = "msg.time-sync-to-client";
    /// The card wire id.
    pub const WIRE_ID: u32 = 4248;

    /// Decode one `msg.time-sync-to-client` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            local_facet_id: reader.u64be("local_facet_id")?,
            local_actor_id_word0: reader.u64be("local_actor_id_word0")?,
        })
    }

    /// Encode one `msg.time-sync-to-client` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u64be(self.local_facet_id);
        writer.u64be(self.local_actor_id_word0);
        Ok(())
    }
}

/// `codec.contracts.blob-256` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecContractsBlob256 {
    /// Body field `payload` (`prefixed_bytes`); meaning unnamed.
    pub payload: Opaque,
}

impl CodecContractsBlob256 {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.contracts.blob-256";

    /// Decode one `codec.contracts.blob-256` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            payload: {
                let value =
                    reader.prefixed_opaque("payload", "codec.contracts.blob-256.payload")?;
                if value.len() as u64 > 256 {
                    return Err(WireError::OutOfRange {
                        field: "payload",
                        max: 256,
                        value: value.len() as u64,
                    });
                }
                value
            },
        })
    }

    /// Encode one `codec.contracts.blob-256` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.prefixed_opaque(&self.payload)?;
        Ok(())
    }
}

/// `codec.contracts.blob-64` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecContractsBlob64 {
    /// Body field `payload` (`prefixed_bytes`); meaning unnamed.
    pub payload: Opaque,
}

impl CodecContractsBlob64 {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.contracts.blob-64";

    /// Decode one `codec.contracts.blob-64` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            payload: {
                let value = reader.prefixed_opaque("payload", "codec.contracts.blob-64.payload")?;
                if value.len() as u64 > 64 {
                    return Err(WireError::OutOfRange {
                        field: "payload",
                        max: 64,
                        value: value.len() as u64,
                    });
                }
                value
            },
        })
    }

    /// Encode one `codec.contracts.blob-64` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.prefixed_opaque(&self.payload)?;
        Ok(())
    }
}

/// `codec.contracts.u32-vector-5` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecContractsU32Vector5 {
    /// Body field `values` (`vec<u32be>`); meaning unnamed.
    pub values: Vec<u32>,
}

impl CodecContractsU32Vector5 {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.contracts.u32-vector-5";

    /// Decode one `codec.contracts.u32-vector-5` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            values: {
                let count = reader.prefix_varint("values")?;
                if count > 5 {
                    return Err(WireError::OutOfRange {
                        field: "values",
                        max: 5,
                        value: count,
                    });
                }
                let mut value = Vec::new();
                for _ in 0..count {
                    value.push(reader.u32be("values")?);
                }
                value
            },
        })
    }

    /// Encode one `codec.contracts.u32-vector-5` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.prefix_varint(self.values.len() as u64)?;
        for value in &self.values {
            writer.u32be(*value);
        }
        Ok(())
    }
}

/// `codec.entitlement-balance` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecEntitlementBalance {
    /// Body field `left` (`u32be`); meaning unnamed.
    pub left: u32,
    /// Body field `right` (`u32be`); meaning unnamed.
    pub right: u32,
}

impl CodecEntitlementBalance {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.entitlement-balance";

    /// Decode one `codec.entitlement-balance` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            left: reader.u32be("left")?,
            right: reader.u32be("right")?,
        })
    }

    /// Encode one `codec.entitlement-balance` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u32be(self.left);
        writer.u32be(self.right);
        Ok(())
    }
}

/// `codec.entitlement-balances` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecEntitlementBalances {
    /// Body field `deltaCount` (`prefix_varint`); meaning unnamed.
    pub delta_count: u64,
    /// Body field `delta` (`optional(prefix_varint)`); meaning unnamed.
    pub delta: Option<u64>,
    /// Body field `elements` (`counted(nested(codec.entitlement-balance))`); meaning unnamed.
    pub elements: Vec<CodecEntitlementBalance>,
}

impl CodecEntitlementBalances {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.entitlement-balances";

    /// Decode one `codec.entitlement-balances` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            delta_count: {
                let value = reader.prefix_varint("deltaCount")?;
                if value > 0 {
                    return Err(WireError::OutOfRange {
                        field: "deltaCount",
                        max: 0,
                        value,
                    });
                }
                value
            },
            delta: {
                let flag = reader.u8("delta")?;
                if flag > 1 {
                    return Err(WireError::NotBoolean {
                        field: "delta",
                        value: flag,
                    });
                }
                if flag == 1 {
                    Some(reader.prefix_varint("delta")?)
                } else {
                    None
                }
            },
            elements: {
                let count = reader.prefix_varint("elements")?;
                let mut value = Vec::new();
                for _ in 0..count {
                    value.push(CodecEntitlementBalance::read_from(reader)?);
                }
                value
            },
        })
    }

    /// Encode one `codec.entitlement-balances` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.prefix_varint(self.delta_count)?;
        match &self.delta {
            Some(value) => {
                writer.u8(1);
                writer.prefix_varint(*value)?;
            }
            None => {
                writer.u8(0);
            }
        }
        writer.prefix_varint(self.elements.len() as u64)?;
        for value in &self.elements {
            value.write_to(writer)?;
        }
        Ok(())
    }
}

/// `codec.entitlement-entitlements` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecEntitlementEntitlements {
    /// Body field `deltaCount` (`prefix_varint`); meaning unnamed.
    pub delta_count: u64,
    /// Body field `delta` (`optional(prefix_varint)`); meaning unnamed.
    pub delta: Option<u64>,
    /// Body field `elements` (`counted(nested(codec.entitlement-entry))`); meaning unnamed.
    pub elements: Vec<CodecEntitlementEntry>,
}

impl CodecEntitlementEntitlements {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.entitlement-entitlements";

    /// Decode one `codec.entitlement-entitlements` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            delta_count: {
                let value = reader.prefix_varint("deltaCount")?;
                if value > 0 {
                    return Err(WireError::OutOfRange {
                        field: "deltaCount",
                        max: 0,
                        value,
                    });
                }
                value
            },
            delta: {
                let flag = reader.u8("delta")?;
                if flag > 1 {
                    return Err(WireError::NotBoolean {
                        field: "delta",
                        value: flag,
                    });
                }
                if flag == 1 {
                    Some(reader.prefix_varint("delta")?)
                } else {
                    None
                }
            },
            elements: {
                let count = reader.prefix_varint("elements")?;
                let mut value = Vec::new();
                for _ in 0..count {
                    value.push(CodecEntitlementEntry::read_from(reader)?);
                }
                value
            },
        })
    }

    /// Encode one `codec.entitlement-entitlements` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.prefix_varint(self.delta_count)?;
        match &self.delta {
            Some(value) => {
                writer.u8(1);
                writer.prefix_varint(*value)?;
            }
            None => {
                writer.u8(0);
            }
        }
        writer.prefix_varint(self.elements.len() as u64)?;
        for value in &self.elements {
            value.write_to(writer)?;
        }
        Ok(())
    }
}

/// `codec.entitlement-entry` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecEntitlementEntry {
    /// Body field `entitlement` (`u8`); meaning unnamed.
    pub entitlement: u8,
}

impl CodecEntitlementEntry {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.entitlement-entry";

    /// Decode one `codec.entitlement-entry` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            entitlement: reader.u8("entitlement")?,
        })
    }

    /// Encode one `codec.entitlement-entry` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u8(self.entitlement);
        Ok(())
    }
}

/// `codec.entitlement-received` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecEntitlementReceived {
    /// Body field `received` (`bool_byte`); meaning unnamed.
    pub received: bool,
}

impl CodecEntitlementReceived {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.entitlement-received";

    /// Decode one `codec.entitlement-received` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            received: reader.bool_byte("received")?,
        })
    }

    /// Encode one `codec.entitlement-received` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u8(u8::from(self.received));
        Ok(())
    }
}

/// `codec.entitlement-replicated-state` — one Atlas card.
///
/// Presence-masked sub-codec card (no wire id).
/// Its body is a two-level presence mask: one group mask byte, then for
/// each present group one member mask byte, then the present members'
/// bodies in ascending member order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecEntitlementReplicatedState {
    /// The `group_mask` byte: bit i set means group i is
    /// on the wire.
    pub group_mask: u8,
    /// The present groups, ascending by group index.
    pub groups: Vec<CodecEntitlementReplicatedStateGroup>,
}

/// One present group of [`CodecEntitlementReplicatedState`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecEntitlementReplicatedStateGroup {
    /// The `entry_mask` byte: bit i set means member i is
    /// on the wire.
    pub entry_mask: u8,
    /// The present members, ascending by member index.
    pub entries: Vec<CodecEntitlementReplicatedStateEntry>,
}

/// One present member of a [`CodecEntitlementReplicatedStateGroup`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CodecEntitlementReplicatedStateEntry {
    /// Group 0 member 0, `entitlements`.
    Entitlements(CodecEntitlementEntitlements),
    /// Group 0 member 1, `balances`.
    Balances(CodecEntitlementBalances),
    /// Group 0 member 2, `entitlementsReceived`.
    EntitlementsReceived(CodecEntitlementReceived),
}

impl CodecEntitlementReplicatedState {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.entitlement-replicated-state";

    /// Decode one `codec.entitlement-replicated-state` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, outside a bound
    /// the card states, or its mask selects a group or member the card does
    /// not declare.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, or a mask selects a group
    /// or member the card does not declare.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        let group_mask = reader.u8("group_mask")?;
        let unknown = group_mask & !0b0000_0001;
        if unknown != 0 {
            return Err(WireError::UnknownPresence {
                what: "group",
                index: u64::from(unknown.trailing_zeros()),
            });
        }
        let mut groups = Vec::new();
        if group_mask & 0b0000_0001 != 0 {
            let entry_mask = reader.u8("entry_mask")?;
            let unknown = entry_mask & !0b0000_0111;
            if unknown != 0 {
                return Err(WireError::UnknownPresence {
                    what: "member",
                    index: u64::from(unknown.trailing_zeros()),
                });
            }
            let mut entries = Vec::new();
            if entry_mask & 0b0000_0001 != 0 {
                let value = CodecEntitlementEntitlements::read_from(reader)?;
                entries.push(CodecEntitlementReplicatedStateEntry::Entitlements(value));
            }
            if entry_mask & 0b0000_0010 != 0 {
                let value = CodecEntitlementBalances::read_from(reader)?;
                entries.push(CodecEntitlementReplicatedStateEntry::Balances(value));
            }
            if entry_mask & 0b0000_0100 != 0 {
                let value = CodecEntitlementReceived::read_from(reader)?;
                entries.push(CodecEntitlementReplicatedStateEntry::EntitlementsReceived(
                    value,
                ));
            }
            groups.push(CodecEntitlementReplicatedStateGroup {
                entry_mask,
                entries,
            });
        }
        Ok(Self { group_mask, groups })
    }

    /// Encode one `codec.entitlement-replicated-state` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u8(self.group_mask);
        for group in &self.groups {
            writer.u8(group.entry_mask);
            for entry in &group.entries {
                match entry {
                    CodecEntitlementReplicatedStateEntry::Entitlements(value) => {
                        value.write_to(writer)?;
                    }
                    CodecEntitlementReplicatedStateEntry::Balances(value) => {
                        value.write_to(writer)?;
                    }
                    CodecEntitlementReplicatedStateEntry::EntitlementsReceived(value) => {
                        value.write_to(writer)?;
                    }
                }
            }
        }
        Ok(())
    }
}

/// `codec.objectives-active-objective` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecObjectivesActiveObjective {
    /// Body field `u32_a08` (`u32be`); meaning unnamed.
    pub u32_a08: u32,
    /// Body field `u64_a10` (`u64be`); meaning unnamed.
    pub u64_a10: u64,
    /// Body field `u32_a18` (`u32be`); meaning unnamed.
    pub u32_a18: u32,
    /// Body field `guid_a1c` (`bytes(16)`); meaning unnamed.
    pub guid_a1c: Opaque,
    /// Body field `u64_a38` (`u64be`); meaning unnamed.
    pub u64_a38: u64,
    /// Body field `u16_a40` (`u16be`); meaning unnamed.
    pub u16_a40: u16,
    /// Body field `u8_a42` (`u8`); meaning unnamed.
    pub u8_a42: u8,
    /// Body field `u8_a43` (`u8`); meaning unnamed.
    pub u8_a43: u8,
    /// Body field `u8_a44` (`u8`); meaning unnamed.
    pub u8_a44: u8,
    /// Body field `u8_a45` (`u8`); meaning unnamed.
    pub u8_a45: u8,
    /// Body field `u64_a50` (`u64be`); meaning unnamed.
    pub u64_a50: u64,
    /// Body field `u8_a58` (`u8`); meaning unnamed.
    pub u8_a58: u8,
    /// Body field `index_list` (`vec<u32be>`).
    pub index_list: Vec<u32>,
}

impl CodecObjectivesActiveObjective {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.objectives-active-objective";

    /// Decode one `codec.objectives-active-objective` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            u32_a08: reader.u32be("u32_a08")?,
            u64_a10: reader.u64be("u64_a10")?,
            u32_a18: reader.u32be("u32_a18")?,
            guid_a1c: reader.opaque(
                "guid_a1c",
                "codec.objectives-active-objective.guid_a1c",
                16,
            )?,
            u64_a38: reader.u64be("u64_a38")?,
            u16_a40: reader.u16be("u16_a40")?,
            u8_a42: reader.u8("u8_a42")?,
            u8_a43: reader.u8("u8_a43")?,
            u8_a44: reader.u8("u8_a44")?,
            u8_a45: reader.u8("u8_a45")?,
            u64_a50: reader.u64be("u64_a50")?,
            u8_a58: reader.u8("u8_a58")?,
            index_list: {
                let count = reader.prefix_varint("index_list")?;
                if count > 7 {
                    return Err(WireError::OutOfRange {
                        field: "index_list",
                        max: 7,
                        value: count,
                    });
                }
                let mut value = Vec::new();
                for _ in 0..count {
                    value.push(reader.u32be("index_list")?);
                }
                value
            },
        })
    }

    /// Encode one `codec.objectives-active-objective` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u32be(self.u32_a08);
        writer.u64be(self.u64_a10);
        writer.u32be(self.u32_a18);
        writer.opaque(&self.guid_a1c);
        writer.u64be(self.u64_a38);
        writer.u16be(self.u16_a40);
        writer.u8(self.u8_a42);
        writer.u8(self.u8_a43);
        writer.u8(self.u8_a44);
        writer.u8(self.u8_a45);
        writer.u64be(self.u64_a50);
        writer.u8(self.u8_a58);
        writer.prefix_varint(self.index_list.len() as u64)?;
        for value in &self.index_list {
            writer.u32be(*value);
        }
        Ok(())
    }
}

/// `codec.objectives-active-objectives` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecObjectivesActiveObjectives {
    /// Body field `deltaCount` (`prefix_varint`).
    pub delta_count: u64,
    /// Body field `delta` (`optional(prefix_varint)`).
    pub delta: Option<u64>,
    /// Body field `elements` (`counted(nested(codec.objectives-active-objective))`).
    pub elements: Vec<CodecObjectivesActiveObjective>,
}

impl CodecObjectivesActiveObjectives {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.objectives-active-objectives";

    /// Decode one `codec.objectives-active-objectives` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            delta_count: {
                let value = reader.prefix_varint("deltaCount")?;
                if value > 0 {
                    return Err(WireError::OutOfRange {
                        field: "deltaCount",
                        max: 0,
                        value,
                    });
                }
                value
            },
            delta: {
                let flag = reader.u8("delta")?;
                if flag > 1 {
                    return Err(WireError::NotBoolean {
                        field: "delta",
                        value: flag,
                    });
                }
                if flag == 1 {
                    Some(reader.prefix_varint("delta")?)
                } else {
                    None
                }
            },
            elements: {
                let count = reader.prefix_varint("elements")?;
                let mut value = Vec::new();
                for _ in 0..count {
                    value.push(CodecObjectivesActiveObjective::read_from(reader)?);
                }
                value
            },
        })
    }

    /// Encode one `codec.objectives-active-objectives` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.prefix_varint(self.delta_count)?;
        match &self.delta {
            Some(value) => {
                writer.u8(1);
                writer.prefix_varint(*value)?;
            }
            None => {
                writer.u8(0);
            }
        }
        writer.prefix_varint(self.elements.len() as u64)?;
        for value in &self.elements {
            value.write_to(writer)?;
        }
        Ok(())
    }
}

/// `codec.objectives-replicated-state` — one Atlas card.
///
/// Presence-masked sub-codec card (no wire id).
/// Its body is a two-level presence mask: one group mask byte, then for
/// each present group one member mask byte, then the present members'
/// bodies in ascending member order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecObjectivesReplicatedState {
    /// The `group_mask` byte: bit i set means group i is
    /// on the wire.
    pub group_mask: u8,
    /// The present groups, ascending by group index.
    pub groups: Vec<CodecObjectivesReplicatedStateGroup>,
}

/// One present group of [`CodecObjectivesReplicatedState`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecObjectivesReplicatedStateGroup {
    /// The `entry_mask` byte: bit i set means member i is
    /// on the wire.
    pub entry_mask: u8,
    /// The present members, ascending by member index.
    pub entries: Vec<CodecObjectivesReplicatedStateEntry>,
}

/// One present member of a [`CodecObjectivesReplicatedStateGroup`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CodecObjectivesReplicatedStateEntry {
    /// Group 1 member 3, `activeObjectives`.
    ActiveObjectives(CodecObjectivesActiveObjectives),
    /// Group 1 member 4, `taskStates`.
    TaskStates(CodecObjectivesTaskStates),
}

impl CodecObjectivesReplicatedState {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.objectives-replicated-state";

    /// Decode one `codec.objectives-replicated-state` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, outside a bound
    /// the card states, or its mask selects a group or member the card does
    /// not declare.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, or a mask selects a group
    /// or member the card does not declare.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        let group_mask = reader.u8("group_mask")?;
        let unknown = group_mask & !0b0000_0010;
        if unknown != 0 {
            return Err(WireError::UnknownPresence {
                what: "group",
                index: u64::from(unknown.trailing_zeros()),
            });
        }
        let mut groups = Vec::new();
        if group_mask & 0b0000_0010 != 0 {
            let entry_mask = reader.u8("entry_mask")?;
            let unknown = entry_mask & !0b0001_1000;
            if unknown != 0 {
                return Err(WireError::UnknownPresence {
                    what: "member",
                    index: u64::from(unknown.trailing_zeros()),
                });
            }
            let mut entries = Vec::new();
            if entry_mask & 0b0000_1000 != 0 {
                let value = CodecObjectivesActiveObjectives::read_from(reader)?;
                entries.push(CodecObjectivesReplicatedStateEntry::ActiveObjectives(value));
            }
            if entry_mask & 0b0001_0000 != 0 {
                let value = CodecObjectivesTaskStates::read_from(reader)?;
                entries.push(CodecObjectivesReplicatedStateEntry::TaskStates(value));
            }
            groups.push(CodecObjectivesReplicatedStateGroup {
                entry_mask,
                entries,
            });
        }
        Ok(Self { group_mask, groups })
    }

    /// Encode one `codec.objectives-replicated-state` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u8(self.group_mask);
        for group in &self.groups {
            writer.u8(group.entry_mask);
            for entry in &group.entries {
                match entry {
                    CodecObjectivesReplicatedStateEntry::ActiveObjectives(value) => {
                        value.write_to(writer)?;
                    }
                    CodecObjectivesReplicatedStateEntry::TaskStates(value) => {
                        value.write_to(writer)?;
                    }
                }
            }
        }
        Ok(())
    }
}

/// `codec.objectives-task-state` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecObjectivesTaskState {
    /// Body field `u64_a10` (`u64be`); meaning unnamed.
    pub u64_a10: u64,
    /// Body field `u8_a18` (`u8`); meaning unnamed.
    pub u8_a18: u8,
    /// Body field `u32_a1c` (`u32be`); meaning unnamed.
    pub u32_a1c: u32,
    /// Body field `u32_a20` (`u32be`); meaning unnamed.
    pub u32_a20: u32,
    /// Body field `u8_a24` (`u8`); meaning unnamed.
    pub u8_a24: u8,
}

impl CodecObjectivesTaskState {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.objectives-task-state";

    /// Decode one `codec.objectives-task-state` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            u64_a10: reader.u64be("u64_a10")?,
            u8_a18: reader.u8("u8_a18")?,
            u32_a1c: reader.u32be("u32_a1c")?,
            u32_a20: reader.u32be("u32_a20")?,
            u8_a24: reader.u8("u8_a24")?,
        })
    }

    /// Encode one `codec.objectives-task-state` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u64be(self.u64_a10);
        writer.u8(self.u8_a18);
        writer.u32be(self.u32_a1c);
        writer.u32be(self.u32_a20);
        writer.u8(self.u8_a24);
        Ok(())
    }
}

/// `codec.objectives-task-states` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecObjectivesTaskStates {
    /// Body field `deltaCount` (`prefix_varint`).
    pub delta_count: u64,
    /// Body field `delta` (`optional(prefix_varint)`).
    pub delta: Option<u64>,
    /// Body field `elements` (`counted(nested(codec.objectives-task-state))`).
    pub elements: Vec<CodecObjectivesTaskState>,
}

impl CodecObjectivesTaskStates {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.objectives-task-states";

    /// Decode one `codec.objectives-task-states` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            delta_count: {
                let value = reader.prefix_varint("deltaCount")?;
                if value > 0 {
                    return Err(WireError::OutOfRange {
                        field: "deltaCount",
                        max: 0,
                        value,
                    });
                }
                value
            },
            delta: {
                let flag = reader.u8("delta")?;
                if flag > 1 {
                    return Err(WireError::NotBoolean {
                        field: "delta",
                        value: flag,
                    });
                }
                if flag == 1 {
                    Some(reader.prefix_varint("delta")?)
                } else {
                    None
                }
            },
            elements: {
                let count = reader.prefix_varint("elements")?;
                let mut value = Vec::new();
                for _ in 0..count {
                    value.push(CodecObjectivesTaskState::read_from(reader)?);
                }
                value
            },
        })
    }

    /// Encode one `codec.objectives-task-states` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.prefix_varint(self.delta_count)?;
        match &self.delta {
            Some(value) => {
                writer.u8(1);
                writer.prefix_varint(*value)?;
            }
            None => {
                writer.u8(0);
            }
        }
        writer.prefix_varint(self.elements.len() as u64)?;
        for value in &self.elements {
            value.write_to(writer)?;
        }
        Ok(())
    }
}

/// `codec.transmog-appearance` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecTransmogAppearance {
    /// Body field `id` (`prefix_varint`); meaning unnamed.
    pub id: u64,
    /// Body field `delta` (`optional(prefix_varint)`); meaning unnamed.
    pub delta: Option<u64>,
    /// Body field `value` (`u64be`); meaning unnamed.
    pub value: u64,
}

impl CodecTransmogAppearance {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.transmog-appearance";

    /// Decode one `codec.transmog-appearance` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            id: reader.prefix_varint("id")?,
            delta: {
                let flag = reader.u8("delta")?;
                if flag > 1 {
                    return Err(WireError::NotBoolean {
                        field: "delta",
                        value: flag,
                    });
                }
                if flag == 1 {
                    Some(reader.prefix_varint("delta")?)
                } else {
                    None
                }
            },
            value: reader.u64be("value")?,
        })
    }

    /// Encode one `codec.transmog-appearance` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.prefix_varint(self.id)?;
        match &self.delta {
            Some(value) => {
                writer.u8(1);
                writer.prefix_varint(*value)?;
            }
            None => {
                writer.u8(0);
            }
        }
        writer.u64be(self.value);
        Ok(())
    }
}

/// `codec.transmog-appearance-list` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecTransmogAppearanceList {
    /// Body field `deltaCount` (`prefix_varint`); meaning unnamed.
    pub delta_count: u64,
    /// Body field `delta` (`optional(prefix_varint)`); meaning unnamed.
    pub delta: Option<u64>,
    /// Body field `elements` (`counted(u64be)`); meaning unnamed.
    pub elements: Vec<u64>,
}

impl CodecTransmogAppearanceList {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.transmog-appearance-list";

    /// Decode one `codec.transmog-appearance-list` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            delta_count: {
                let value = reader.prefix_varint("deltaCount")?;
                if value > 0 {
                    return Err(WireError::OutOfRange {
                        field: "deltaCount",
                        max: 0,
                        value,
                    });
                }
                value
            },
            delta: {
                let flag = reader.u8("delta")?;
                if flag > 1 {
                    return Err(WireError::NotBoolean {
                        field: "delta",
                        value: flag,
                    });
                }
                if flag == 1 {
                    Some(reader.prefix_varint("delta")?)
                } else {
                    None
                }
            },
            elements: {
                let count = reader.prefix_varint("elements")?;
                let mut value = Vec::new();
                for _ in 0..count {
                    value.push(reader.u64be("elements")?);
                }
                value
            },
        })
    }

    /// Encode one `codec.transmog-appearance-list` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.prefix_varint(self.delta_count)?;
        match &self.delta {
            Some(value) => {
                writer.u8(1);
                writer.prefix_varint(*value)?;
            }
            None => {
                writer.u8(0);
            }
        }
        writer.prefix_varint(self.elements.len() as u64)?;
        for value in &self.elements {
            writer.u64be(*value);
        }
        Ok(())
    }
}

/// `codec.transmog-appearance-map` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecTransmogAppearanceMap {
    /// Body field `elements` (`masked_counted(nested(codec.transmog-appearance))`); meaning unnamed.
    pub elements: Vec<CodecTransmogAppearance>,
}

impl CodecTransmogAppearanceMap {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.transmog-appearance-map";

    /// Decode one `codec.transmog-appearance-map` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            elements: {
                let count = reader.prefix_varint("elements")?;
                let mut value = Vec::new();
                let mut index = 0_u64;
                while index < count {
                    let chunk = (count - index).min(8);
                    let mask = reader.u8("elements")?;
                    let wanted = u8::MAX >> (8 - chunk);
                    if mask != wanted {
                        return Err(WireError::UnknownPresence {
                            what: "elements",
                            index: index + u64::from((mask ^ wanted).trailing_zeros()),
                        });
                    }
                    for _ in 0..chunk {
                        value.push(CodecTransmogAppearance::read_from(reader)?);
                    }
                    index += chunk;
                }
                value
            },
        })
    }

    /// Encode one `codec.transmog-appearance-map` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.prefix_varint(self.elements.len() as u64)?;
        let mut index = 0;
        while index < self.elements.len() {
            let chunk = (self.elements.len() - index).min(8);
            writer.u8(u8::MAX >> (8 - chunk));
            for item in &self.elements[index..index + chunk] {
                item.write_to(writer)?;
            }
            index += chunk;
        }
        Ok(())
    }
}

/// `codec.transmog-inventory-ready` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecTransmogInventoryReady {
    /// Body field `ready` (`bool_byte`); meaning unnamed.
    pub ready: bool,
}

impl CodecTransmogInventoryReady {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.transmog-inventory-ready";

    /// Decode one `codec.transmog-inventory-ready` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, or outside
    /// a bound the card states.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a field is truncated or outside a bound the
    /// card states.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Ok(Self {
            ready: reader.bool_byte("ready")?,
        })
    }

    /// Encode one `codec.transmog-inventory-ready` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u8(u8::from(self.ready));
        Ok(())
    }
}

/// `codec.transmog-replicated-state` — one Atlas card.
///
/// Presence-masked sub-codec card (no wire id).
/// Its body is a two-level presence mask: one group mask byte, then for
/// each present group one member mask byte, then the present members'
/// bodies in ascending member order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecTransmogReplicatedState {
    /// The `group_mask` byte: bit i set means group i is
    /// on the wire.
    pub group_mask: u8,
    /// The present groups, ascending by group index.
    pub groups: Vec<CodecTransmogReplicatedStateGroup>,
}

/// One present group of [`CodecTransmogReplicatedState`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecTransmogReplicatedStateGroup {
    /// The `entry_mask` byte: bit i set means member i is
    /// on the wire.
    pub entry_mask: u8,
    /// The present members, ascending by member index.
    pub entries: Vec<CodecTransmogReplicatedStateEntry>,
}

/// One present member of a [`CodecTransmogReplicatedStateGroup`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CodecTransmogReplicatedStateEntry {
    /// Group 0 member 0, `capturedArmorAppearances`.
    CapturedArmorAppearances(CodecTransmogAppearanceMap),
    /// Group 0 member 1, `capturedWeaponAppearances`.
    CapturedWeaponAppearances(CodecTransmogAppearanceList),
    /// Group 0 member 2, `ownedArmorAppearances`.
    OwnedArmorAppearances(CodecTransmogAppearanceMap),
    /// Group 0 member 3, `ownedWeaponAppearances`.
    OwnedWeaponAppearances(CodecTransmogAppearanceMap),
    /// Group 0 member 4, `inventoryServicesReady`.
    InventoryServicesReady(CodecTransmogInventoryReady),
}

impl CodecTransmogReplicatedState {
    /// The Atlas card id.
    pub const UID: &'static str = "codec.transmog-replicated-state";

    /// Decode one `codec.transmog-replicated-state` body.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, longer, outside a bound
    /// the card states, or its mask selects a group or member the card does
    /// not declare.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let mut reader = Reader::new(body);
        let value = Self::read_from(&mut reader)?;
        reader.finish()?;
        Ok(value)
    }

    /// Read one body from the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body is shorter, or a mask selects a group
    /// or member the card does not declare.
    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        let group_mask = reader.u8("group_mask")?;
        let unknown = group_mask & !0b0000_0001;
        if unknown != 0 {
            return Err(WireError::UnknownPresence {
                what: "group",
                index: u64::from(unknown.trailing_zeros()),
            });
        }
        let mut groups = Vec::new();
        if group_mask & 0b0000_0001 != 0 {
            let entry_mask = reader.u8("entry_mask")?;
            let unknown = entry_mask & !0b0001_1111;
            if unknown != 0 {
                return Err(WireError::UnknownPresence {
                    what: "member",
                    index: u64::from(unknown.trailing_zeros()),
                });
            }
            let mut entries = Vec::new();
            if entry_mask & 0b0000_0001 != 0 {
                let value = CodecTransmogAppearanceMap::read_from(reader)?;
                entries.push(CodecTransmogReplicatedStateEntry::CapturedArmorAppearances(
                    value,
                ));
            }
            if entry_mask & 0b0000_0010 != 0 {
                let value = CodecTransmogAppearanceList::read_from(reader)?;
                entries.push(CodecTransmogReplicatedStateEntry::CapturedWeaponAppearances(value));
            }
            if entry_mask & 0b0000_0100 != 0 {
                let value = CodecTransmogAppearanceMap::read_from(reader)?;
                entries.push(CodecTransmogReplicatedStateEntry::OwnedArmorAppearances(
                    value,
                ));
            }
            if entry_mask & 0b0000_1000 != 0 {
                let value = CodecTransmogAppearanceMap::read_from(reader)?;
                entries.push(CodecTransmogReplicatedStateEntry::OwnedWeaponAppearances(
                    value,
                ));
            }
            if entry_mask & 0b0001_0000 != 0 {
                let value = CodecTransmogInventoryReady::read_from(reader)?;
                entries.push(CodecTransmogReplicatedStateEntry::InventoryServicesReady(
                    value,
                ));
            }
            groups.push(CodecTransmogReplicatedStateGroup {
                entry_mask,
                entries,
            });
        }
        Ok(Self { group_mask, groups })
    }

    /// Encode one `codec.transmog-replicated-state` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        self.write_to(&mut writer)
    }

    /// Write one body into the middle of a larger record.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        writer.u8(self.group_mask);
        for group in &self.groups {
            writer.u8(group.entry_mask);
            for entry in &group.entries {
                match entry {
                    CodecTransmogReplicatedStateEntry::CapturedArmorAppearances(value)
                    | CodecTransmogReplicatedStateEntry::OwnedArmorAppearances(value)
                    | CodecTransmogReplicatedStateEntry::OwnedWeaponAppearances(value) => {
                        value.write_to(writer)?;
                    }
                    CodecTransmogReplicatedStateEntry::CapturedWeaponAppearances(value) => {
                        value.write_to(writer)?;
                    }
                    CodecTransmogReplicatedStateEntry::InventoryServicesReady(value) => {
                        value.write_to(writer)?;
                    }
                }
            }
        }
        Ok(())
    }
}
