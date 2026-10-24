#!/usr/bin/env python3
"""Stub for `az test e2e entry` — offline scenario gates (ADR 0007).

Runs crate tests that encode real failure modes (tickets, RBAC, privacy,
wire). Live InGame soak still needs OpenSSL + private client.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"


def main() -> int:
    cmd = [
        "cargo",
        "test",
        "--offline",
        "-p",
        "azoth-model",
        "-p",
        "azoth-session",
        "-p",
        "azoth-commands",
        "-p",
        "azoth-privacy",
        "-p",
        "azoth-wire",
    ]
    print("+", " ".join(cmd))
    code = subprocess.call(cmd, cwd=SERVER)
    if code:
        return code
    print("e2e-entry-stub: offline scenario crates ok")
    print("next: live InGame soak (OpenSSL + private client)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
