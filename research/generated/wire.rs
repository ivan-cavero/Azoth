// NON-COMPILING PREVIEW -- generated from the Atlas concept cards by
// `reverse/tools/atlas/ontology-gen.py`. This file is NOT a crate and is NOT
// meant to build; it previews the same table-driven layout as wire.py so the
// Rust port can be reviewed field by field. Do not `mod` it into anything.
//
// Envelope note: every field is a message BODY field. The `00 01` + prefix-varint
// type record envelope is framing owned by javelin/frame.py, never a field here.
//
// The measured prefix-varint primitive is `azoth_world.javelin.varint`; this
// preview mirrors wire.py and does not reimplement it.


pub const VOCABULARY: &[&str] = &[
    "u8",
    "u16be",
    "u16le",
    "u32be",
    "u32le",
    "u64be",
    "u64le",
    "i8",
    "i16be",
    "i32be",
    "i64be",
    "f32be",
    "f32le",
    "f64be",
    "prefix_varint",
    "varint",
    "bool_byte",
    "prefixed_bytes",
    "prefixed_string",
    "guid16",
    "enum8",
    "enum16be",
    "enum32be",
    "bitset8",
    "bitset16",
    "bitset32be",
];

pub struct FieldSpec {
    pub name: &'static str,
    pub codec: &'static str,
}

pub struct MessageSpec {
    pub wire_id: u32,
    pub uid: &'static str,
    pub name: &'static str,
    pub direction: &'static str,
    pub fields: &'static [FieldSpec],
}

pub static MESSAGES: &[MessageSpec] = &[
    MessageSpec {
        wire_id: 106,
        uid: "msg.update",
        name: "UpdateMsg",
        direction: "S2C",
        fields: &[
            FieldSpec { name: "blob", codec: "prefixed_bytes" },
        ],
    },
];
