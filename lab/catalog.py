"""Resolve helpers from scripts/catalog.json and the RE workflow catalog."""

from __future__ import annotations

import json
from pathlib import Path

from lab.paths import ROOT, SCRIPTS

_SCRIPT_CATALOG: dict[str, dict] | None = None


def script_catalog() -> dict[str, dict]:
    global _SCRIPT_CATALOG
    if _SCRIPT_CATALOG is not None:
        return _SCRIPT_CATALOG
    path = SCRIPTS / "catalog.json"
    if not path.is_file():
        _SCRIPT_CATALOG = {}
        return _SCRIPT_CATALOG
    data = json.loads(path.read_text(encoding="utf-8"))
    _SCRIPT_CATALOG = dict(data.get("scripts") or {})
    return _SCRIPT_CATALOG


def resolve_script(name: str) -> Path | None:
    raw = name.strip().replace("\\", "/")
    stem = Path(raw).stem
    catalog = script_catalog()
    if stem in catalog:
        candidate = SCRIPTS / catalog[stem]["path"]
        if candidate.is_file():
            return candidate
    direct = SCRIPTS / raw
    if direct.is_file():
        return direct
    if not raw.endswith(".py") and not raw.endswith(".ps1"):
        for ext in (".py", ".ps1"):
            hit = SCRIPTS / f"{raw}{ext}"
            if hit.is_file():
                return hit
    pattern = Path(raw).name if "/" in raw or "\\" in raw else (
        raw if raw.endswith((".py", ".ps1")) else f"{raw}.py"
    )
    matches = [
        path
        for path in SCRIPTS.rglob(pattern)
        if path.is_file() and path.name != "catalog.json"
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def reverse_catalog() -> dict[str, dict]:
    path = ROOT / "reverse" / "tools" / "catalog.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data.get("workflows") or {})
