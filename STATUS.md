# Live status

Frontier only. Diary:
[`docs/journal/raw/2026-10-status-dump.md`](docs/journal/raw/2026-10-status-dump.md).
Platform: [`docs/PLAN-master-platform.md`](docs/PLAN-master-platform.md).
Legal: [`docs/LEGAL.md`](docs/LEGAL.md). Official NW offline: **2027-01-31**.
Daily loop: **`az.py dev`** (not Compose) — ADR 0009.

## Active blocker

**Presence layouts identified, not decoded** (`presence-codecs.json`). Next
unit: live unmarshal → ontology `layout`.

Build: **1.460.6033.6024067** —
`30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.

## Reorg ready for agents

Knowledge OS, ontology, roadmap v2, LEGAL/funding/testing, setup profiles +
`doctor`, model/commands/privacy, Linux compose (CI only), `platform/`
skeletons, boot-naming campaign runbook. Python play path still transitional.

## Next useful step

1. **Agentic boot-naming campaign** —
   [`docs/runbooks/agentic-boot-campaign.md`](docs/runbooks/agentic-boot-campaign.md)
   (name every critical-path surface open → InGame).
2. Then presence layouts + Rust domain spawn; enter world on `az.py dev`.
3. Fix MSVC OpenSSL (`az doctor` flags MinGW mix).
4. Lock rename (ADR 0005).

## Do not

- Develop private-client loop inside Compose on Windows.
- Reload `docs/journal/raw/`; ship PAKs; claim Amazon affiliation.
