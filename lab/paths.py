"""Checkout paths. Import this instead of repeating Path(__file__)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
STATE = ROOT / ".azoth" / "state"
LOGS = ROOT / ".azoth" / "logs"
PRIVATE = ROOT / "private-client"
TMP = ROOT / ".azoth" / "tmp"
