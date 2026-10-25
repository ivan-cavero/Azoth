#!/usr/bin/env python3
"""Offline entry check. The Rust crates this used to run are not in the tree."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from _server_gate import refuse_if_no_server  # noqa: E402


def main() -> int:
    return refuse_if_no_server(Path(__file__))


if __name__ == "__main__":
    raise SystemExit(main())
