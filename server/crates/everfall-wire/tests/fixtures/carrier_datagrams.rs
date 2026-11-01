// Real Carrier datagrams captured by the reference world server.
//
// Capture: `.azoth/logs/world.log`, the session of 2026-10-19T20:52:39Z
// (`.azoth/` is gitignored and the file is huge, so the datagrams are kept here
// as literals). Client build: 1.400.6031.6004151, SHA-256
// `8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e` (the
// build flavor string is itself inside a captured registration reply).
//
// Every expected field below is the Python reference's own decode of the raw
// datagram (`javelin/frame.py`), not a hand computation, so the Rust codec is
// checked against the implementation it was ported from.

/// One record exactly as the Python reference decoded it.
pub(crate) struct ExpectedRecord {
    /// Channel the record rides on.
    pub(crate) channel: u8,
    /// Raw flag byte.
    pub(crate) flags: u8,
    /// Payload byte count.
    pub(crate) size: usize,
    /// Per-channel message sequence.
    pub(crate) sequence: u16,
    /// Per-channel reliable sequence.
    pub(crate) reliable_sequence: u16,
    /// Whether the record is reliable.
    pub(crate) reliable: bool,
    /// Whether the record belongs to the handshake.
    pub(crate) connecting: bool,
    /// Declared chunk count.
    pub(crate) num_chunks: u16,
    /// System message id, when the record is on the system channel.
    pub(crate) system: Option<u8>,
}

/// The envelope header exactly as the Python reference decoded it.
pub(crate) struct ExpectedEnvelope {
    /// Raw type byte.
    pub(crate) type_byte: u8,
    /// Protocol byte.
    pub(crate) proto: u8,
    /// Envelope sequence.
    pub(crate) sequence: u16,
    /// Whether the body is LZ4-compressed.
    pub(crate) compressed: bool,
    /// Whole-datagram byte count.
    pub(crate) size: usize,
}

/// One captured datagram with every expected field.
pub(crate) struct Sample {
    /// Human-readable label.
    pub(crate) name: &'static str,
    /// One of `app-data`, `reply`, `record-bearing`.
    pub(crate) kind: &'static str,
    /// The datagram bytes, hex.
    pub(crate) raw: &'static str,
    /// Expected envelope fields.
    pub(crate) envelope: ExpectedEnvelope,
    /// Expected records, in wire order.
    pub(crate) records: &'static [ExpectedRecord],
}

/// A compressed datagram, carried only for envelope-header parity: its body is an
/// LZ4 block the envelope layer must leave alone.
pub(crate) struct CompressedSample {
    /// Human-readable label.
    pub(crate) name: &'static str,
    /// The datagram bytes, hex.
    pub(crate) raw: &'static str,
    /// Expected envelope fields.
    pub(crate) envelope: ExpectedEnvelope,
}

