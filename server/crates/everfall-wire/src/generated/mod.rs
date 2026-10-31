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
    /// Body field `unresolved_u32` (`u32be`).
    pub unresolved_u32: u32,
    /// Body field `unresolved_u64` (`u64be`).
    pub unresolved_u64: u64,
    /// Body field `unresolved_block` (`prefixed_bytes`).
    pub unresolved_block: Opaque,
    /// Body field `server_version` (`prefixed_string`).
    pub server_version: String,
    /// Body field `trailing_bool_0` (`bool_byte`).
    pub trailing_bool_0: bool,
    /// Body field `trailing_bool_1` (`bool_byte`).
    pub trailing_bool_1: bool,
    /// Body field `trailing_bool_2` (`bool_byte`).
    pub trailing_bool_2: bool,
    /// Body field `trailing_bool_3` (`bool_byte`).
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
        let unresolved_u32 = reader.u32be("unresolved_u32")?;
        let unresolved_u64 = reader.u64be("unresolved_u64")?;
        let unresolved_block = reader.prefixed_opaque(
            "unresolved_block",
            "flow.world-entry.rung.registration.unresolved_block",
        )?;
        let server_version = reader.prefixed_string("server_version")?;
        let trailing_bool_0 = reader.bool_byte("trailing_bool_0")?;
        let trailing_bool_1 = reader.bool_byte("trailing_bool_1")?;
        let trailing_bool_2 = reader.bool_byte("trailing_bool_2")?;
        let trailing_bool_3 = reader.bool_byte("trailing_bool_3")?;
        reader.finish()?;
        Ok(Self {
            unresolved_u32,
            unresolved_u64,
            unresolved_block,
            server_version,
            trailing_bool_0,
            trailing_bool_1,
            trailing_bool_2,
            trailing_bool_3,
        })
    }

    /// Encode one `flow.world-entry.rung.registration` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
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
    /// Body field `blob` (`prefixed_bytes`).
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
        let blob = reader.prefixed_opaque("blob", "msg.update.blob")?;
        if blob.len() as u64 > 512 {
            return Err(WireError::OutOfRange {
                field: "blob",
                max: 512,
                value: blob.len() as u64,
            });
        }
        reader.finish()?;
        Ok(Self { blob })
    }

    /// Encode one `msg.update` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        writer.prefixed_opaque(&self.blob)?;
        Ok(())
    }
}

