"""/characters* routes (Azoth-local mock, shape GUESSED).

Live paths were never printed in Game.log; create happened during FTUE_V2_CC
(client_expect.json). Two handlers:

* list  — any path containing "/characters" (but not "/validator"): the
  frontend listed both existing and new characters, so it returns a list.
  Starts with one placeholder so a non-empty selection path exists.
* validator — "/characters/validator": permissive "valid" response.

Unknowns (iterate via the override file — strict JSON parsing means a missing
key or wrong type can surface as a client-side parse error, cf. STATUS.md):
* exact list envelope: bare array vs {"characters": [...]} — the bare array
  is served first; flip via override if the client chokes
* per-character field names/casing (name, id, level, appearance blobs)
* validator request body and expected verdict key

Override: <discovery_dir>/characters.json is served verbatim for the list;
<discovery_dir>/characters_validator.json for the validator (no restart).
"""

from __future__ import annotations

import json
from pathlib import Path

from .identity import AZOTH_CHARACTER_ID
from .registry import AZOTH_WORLD_ID

# Compatibility name retained for tools that imported the old placeholder.
PLACEHOLDER_CHARACTER_ID = AZOTH_CHARACTER_ID

LIST_OVERRIDE_NAME = "characters.json"
VALIDATOR_OVERRIDE_NAME = "characters_validator.json"


def _placeholder() -> dict:
    return {
        "characterId": PLACEHOLDER_CHARACTER_ID,
        "name": "Azoth",
        "level": 1,
        "worldId": AZOTH_WORLD_ID,
    }


def characters_response(discovery_dir: Path | None = None) -> bytes:
    if discovery_dir is not None:
        fp = discovery_dir / LIST_OVERRIDE_NAME
        if fp.is_file():
            return fp.read_bytes()
    return (json.dumps([_placeholder()]) + "\n").encode()


def characters_validator_response(discovery_dir: Path | None = None) -> bytes:
    if discovery_dir is not None:
        fp = discovery_dir / VALIDATOR_OVERRIDE_NAME
        if fp.is_file():
            return fp.read_bytes()
    return (json.dumps({"valid": True}) + "\n").encode()


def is_characters_path(path: str) -> bool:
    return "/characters" in path.split("?", 1)[0]


def is_characters_validator_path(path: str) -> bool:
    return "/characters/validator" in path.split("?", 1)[0]
