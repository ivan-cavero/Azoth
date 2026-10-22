//! Repository checks for the Rust workspace.
//!
//! WHY THIS EXISTS
//! ===============
//! The plan's admission rules are only rules if something enforces them. A rule
//! nobody checks decays into a preference within a month, and this workspace is
//! meant to stay coherent as it grows.
//!
//! WHAT IT CHECKS
//! ==============
//! * **File size.** A source file over ~400 lines means the module boundary is
//!   wrong. The counter-example this exists for is the Python world server's
//!   5,343-line `rep.py`.
//! * **No `unsafe`.** The workspace lint denies it; this checks the deny is
//!   actually inherited rather than overridden per crate.
//! * **Module docs.** Every crate states, in its first paragraph, why it exists.
//!
//! Run with `cargo xtask` from `server/`.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

/// A source file longer than this means the boundary is wrong, not that the
/// limit needs raising.
const MAX_LINES: usize = 400;

fn main() -> ExitCode {
    let root = match workspace_root() {
        Some(root) => root,
        None => {
            eprintln!("xtask: cannot find the workspace root (no Cargo.toml with [workspace])");
            return ExitCode::FAILURE;
        }
    };
    let mut failures = 0;
    failures += check_file_sizes(&root);
    failures += check_crate_docs(&root);
    failures += check_no_unsafe_override(&root);

    if failures == 0 {
        println!("xtask: all checks passed");
        ExitCode::SUCCESS
    } else {
        eprintln!("xtask: {failures} check(s) failed");
        ExitCode::FAILURE
    }
}

fn workspace_root() -> Option<PathBuf> {
    let mut dir = std::env::current_dir().ok()?;
    loop {
        let candidate = dir.join("Cargo.toml");
        if let Ok(text) = fs::read_to_string(&candidate)
            && text.contains("[workspace]")
        {
            return Some(dir);
        }
        if !dir.pop() {
            return None;
        }
    }
}

/// Every `*.rs` under `crates/` and `apps/`, excluding tests and targets.
fn rust_sources(root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    for dir in ["crates", "apps"] {
        walk(&root.join(dir), &mut out);
    }
    out
}

fn walk(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            if path.file_name().is_some_and(|n| n == "target") {
                continue;
            }
            walk(&path, out);
        } else if path.extension().is_some_and(|e| e == "rs") {
            out.push(path);
        }
    }
}

fn check_file_sizes(root: &Path) -> usize {
    let mut failures = 0;
    for path in rust_sources(root) {
        let Ok(text) = fs::read_to_string(&path) else {
            continue;
        };
        let lines = text.lines().count();
        if lines > MAX_LINES {
            let rel = path.strip_prefix(root).unwrap_or(&path);
            eprintln!(
                "  {}: {lines} lines (limit {MAX_LINES}) -- split by responsibility",
                rel.display()
            );
            failures += 1;
        }
    }
    failures
}

fn check_crate_docs(root: &Path) -> usize {
    let mut failures = 0;
    for path in rust_sources(root) {
        if path.file_name().is_some_and(|n| n == "lib.rs" || n == "main.rs") {
            let Ok(text) = fs::read_to_string(&path) else {
                continue;
            };
            if !text.trim_start().starts_with("//!") {
                let rel = path.strip_prefix(root).unwrap_or(&path);
                eprintln!("  {}: no crate-level `//!` doc", rel.display());
                failures += 1;
            }
        }
    }
    failures
}

fn check_no_unsafe_override(root: &Path) -> usize {
    let mut failures = 0;
    for path in rust_sources(root) {
        let Ok(text) = fs::read_to_string(&path) else {
            continue;
        };
        // `#![allow(unsafe_code)]` in a crate root would defeat the workspace deny.
        if text.contains("allow(unsafe_code)") {
            let rel = path.strip_prefix(root).unwrap_or(&path);
            eprintln!("  {}: overrides the workspace `unsafe_code` deny", rel.display());
            failures += 1;
        }
    }
    failures
}
