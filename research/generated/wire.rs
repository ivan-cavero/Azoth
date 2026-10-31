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
    MessageSpec {
        wire_id: 1502,
        uid: "msg.request-spend-attribute-points",
        name: "AttributeComponentServerFacet_RequestSpendAttributePoints",
        direction: "C2S",
        fields: &[
            FieldSpec { name: "field_a", codec: "u64be" },
            FieldSpec { name: "field_b", codec: "u64be" },
            FieldSpec { name: "attribute_indices", codec: "vec<u32be>" },
            FieldSpec { name: "points", codec: "vec<u32be>" },
        ],
    },
    MessageSpec {
        wire_id: 1628,
        uid: "flow.world-entry.rung.self-identification",
        name: "Ladder: SelfIdentification",
        direction: "S2C",
        fields: &[
            FieldSpec { name: "prefix_lead", codec: "u8" },
            FieldSpec { name: "identity_guid_prefix", codec: "guid16" },
            FieldSpec { name: "vtable_tag", codec: "u32be" },
            FieldSpec { name: "prefix_data", codec: "bytes(107)" },
            FieldSpec { name: "grid_side", codec: "u8" },
            FieldSpec { name: "grid_header", codec: "bytes(2)" },
            FieldSpec { name: "grid_cells", codec: "bytes(12544)" },
            FieldSpec { name: "tail_zeros", codec: "bytes(10)" },
            FieldSpec { name: "tail_lead", codec: "u8" },
            FieldSpec { name: "identity_guid_tail", codec: "guid16" },
        ],
    },
    MessageSpec {
        wire_id: 3895,
        uid: "msg.server-equip-item",
        name: "PaperdollComponentServerFacet_ServerEquipItem",
        direction: "C2S",
        fields: &[
            FieldSpec { name: "field_a", codec: "u64be" },
            FieldSpec { name: "field_b", codec: "u64be" },
            FieldSpec { name: "field_c", codec: "u32be" },
            FieldSpec { name: "field_d", codec: "u32be" },
            FieldSpec { name: "field_e", codec: "u32be" },
            FieldSpec { name: "field_f", codec: "guid16" },
            FieldSpec { name: "field_g", codec: "bool_byte" },
        ],
    },
];

pub struct CodecSpec {
    pub uid: &'static str,
    pub name: &'static str,
    pub fields: &'static [FieldSpec],
}

pub static CODECS: &[CodecSpec] = &[
    CodecSpec {
        uid: "codec.contracts.blob-256",
        name: "Contracts nested sub-codec B",
        fields: &[
            FieldSpec { name: "payload", codec: "prefixed_bytes" },
        ],
    },
    CodecSpec {
        uid: "codec.contracts.blob-64",
        name: "Contracts nested sub-codec A",
        fields: &[
            FieldSpec { name: "payload", codec: "prefixed_bytes" },
        ],
    },
    CodecSpec {
        uid: "codec.contracts.u32-vector-5",
        name: "Contracts nested sub-codec C",
        fields: &[
            FieldSpec { name: "values", codec: "vec<u32be>" },
        ],
    },
];
