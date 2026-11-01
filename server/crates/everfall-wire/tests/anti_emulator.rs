//! Anti-emulator guard: the library must stay a codec, not a replay.
//!
//! The owner's requirement: the Rust side is the best-practice server, never an
//! emulator or a replay. Two rules are mechanised here against the library
//! source (`src/`, the crate's own modules; integration tests are separate
//! crates that consume the committed corpus, they are not the codec):
//!
//!   1. no generated struct declares a bare `Vec<u8>` or `&[u8]` field — an
//!      unnamed byte run goes through `Opaque`; and
//!   2. no library module READS a recording: it may not call a file API
//!      (`std::fs`, `File::open`, `read_to_string`, `read`, `include_bytes!`,
//!      `include_str!`) nor hold a string literal that names a recording
//!      location (`.azoth`, `world.log`, `messages-redacted`, `replay`,
//!      `fixtures/`).
//!
//! Rule 2 looks at behaviour, not at identifiers. A field or type whose name
//! merely contains the word `capture` is a protocol name from the client's own
//! reflection strings, and is exactly what this crate must keep.
//!
//! If either rule breaks, this test fails.

use std::fs;
use std::path::{Path, PathBuf};

/// File-reading APIs. Matched against comment-stripped source, so the prose in
/// a doc comment cannot trip the guard.
const FILE_API_TOKENS: &[&str] = &[
    "std::fs",
    "File::open",
    "read_to_string",
    "include_bytes!",
    "include_str!",
];

/// Substrings of a string literal that would mean the codec had reached for a
/// recording. Matched only inside string literals, never inside an identifier.
const RECORDING_PATH_TOKENS: &[&str] = &[
    ".azoth",
    "world.log",
    "messages-redacted",
    "replay",
    "fixtures/",
];

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

/// Library code with comments removed and string bodies erased, plus every
/// string literal the source holds.
struct Scan {
    code: String,
    strings: Vec<String>,
}

fn is_ident_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || byte == b'_'
}

fn scan(source: &str) -> Scan {
    let chars: Vec<char> = source.chars().collect();
    let mut code = String::with_capacity(source.len());
    let mut strings = Vec::new();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c == '/' && chars.get(i + 1) == Some(&'/') {
            i += 2;
            while i < chars.len() && chars[i] != '\n' {
                i += 1;
            }
            code.push('\n');
            continue;
        }
        if c == '/' && chars.get(i + 1) == Some(&'*') {
            i += 2;
            while i < chars.len() && !(chars[i] == '*' && chars.get(i + 1) == Some(&'/')) {
                i += 1;
            }
            i = (i + 2).min(chars.len());
            code.push(' ');
            continue;
        }
        if c == '"' {
            i += 1;
            let mut literal = String::new();
            while i < chars.len() && chars[i] != '"' {
                if chars[i] == '\\' && i + 1 < chars.len() {
                    literal.push(chars[i + 1]);
                    i += 2;
                } else {
                    literal.push(chars[i]);
                    i += 1;
                }
            }
            i = (i + 1).min(chars.len());
            strings.push(literal);
            code.push_str("\"\"");
            continue;
        }
        if c == '\'' {
            // A char literal is `'x'` or `'\x'`; a lifetime has no closing quote
            // two or three characters on, so it falls through untouched.
            let escaped = chars.get(i + 1) == Some(&'\\');
            let close = if escaped { i + 3 } else { i + 2 };
            if chars.get(close) == Some(&'\'') {
                code.push_str("' '");
                i = close + 1;
                continue;
            }
        }
        code.push(c);
        i += 1;
    }
    Scan { code, strings }
}

/// True when the code holds a free `read` that is called or path-qualified,
/// e.g. `std::io::read(..)` or `.read(..)`. A bare identifier named `read` is
/// not I/O on its own, and `read_to_string`/`read_from` are separate tokens.
fn calls_a_free_read(code: &str) -> bool {
    let bytes = code.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if !(bytes[i].is_ascii_alphabetic() || bytes[i] == b'_') {
            i += 1;
            continue;
        }
        let start = i;
        while i < bytes.len() && is_ident_byte(bytes[i]) {
            i += 1;
        }
        if &code[start..i] == "read" {
            let rest = code[i..].trim_start();
            if rest.starts_with('(') || rest.starts_with("::") {
                return true;
            }
        }
    }
    false
}

/// Every way `source` reads a recording. Empty means the guard is satisfied.
fn violations(source: &str) -> Vec<String> {
    let scanned = scan(source);
    let mut found = Vec::new();
    for token in FILE_API_TOKENS {
        if scanned.code.contains(token) {
            found.push(format!("file API {token:?}"));
        }
    }
    if calls_a_free_read(&scanned.code) {
        found.push("a file `read` call".to_owned());
    }
    for literal in &scanned.strings {
        for token in RECORDING_PATH_TOKENS {
            if literal.contains(token) {
                found.push(format!("recording path {literal:?} (names {token:?})"));
            }
        }
    }
    found
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
fn library_source_reads_no_recording() {
    let mut files = Vec::new();
    rust_files(&src_dir(), &mut files);
    assert!(!files.is_empty(), "no library source found");
    for path in &files {
        let text = fs::read_to_string(path).expect("read library source");
        let found = violations(&text);
        assert!(
            found.is_empty(),
            "{} reads a recording: {found:?}",
            path.display()
        );
    }
}

#[test]
fn a_source_that_opens_a_file_is_flagged() {
    let via_std_fs = r#"
        use std::fs;
        fn load() -> String {
            std::fs::read_to_string("data.bin").expect("a file")
        }
    "#;
    let via_file_open = r#"
        fn load() {
            let mut file = File::open("data.bin").expect("a file");
        }
    "#;
    let via_free_read = r"
        fn load(handle: u64, buf: &mut [u8]) {
            read(handle, buf);
        }
    ";
    for source in [via_std_fs, via_file_open, via_free_read] {
        assert!(
            !violations(source).is_empty(),
            "a source that opens a file must fail the guard: {source}"
        );
    }
}

#[test]
fn a_source_that_names_a_log_path_is_flagged() {
    let source = r#"
        const LOG: &str = "fixtures/world.log";
    "#;
    assert!(
        !violations(source).is_empty(),
        "a source that names a recording path must fail the guard"
    );
}

#[test]
fn a_field_named_capture_is_not_flagged() {
    let source = r"
        pub struct TransmogState {
            pub capturedArmorAppearances: Vec<u8>,
            pub capturedWeaponAppearances: Vec<u8>,
        }
    ";
    assert!(
        violations(source).is_empty(),
        "a protocol name containing `capture` is not recording I/O"
    );
}
