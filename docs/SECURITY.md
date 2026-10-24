# Security and privacy (design)

Status: **draft** for P1. Not an implementation checklist until acceptance tests exist.
Normative product rules: [`PLAN-master-platform.md`](PLAN-master-platform.md) §4.

## Threat model (condensed)

| Asset | Threat | Control direction |
| --- | --- | --- |
| Accounts | Stuffing, token theft | Hashed secrets, rotated tokens, rate limits |
| Character / inventory / currency | Client forgery, duping | Server authority; ignore client wealth claims |
| Admin commands | Privilege escalation | RBAC + audit-before-apply |
| Private profile/stats | Scraping | Default-deny privacy engine |
| Launcher / patches | Supply chain | Hash + signature; no `:latest` in prod images |
| World process | Parse RCE | Bounded codecs; fuzz; admin off public NIC |
| Secrets | Git/log leak | `.azoth` / k8s Secrets only |

## Privacy defaults

| Field class | Default |
| --- | --- |
| Online status | friends / private |
| Character list | private |
| Gear / inventory detail | private (not public) |
| Rankings | opt-in |
| Exact map location via public API | never |

Unauthorized public reads → `404` (no existence leak) unless policy says `403`.

## Agent / ops rules

- High-risk PRs (`azoth-wire`, privacy, economy, auth): human merge only.
- LLM never promotes atlas to `verified` alone.
- Journal `raw/` dumps are not threat intel to paste into chats.

## Open measurements

- Live privacy-endpoint shape against our stack (PLAN-backend-rust still flags this).
- Command-bus authn for opsd (mTLS vs SSO) — decide in an ADR before coding.
