# Status journals

Root [`STATUS.md`](../../STATUS.md) is the **frontier only** (hard budget: **80 lines**).
That novel-sized dump must never return to the root.

## Layout

| Path | Role | Agent rule |
| --- | --- | --- |
| `YYYY-MM.md` | New monthly diaries (create as needed) | Read only the section you need |
| [`raw/`](raw/) | Frozen dumps (e.g. pre-compaction STATUS) | **Do not load whole files** |

## Hard rules

1. Never grow root `STATUS.md` past 80 lines (`python scripts/check-docs.py`).
2. Never restore a multi-thousand-line STATUS at repo root.
3. Durable facts → `research/atlas/` / ontology, not journal prose.
4. Agents needing history: `rg -n "keyword" docs/journal/raw -g "*.md"` with a
   head limit — not `Read` of the entire dump.
