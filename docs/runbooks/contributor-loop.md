# Contributor loop

How a new person should work day-to-day. Planning detail:
[`PLAN-master-platform.md`](../PLAN-master-platform.md) §0D–0E.

## 0. Clone and doctor

```text
git clone <repo>
cd <repo>
.\az.ps1 setup              # Windows: core profile (Python + Caddy)
# or: python az.py setup --core
python az.py doctor         # checklist: tools, Rust, OpenSSL
```

`setup --re` adds Ghidra+JDK (large). `setup --purge` removes `.azoth`
caches. Server binaries also target **Linux** (Docker later); private client
stays Windows.

## 1. Run the stack (native — ADR 0009)

```text
python az.py dev            # gateway + world + caddy on the host
python az.py status
# logs: .azoth/logs/
python az.py game           # private client (Steam install + setup)
```

**Do not use Compose for this loop on Windows.** Compose is Linux/CI/prod
(`deploy/local/compose.yml`) only.

Hot reload: gateway JSON/routes reload on mtime; restart Rust world after code
changes. Content hot-reload is a later milestone.

## 2. Tests that matter

```text
cd server
cargo test -p azoth-wire -p azoth-session -p azoth-model
# Prefer scenario names: expired_ticket_after_auth_does_not_kick
python az.py doctor
# e2e (when harness lands): python az.py test e2e entry
```

Do not add tests that only assert a getter. See ADR 0007.

## 3. Reverse engineering (optional)

```text
python az.py setup --re
python az.py re list
# Corpora under reverse/builds/<sha256>/ — never Frida while EAC uncertain
```

## 4. Docs / atlas

- Frontier: `STATUS.md` (short).
- Facts: `research/atlas/` + ontology.
- Legal: `docs/LEGAL.md` before sharing captures or monetization ideas.

## 5. Web / dashboards

When `site/` or `platform/web` grows: Vitest for logic, Playwright for
login/privacy/ban journeys. No CSS-class archaeology.
