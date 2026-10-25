#!/usr/bin/env python3
"""Enforce knowledge-OS doc budgets (PLAN-master-platform P0).

Fails when:
  - root STATUS.md exceeds STATUS_MAX_LINES
  - a multi-k line STATUS novel reappears at repo root under another name
  - public gen-roadmap still imports the v1 inventory
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATUS_MAX_LINES = 80
NOVEL_LINE_FLOOR = 500


def fail(msg: str) -> None:
    print(f"check-docs: FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    status = ROOT / "STATUS.md"
    if not status.is_file():
        fail("STATUS.md missing at repo root")
    lines = status.read_text(encoding="utf-8").splitlines()
    if len(lines) > STATUS_MAX_LINES:
        fail(f"STATUS.md has {len(lines)} lines (max {STATUS_MAX_LINES})")

    # Block accidental reintroduction of a STATUS novel at root.
    for path in ROOT.glob("STATUS*.md"):
        n = len(path.read_text(encoding="utf-8").splitlines())
        if path.name != "STATUS.md" and n >= NOVEL_LINE_FLOOR:
            fail(f"{path.name} looks like a STATUS novel ({n} lines); keep dumps under docs/journal/raw/")
        if path.name == "STATUS.md" and n >= NOVEL_LINE_FLOOR:
            fail(f"STATUS.md is a novel again ({n} lines)")

    gen = (ROOT / "platform/web/scripts/gen-roadmap.mjs").read_text(encoding="utf-8")
    if "roadmap-full" in gen or "roadmap-v1-inventory" in gen:
        fail("gen-roadmap.mjs must import roadmap-v2 only, not v1 inventory")

    raw_readme = ROOT / "docs/journal/raw/README.md"
    if not raw_readme.is_file():
        fail("docs/journal/raw/README.md missing (agents need the do-not-load rule)")

    for required in (
        ROOT / "docs/LEGAL.md",
        ROOT / "docs/runbooks/contributor-loop.md",
        ROOT / "docs/runbooks/agentic-boot-campaign.md",
        ROOT / "docs/adr/0009-native-dev-vs-compose.md",
        ROOT / "deploy/local/compose.yml",
        ROOT / "platform/README.md",
        ROOT / ".agents/README.md",
        ROOT / ".agents/skills/everfall-next/SKILL.md",
        ROOT / ".agents/skills/everfall-server/SKILL.md",
        ROOT / ".agents/skills/rust/SKILL.md",
        ROOT / ".agents/skills/rust/references/REFERENCE.md",
        ROOT / ".agents/skills/python/SKILL.md",
        ROOT / ".agents/skills/python/references/REFERENCE.md",
        ROOT / ".agents/skills/javascript/SKILL.md",
        ROOT / ".agents/skills/javascript/references/REFERENCE.md",
        ROOT / ".agents/skills/protocols/SKILL.md",
        ROOT / ".agents/skills/protocols/references/REFERENCE.md",
        ROOT / ".agents/skills/security/SKILL.md",
        ROOT / ".agents/skills/security/references/REFERENCE.md",
        ROOT / ".agents/skills/naming/SKILL.md",
        ROOT / "research/atlas/meanings.md",
        ROOT / "docs/PLAN.md",
        ROOT / "scripts/catalog.json",
        ROOT / "scripts/README.md",
    ):
        if not required.is_file():
            fail(f"missing reorg artifact: {required.relative_to(ROOT)}")

    print(
        f"check-docs: ok (STATUS.md {len(lines)}/{STATUS_MAX_LINES} lines; roadmap v2 wired)"
    )


if __name__ == "__main__":
    main()
