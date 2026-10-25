"""Shared refusal for helpers that used to write the deleted Rust tree."""

from __future__ import annotations

from pathlib import Path


def refuse_if_no_server(start: Path) -> int:
    """Return 2 when server/Cargo.toml is gone. Return 0 when the tree exists."""
    root = start.resolve()
    if root.is_file():
        root = root.parent
    while not (root / "ef.py").is_file():
        if root.parent == root:
            print("repo root not found; refusing to write a server tree")
            return 2
        root = root.parent
    if (root / "server" / "Cargo.toml").is_file():
        return 0
    print("server/ is not in this checkout.")
    print("This helper used to write Rust fixtures. It does not recreate server/.")
    print("See research/atlas/meanings.md.")
    return 2