/// `msg.objectives-update-tracked-objectives` — one Atlas card.
///
/// Message card, wire id `1458`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MsgObjectivesUpdateTrackedObjectives {
    /// Body field `field_a` (`u64be`).
    pub field_a: u64,
    /// Body field `field_b` (`u64be`).
    pub field_b: u64,
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
        let field_a = reader.u64be("field_a")?;
        let field_b = reader.u64be("field_b")?;
        let count = reader.prefix_varint("tracked_objective_ids")?;
        if count > 8 {
            return Err(WireError::OutOfRange {
                field: "tracked_objective_ids",
                max: 8,
                value: count,
            });
        }
        let mut tracked_objective_ids = Vec::new();
        for _ in 0..count {
            tracked_objective_ids.push(reader.u64be("tracked_objective_ids")?);
        }
        reader.finish()?;
        Ok(Self {
            field_a,
            field_b,
            tracked_objective_ids,
        })
    }

    /// Encode one `msg.objectives-update-tracked-objectives` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        writer.u64be(self.field_a);
        writer.u64be(self.field_b);
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
    /// Body field `field_a` (`u64be`).
    pub field_a: u64,
    /// Body field `field_b` (`u64be`).
    pub field_b: u64,
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
        let field_a = reader.u64be("field_a")?;
        let field_b = reader.u64be("field_b")?;
        let count = reader.prefix_varint("attribute_indices")?;
        if count > 4 {
            return Err(WireError::OutOfRange {
                field: "attribute_indices",
                max: 4,
                value: count,
            });
        }
        let mut attribute_indices = Vec::new();
        for _ in 0..count {
            attribute_indices.push(reader.u32be("attribute_indices")?);
        }
        let count = reader.prefix_varint("points")?;
        if count > 700 {
            return Err(WireError::OutOfRange {
                field: "points",
                max: 700,
                value: count,
            });
        }
        let mut points = Vec::new();
        for _ in 0..count {
            points.push(reader.u32be("points")?);
        }
        reader.finish()?;
        Ok(Self {
            field_a,
            field_b,
            attribute_indices,
            points,
        })
    }

    /// Encode one `msg.request-spend-attribute-points` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        writer.u64be(self.field_a);
        writer.u64be(self.field_b);
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
    /// Body field `prefix_lead` (`u8`).
    pub prefix_lead: u8,
    /// Body field `identity_guid_prefix` (`guid16`).
    pub identity_guid_prefix: Opaque,
    /// Body field `vtable_tag` (`u32be`).
    pub vtable_tag: u32,
    /// Body field `prefix_data` (`bytes(107)`).
    pub prefix_data: Opaque,
    /// Body field `grid_side` (`u8`).
    pub grid_side: u8,
    /// Body field `grid_header` (`bytes(2)`).
    pub grid_header: Opaque,
    /// Body field `grid_cells` (`bytes(12544)`).
    pub grid_cells: Opaque,
    /// Body field `tail_zeros` (`bytes(10)`).
    pub tail_zeros: Opaque,
    /// Body field `tail_lead` (`u8`).
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
        let prefix_lead = reader.u8("prefix_lead")?;
        let identity_guid_prefix = reader.opaque(
            "identity_guid_prefix",
            "flow.world-entry.rung.self-identification.identity_guid_prefix",
            16,
        )?;
        let vtable_tag = reader.u32be("vtable_tag")?;
        let prefix_data = reader.opaque(
            "prefix_data",
            "flow.world-entry.rung.self-identification.prefix_data",
            107,
        )?;
        let grid_side = reader.u8("grid_side")?;
        let grid_header = reader.opaque(
            "grid_header",
            "flow.world-entry.rung.self-identification.grid_header",
            2,
        )?;
        let grid_cells = reader.opaque(
            "grid_cells",
            "flow.world-entry.rung.self-identification.grid_cells",
            12544,
        )?;
        let tail_zeros = reader.opaque(
            "tail_zeros",
            "flow.world-entry.rung.self-identification.tail_zeros",
            10,
        )?;
        let tail_lead = reader.u8("tail_lead")?;
        let identity_guid_tail = reader.opaque(
            "identity_guid_tail",
            "flow.world-entry.rung.self-identification.identity_guid_tail",
            16,
        )?;
        reader.finish()?;
        Ok(Self {
            prefix_lead,
            identity_guid_prefix,
            vtable_tag,
            prefix_data,
            grid_side,
            grid_header,
            grid_cells,
            tail_zeros,
            tail_lead,
            identity_guid_tail,
        })
    }

    /// Encode one `flow.world-entry.rung.self-identification` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
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
    /// Body field `unresolved_u64` (`u64be`).
    pub unresolved_u64: u64,
    /// Body field `unresolved_u32` (`u32be`).
    pub unresolved_u32: u32,
    /// Body field `session_nonce` (`u64be`).
    pub session_nonce: u64,
    /// Body field `unresolved_group` (`bytes(10)`).
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
        let level_name = reader.prefixed_string("level_name")?;
        let level_path = reader.prefixed_string("level_path")?;
        let mut level_bounds = [0.0; 4];
        for slot in &mut level_bounds {
            *slot = reader.f32be("level_bounds")?;
        }
        let unresolved_u64 = reader.u64be("unresolved_u64")?;
        let unresolved_u32 = reader.u32be("unresolved_u32")?;
        let session_nonce = reader.u64be("session_nonce")?;
        let unresolved_group = reader.opaque(
            "unresolved_group",
            "flow.world-entry.rung.level-info.unresolved_group",
            10,
        )?;
        let level_context_key = reader.u64be("level_context_key")?;
        reader.finish()?;
        Ok(Self {
            level_name,
            level_path,
            level_bounds,
            unresolved_u64,
            unresolved_u32,
            session_nonce,
            unresolved_group,
            level_context_key,
        })
    }

    /// Encode one `flow.world-entry.rung.level-info` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
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

