//! Anti-emulator guard: the library must stay a codec, not a replay.
//!
//! The owner's requirement: the Rust side is the best-practice server, never an
//! emulator or a replay. Two rules are mechanised here against the library
//! source (`src/`, the crate's own modules; integration tests are separate
//! crates that consume the committed corpus, they are not the codec):
//!
//!   1. no generated struct declares a bare `Vec<u8>` or `&[u8]` field — an
//!      unnamed byte run goes through `Opaque`; and
//!   2. no library module names a capture, log, replay or fixture path, and no
//!      library module reads a file at all.
//!
//! If either rule breaks, this test fails.

use std::fs;
use std::path::{Path, PathBuf};

/// Substrings that would mean the codec had reached for a recording.
const RECORDING_TOKENS: &[&str] = &[
    "replay",
    "capture",
    "corpus",
    "fixture",
    "dump",
    "wire-bodies",
    "wire-fixtures",
    "messages-redacted",
    "rep_traffic",
    ".log",
    ".pcap",
];

/// Ways a module could pull bytes off disk.
const DISK_IO_TOKENS: &[&str] = &["std::fs", "include_bytes!", "include_str!", "File::open"];

fn src_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src")
}

fn rust_files(dir: &Path, out: &mut Vec<PathBuf>) {
    for entry in fs::read_dir(dir).expect("read src dir") {
        let path = entry.expect("dir entry").path();
        if path.is_dir() {
            rust_files(&path, out);
        } else if path.extension().is_some_and(|ext| ext == "rs") {
            out.push(path);
        }
    }
}

#[test]
fn generated_module_has_no_bare_byte_vector_field() {
    let path = src_dir().join("generated").join("mod.rs");
    let text = fs::read_to_string(&path).expect("generated module present");
    let mut checked = 0;
    for line in text.lines() {
        let Some(rest) = line.trim().strip_prefix("pub ") else {
            continue;
        };
        let Some((name, field_type)) = rest.split_once(':') else {
            continue;
        };
        // A field line is `pub <ident>: <type>,`; skip `pub fn`/`pub const`.
        if name.is_empty() || !name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
            continue;
        }
        let field_type = field_type.trim().trim_end_matches(',');
        assert!(
            field_type != "Vec<u8>" && field_type != "&[u8]",
            "bare byte field: {line}"
        );
        checked += 1;
    }
    assert!(checked > 0, "no generated fields were inspected");
}

#[test]
fn library_source_names_no_recording_path() {
    let mut files = Vec::new();
    rust_files(&src_dir(), &mut files);
    assert!(!files.is_empty(), "no library source found");
    for path in &files {
        let text = fs::read_to_string(path).expect("read library source");
        for token in RECORDING_TOKENS {
            assert!(
                !text.contains(token),
                "{} names a recording token {token:?}",
                path.display()
            );
        }
        for token in DISK_IO_TOKENS {
            assert!(
                !text.contains(token),
                "{} reads from disk via {token:?}",
                path.display()
            );
        }
    }
}
