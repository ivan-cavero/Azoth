# Docs

Start with [project status](../STATUS.md) (frontier only), then the reference
for the work at hand. Taxonomy: [`PLAN-master-platform.md`](PLAN-master-platform.md) §13.

| Work | Read |
| --- | --- |
| Run the local stack | [README](../README.md), [deploy](../deploy/README.md) |
| Change Windows host routing | [Admin operations](ADMIN.md) |
| **Platform / reorg / agents / security vision** | [Master platform plan](PLAN-master-platform.md) |
| Rust crates, tick, DTLS, capacity mechanics | [Rust backend plan](PLAN-backend-rust.md) |
| Short architecture boundaries | [Architecture](ARCHITECTURE.md) |
| Near-term sequencing | [Roadmap](ROADMAP.md) |
| ADRs | [`adr/`](adr/) |
| Status diaries | [`journal/`](journal/) |
| Operator / overnight agents | [`runbooks/`](runbooks/) |
| Gateway or world (Python prototype) | [Gateway](../services/docs/GATEWAY.md), [World](../services/world/README.md) |
| Reverse engineer the client | [Reverse tools](../reverse/README.md), [Research index](../research/docs/INDEX.md), [ontology](../research/atlas/ontology/) |
| Public landing / roadmap display | [site/README](../site/README.md) — **v2 live**; v1 inventory archived |
| Security / privacy design | [SECURITY.md](SECURITY.md) |
| Legal / preservation / collab | [LEGAL.md](LEGAL.md), [`../NOTICE`](../NOTICE), [`../CONTRIBUTING.md`](../CONTRIBUTING.md) |
| Rename / binary names | [ADR 0005](adr/0005-project-rename.md), [ADR 0006](adr/0006-binary-naming.md) |
| DTLS / OpenSSL choice | [ADR 0004](adr/0004-dtls-crypto-stack.md), [Rust plan §0.3](PLAN-backend-rust.md) |
| Doc budget check | `python scripts/check-docs.py` (via project Python) |
| Historical archives | [`archive/`](archive/), [`sessions/`](sessions/) |

Implementation facts belong next to code or in `research/atlas/`. This folder
holds project-wide guidance, plans, ADRs, journals, and runbooks.
