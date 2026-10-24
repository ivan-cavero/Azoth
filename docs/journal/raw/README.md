# Raw journal dumps — DO NOT LOAD INTO AGENT CONTEXT

These files exist so history is not deleted. They are **not** working docs.

| File | What it is |
| --- | --- |
| `2026-10-status-dump.md` | Full pre-compaction STATUS (~2884 lines). Ontology + atlas supersede it for facts. |

**Agents:** never `Read` these files end-to-end. Use ripgrep with a pattern and
`head_limit`. Prefer `research/atlas/` and ontology concepts instead.

**Humans:** split or delete only after confirming atlas/ontology already hold
the durable claims you care about.
