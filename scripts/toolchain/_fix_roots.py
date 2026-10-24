#!/usr/bin/env python3
"""Fix Path(__file__).parents[1] → parents[2] after scripts/<kind>/ move."""

from __future__ import annotations

from pathlib import Path

# This file lives in scripts/toolchain/ → parents[1] == scripts/
SCRIPTS = Path(__file__).resolve().parents[1]


def main() -> int:
    fixes = 0
    for path in SCRIPTS.rglob("*.py"):
        if path.parent == SCRIPTS or path.name.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8")
        orig = text
        text = text.replace(
            "Path(__file__).resolve().parents[1]",
            "Path(__file__).resolve().parents[2]",
        )
        if path.name in {"corpus-contains.py", "corpus-fn.py"}:
            text = text.replace(
                "Path(__file__).resolve().parent.parent",
                "Path(__file__).resolve().parents[2]",
            )
        if path.name == "export-wire-fixtures.py":
            old = 'Path(__file__).resolve().parent / "measure-inventory-grammar.py"'
            new = (
                'Path(__file__).resolve().parents[1] / "measure" / '
                '"measure-inventory-grammar.py"'
            )
            text = text.replace(old, new)
        if text != orig:
            path.write_text(text, encoding="utf-8", newline="\n")
            fixes += 1
            print(f"fixed {path.relative_to(SCRIPTS.parent)}")
    print(f"files fixed: {fixes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