/// `msg.objectives-set-objective-auto-pinning` — one Atlas card.
///
/// Message card, wire id `2709`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MsgObjectivesSetObjectiveAutoPinning {
    /// Body field `field_a` (`u64be`).
    pub field_a: u64,
    /// Body field `field_b` (`u64be`).
    pub field_b: u64,
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
        let field_a = reader.u64be("field_a")?;
        let field_b = reader.u64be("field_b")?;
        let count = reader.prefix_varint("auto_pinning_flags")?;
        if count > 36 {
            return Err(WireError::OutOfRange {
                field: "auto_pinning_flags",
                max: 36,
                value: count,
            });
        }
        let mut auto_pinning_flags = Vec::new();
        for _ in 0..count {
            auto_pinning_flags.push(reader.bool_byte("auto_pinning_flags")?);
        }
        reader.finish()?;
        Ok(Self {
            field_a,
            field_b,
            auto_pinning_flags,
        })
    }

    /// Encode one `msg.objectives-set-objective-auto-pinning` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        writer.u64be(self.field_a);
        writer.u64be(self.field_b);
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
    /// Body field `field_a` (`u64be`).
    pub field_a: u64,
    /// Body field `field_b` (`u64be`).
    pub field_b: u64,
    /// Body field `field_c` (`u32be`).
    pub field_c: u32,
    /// Body field `field_d` (`u32be`).
    pub field_d: u32,
    /// Body field `field_e` (`u32be`).
    pub field_e: u32,
    /// Body field `field_f` (`guid16`).
    pub field_f: Opaque,
    /// Body field `field_g` (`bool_byte`).
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
        let field_a = reader.u64be("field_a")?;
        let field_b = reader.u64be("field_b")?;
        let field_c = reader.u32be("field_c")?;
        let field_d = reader.u32be("field_d")?;
        let field_e = reader.u32be("field_e")?;
        let field_f = reader.opaque("field_f", "msg.server-equip-item.field_f", 16)?;
        let field_g = reader.bool_byte("field_g")?;
        reader.finish()?;
        Ok(Self {
            field_a,
            field_b,
            field_c,
            field_d,
            field_e,
            field_f,
            field_g,
        })
    }

    /// Encode one `msg.server-equip-item` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        writer.u64be(self.field_a);
        writer.u64be(self.field_b);
        writer.u32be(self.field_c);
        writer.u32be(self.field_d);
        writer.u32be(self.field_e);
        writer.opaque(&self.field_f);
        writer.u8(u8::from(self.field_g));
        Ok(())
    }
}

/// `codec.contracts.blob-256` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecContractsBlob256 {
    /// Body field `payload` (`prefixed_bytes`).
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
        let payload = reader.prefixed_opaque("payload", "codec.contracts.blob-256.payload")?;
        if payload.len() as u64 > 256 {
            return Err(WireError::OutOfRange {
                field: "payload",
                max: 256,
                value: payload.len() as u64,
            });
        }
        reader.finish()?;
        Ok(Self { payload })
    }

    /// Encode one `codec.contracts.blob-256` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        writer.prefixed_opaque(&self.payload)?;
        Ok(())
    }
}

/// `codec.contracts.blob-64` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecContractsBlob64 {
    /// Body field `payload` (`prefixed_bytes`).
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
        let payload = reader.prefixed_opaque("payload", "codec.contracts.blob-64.payload")?;
        if payload.len() as u64 > 64 {
            return Err(WireError::OutOfRange {
                field: "payload",
                max: 64,
                value: payload.len() as u64,
            });
        }
        reader.finish()?;
        Ok(Self { payload })
    }

    /// Encode one `codec.contracts.blob-64` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        writer.prefixed_opaque(&self.payload)?;
        Ok(())
    }
}

/// `codec.contracts.u32-vector-5` — one Atlas card.
///
/// Nested sub-codec card (no wire id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecContractsU32Vector5 {
    /// Body field `values` (`vec<u32be>`).
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
        let count = reader.prefix_varint("values")?;
        if count > 5 {
            return Err(WireError::OutOfRange {
                field: "values",
                max: 5,
                value: count,
            });
        }
        let mut values = Vec::new();
        for _ in 0..count {
            values.push(reader.u32be("values")?);
        }
        reader.finish()?;
        Ok(Self { values })
    }

    /// Encode one `codec.contracts.u32-vector-5` body, appending to `out`.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {
        let mut writer = Writer::new(out);
        writer.prefix_varint(self.values.len() as u64)?;
        for value in &self.values {
            writer.u32be(*value);
        }
        Ok(())
    }
}