/// The uncompressed datagrams, decoded record by record.
pub(crate) const SAMPLES: &[Sample] = &[
    Sample {
        name: "app-data handshake seq 2",
        kind: "app-data",
        raw: "80010002a00005030000ffff0000000501880006ffff000000050101880002ffff2006",
        envelope: ExpectedEnvelope { type_byte: 0x80, proto: 1, sequence: 2, compressed: false, size: 35 },
        records: &[
        ExpectedRecord { channel: 3, flags: 0xA0, size: 5, sequence: 0, reliable_sequence: 65535, reliable: false, connecting: true, num_chunks: 1, system: Some(1) },
        ExpectedRecord { channel: 3, flags: 0x88, size: 6, sequence: 1, reliable_sequence: 65535, reliable: false, connecting: true, num_chunks: 1, system: Some(1) },
        ExpectedRecord { channel: 3, flags: 0x88, size: 2, sequence: 2, reliable_sequence: 65535, reliable: false, connecting: true, num_chunks: 1, system: Some(6) },
        ],
    },
    Sample {
        name: "app-data handshake seq 3",
        kind: "app-data",
        raw: "80010003a00007030003ffff00000005010101880002ffff2006",
        envelope: ExpectedEnvelope { type_byte: 0x80, proto: 1, sequence: 3, compressed: false, size: 26 },
        records: &[
        ExpectedRecord { channel: 3, flags: 0xA0, size: 7, sequence: 3, reliable_sequence: 65535, reliable: false, connecting: true, num_chunks: 1, system: Some(1) },
        ExpectedRecord { channel: 3, flags: 0x88, size: 2, sequence: 4, reliable_sequence: 65535, reliable: false, connecting: true, num_chunks: 1, system: Some(6) },
        ],
    },
    Sample {
        name: "app-data handshake seq 4",
        kind: "app-data",
        raw: "80010004200004030005ffff00000206",
        envelope: ExpectedEnvelope { type_byte: 0x80, proto: 1, sequence: 4, compressed: false, size: 16 },
        records: &[
        ExpectedRecord { channel: 3, flags: 0x20, size: 4, sequence: 5, reliable_sequence: 65535, reliable: false, connecting: false, num_chunks: 1, system: Some(6) },
        ],
    },
    Sample {
        name: "app-data data record seq 35",
        kind: "record-bearing",
        raw: "8001002320000603001effff4000e800e50621002c000013001398e3e4a1000000241a954abc4b3185bfbe37c3d8592618e00001ab19d8c9c8af5e7a353cbf85314bbc4a951a",
        envelope: ExpectedEnvelope { type_byte: 0x80, proto: 1, sequence: 35, compressed: false, size: 70 },
        records: &[
        ExpectedRecord { channel: 3, flags: 0x20, size: 6, sequence: 30, reliable_sequence: 65535, reliable: false, connecting: false, num_chunks: 1, system: Some(6) },
        ExpectedRecord { channel: 0, flags: 0x21, size: 44, sequence: 19, reliable_sequence: 19, reliable: true, connecting: false, num_chunks: 1, system: None },
        ],
    },
    Sample {
        name: "reply acceptance flight seq 2",
        kind: "reply",
        raw: "80010002200005030000ffff55f014b00421000503000100000000000502180006400002000206",
        envelope: ExpectedEnvelope { type_byte: 0x80, proto: 1, sequence: 2, compressed: false, size: 39 },
        records: &[
        ExpectedRecord { channel: 3, flags: 0x20, size: 5, sequence: 0, reliable_sequence: 65535, reliable: false, connecting: false, num_chunks: 1, system: Some(4) },
        ExpectedRecord { channel: 3, flags: 0x21, size: 5, sequence: 1, reliable_sequence: 0, reliable: true, connecting: false, num_chunks: 1, system: Some(2) },
        ExpectedRecord { channel: 3, flags: 0x18, size: 6, sequence: 2, reliable_sequence: 0, reliable: false, connecting: false, num_chunks: 1, system: Some(6) },
        ],
    },
    Sample {
        name: "reply ct-acks seq 6",
        kind: "reply",
        raw: "80010006200006030000ffff400006000206",
        envelope: ExpectedEnvelope { type_byte: 0x80, proto: 1, sequence: 6, compressed: false, size: 18 },
        records: &[
        ExpectedRecord { channel: 3, flags: 0x20, size: 6, sequence: 0, reliable_sequence: 65535, reliable: false, connecting: false, num_chunks: 1, system: Some(6) },
        ],
    },
    Sample {
        name: "reply ct-acks seq 18",
        kind: "reply",
        raw: "80010012200006030000ffff400012000206",
        envelope: ExpectedEnvelope { type_byte: 0x80, proto: 1, sequence: 18, compressed: false, size: 18 },
        records: &[
        ExpectedRecord { channel: 3, flags: 0x20, size: 6, sequence: 0, reliable_sequence: 65535, reliable: false, connecting: false, num_chunks: 1, system: Some(6) },
        ],
    },
];

/// Compressed datagrams used for the envelope-header check.
pub(crate) const COMPRESSED_SAMPLES: &[CompressedSample] = &[
    CompressedSample {
        name: "app-data lz4 seq 7",
        raw: "810100079f0100ef0002000261350200cb15000100500000000000",
        envelope: ExpectedEnvelope { type_byte: 0x81, proto: 1, sequence: 7, compressed: true, size: 27 },
    },
];
