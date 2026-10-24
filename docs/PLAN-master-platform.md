# Azoth master platform plan

Planning document. **No implementation is authorized by this file.**

This is the absolute north star for product, security, knowledge, repository
and **documentation** reorganization, runtime architecture, operations,
**agentic factories** (overnight/day-long measured runs), the public site, and
the path to a fully playable private world that can later outscale and
out-operate the original Amazon services — and out-iterate competing private
server projects — **measured, not wished**.

| | |
| --- | --- |
| Companion runtime plan | [`PLAN-backend-rust.md`](PLAN-backend-rust.md) — crates, tick, DTLS, region/world, capacity |
| Architecture (current short form) | [`ARCHITECTURE.md`](ARCHITECTURE.md) — amended by §3 of this file over time |
| Active frontier | [`../STATUS.md`](../STATUS.md) — ≤ ~80 lines; one blocker |
| Sequencing | [`ROADMAP.md`](ROADMAP.md) — phase checkboxes without duplicating design |
| Client build (today) | **1.460.6033.6024067** — SHA-256 in `research/atlas/builds.json` |

**Conflict rules**

- Runtime mechanics (tick, wire, DTLS, store layout) → `PLAN-backend-rust.md` wins
  until amended.
- Product, security, privacy, repo/docs layout, Docker/K8s, ontology OS,
  admin/API, launcher, gameplay vertical order, **agent factory**, **public
  site/roadmap** → **this file wins**; amend the Rust plan and
  `ARCHITECTURE.md` to match.

**Correct framing of today’s Rust server:** the world process is already a real
authoritative process (no replay pump). Early captured templates are bootstrap
seeds. The debt is domain layering, knowledge, playable systems, and ops — not
“still a replayer.” Byte archaeology in app code is **technical debt to retire**,
not the product shape.

**Working name:** this repository still says “Azoth.” That brand collides with
an established community project ([projectazoth.com](https://projectazoth.com/)).
**Rename is planned** ([ADR 0005](adr/0005-project-rename.md)); docs below say
“this project” where brand matters. Binary name `worldd` is also under review
([ADR 0006](adr/0006-binary-naming.md)).

---

## 0A. Mission: keep New World playable after shutdown

Amazon’s official statement (2026-01-15): **New World: Aeternum is delisted**
and **servers go permanently offline on 2027-01-31**. Owners can play until
then; Marks of Fortune purchases end 2026-07-20. Source:
[official news](https://www.newworld.com/en-us/news/articles/the-future-of-new-world-aeternum-what-to-expect).

This project’s purpose is **preservation and a private, self-hosted life for
the game** after that date — not competing with live Amazon commerce, and not
impersonating Amazon Games.

Legal / community posture lives in [`LEGAL.md`](LEGAL.md),
[`NOTICE`](../NOTICE), [`CONTRIBUTING.md`](../CONTRIBUTING.md), and
[ADR 0003](adr/0003-legal-preservation-posture.md). **Not legal advice** —
engineering defaults that keep the project honest and reviewable:

1. **No Amazon/New World assets in Git** — client PAKs, Steam trees, ripped
   textures/audio stay local / ignored; players bring their own legally obtained
   client.
2. **Original server code is ours** — clean-room / protocol-compatible
   reimplementation; do not ship Amazon binaries or leaked server source.
3. **Non-commercial default** until counsel + rights-holder posture is clear;
   donations/ops costs need an entity and policy before monetization.
4. **Unofficial labelling** everywhere public (site, launcher, Discord).
5. **No EAC circumvention as a product feature** — private-client workflows
   already documented in-repo; do not market “bypass” tools.
6. **Seek dialogue** with Amazon Games for a sanctioned hand-off / license if
   that becomes possible; document attempts in journal, not marketing claims.
7. **Collaborators** warrant they submit only what they have rights to; DCO or
   CLA when GitHub opens (P22).

Hard deadline pressure: **playable spine before 2027-01-31** matters more than
website polish. Capture while official servers still answer.

---

## 0. Vision

This project becomes a self-hosted New World–compatible **studio platform**:

1. **Fully playable loop first** — enter world, move, gather, craft, quest,
   dungeon, farm XP/gear, PvP, persist characters — against an authoritative
   Rust stack.
2. **Understands the game completely** — ontology of messages, systems, content
   ids, admin commands; entrails extracted via RE + AI with promotion gates.
3. **Secure by default** — least privilege, audited mutations, private profiles,
   signed patches, secret hygiene, hardened containers.
4. **Clone-anywhere** — any machine that clones the repo + runs setup gets a
   working private stack; no machine-specific paths; Steam remains read-only
   source of assets.
5. **Operable** — ban/kick/grant/teleport/bots, live map, Grafana, in-game GM
   panel; one command bus.
6. **Player platform** — launcher, web accounts, public API with **privacy
   controls** (profiles/stats/inventory visibility by consent).
7. **Scalable ops** — local compose today; Docker images for every plane;
   Kubernetes (+ game-server fleet patterns such as Agones) for dynamic world
   scale later.
8. **Better than original on falsifiable metrics** — tick p99, CCU/process,
   bytes/player, reconnect — on recorded hardware.
9. **Content + client evolution** — authored content; then strip AWS; then
   protocol/client improvements behind capability bits.
10. **AI-built with discipline** — short AGENTS.md, skills, ontology promotion;
    never “LLM said verified.”
11. **Agentic velocity is a product** — long-running, checkpointed, observed
    agent graphs (LangGraph-class) with a dashboard; overnight RE/ontology/
    parity batches that resume after crash.
12. **One living roadmap, two surfaces** — internal tracker for work;
    public `site/` roadmap + future player landing that show *evidence-backed*
    progress, server health, and (later) leaderboards/profiles.
13. **Win by iteration speed** — competitors with messier knowledge and no
    agent factory lose; the edge is measured loops: hypothesis → agent run
    → promote → e2e → ship.
14. **Feel like a real MMORPG server** — model/sim/replica own meaning; wire
    owns bytes; capture seeds are temporary, named, and retired.
15. **Honest brand** — rename away from colliding “Azoth”; never claim Amazon
    affiliation.

```text
 Player PC                         Studio cluster (future)
 ┌──────────────┐                  ┌─────────────────────────────┐
 │ Launcher     │                  │ Ingress / TLS               │
 │  download    │                  │ channel  (Deploy)           │
 │  verify sig  │                  │ region   (Deploy)           │
 │  start game  │                  │ world    (Fleet / Agones)   │
 └──────┬───────┘                  │ ops      (Deploy)           │
        │                          │ Postgres / object store     │
        ▼                          │ Prometheus / Grafana        │
 ┌──────────────┐                  └─────────────────────────────┘
 │ NW client    │◀──── HTTPS / DTLS ──── same binaries, more replicas
 │ (patched)    │
 └──────────────┘

 Dev PC (clone)
 ┌──────────────────────────────────────┐
 │ az setup → local tools               │
 │ docker compose OR az.dev local procs │
 │ private-client/ (ignored)            │
 │ reverse/builds/<sha>/ (ignored)      │
 └──────────────────────────────────────┘
```

---

## 0B. DTLS / crypto stack (performance + correctness)

Full mechanics and measured ClientHello: `PLAN-backend-rust.md` §0.3.
Decision record: [ADR 0004](adr/0004-dtls-crypto-stack.md).

**Hard constraint:** build 1.460 offers **only**
`TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384` (`0xC030`) over **DTLS 1.2**. Any stack
that cannot negotiate that suite + HelloVerifyRequest cookies is disqualified
regardless of TLS-only benchmarks.

| Option | DTLS 1.2 + 0xC030 | Perf signal | Verdict |
| --- | --- | --- | --- |
| **OpenSSL 3.x (`openssl` crate)** | Proven live (Python + Rust) | TLS: slower than rustls/BoringSSL; DTLS write ~14% slower in 3.2+ vs 3.1 ([openssl#26055](https://github.com/openssl/openssl/issues/26055)) | **Keep production path** until a peer is measured equal on the real client |
| **rustls** | **No DTLS** ([rustls#40](https://github.com/rustls/rustls/issues/40)) | Excellent TLS benches | Watch only |
| **BoringSSL / aws-lc** | No drop-in Rust DTLS for our suite | Strong TLS | Not a swap |
| **NoxTLS / pure-Rust DTLS** | Claims DTLS 1.2 + `0xC030` | Unproven vs NW | Spike later behind `azoth-dtls` only |
| **Custom DTLS** | Risky | — | Forbidden until after playable spine |

**Windows/link:** one documented toolchain (MSVC + vcpkg **or** pinned MSYS2).
Never mix MinGW OpenSSL into an MSVC `rustc` link. Avoid day-to-day
`vendored` OpenSSL on Windows (multi-minute builds). Docker static-links once
for releases.

**Perf order:** correct handshake → isolate in `azoth-dtls` → PPS/CPU harness →
A/B alternate DTLS only against the real client.

---

## 0C. Naming & binary names

| Topic | Decision |
| --- | --- |
| Project brand | **Rename** — “Azoth” collides with [Azoth Central](https://projectazoth.com/) ([ADR 0005](adr/0005-project-rename.md)). Repo keeps old name until cutover. |
| `worldd` | Awkward double-*d*. Public binary **`world`**; crate may stay `worldd` until rename batch ([ADR 0006](adr/0006-binary-naming.md)). Same pattern for channel/region/ops. |
| Crate prefix `azoth-*` | Renames with brand in one mechanical PR after name lock. |

---

## 0D. Contributor DX — `az` setup, logs, hot reload, Linux

Anyone who clones should be able to **develop, decompile (optional), raise the
stack, watch logs, iterate, and run real tests** without tribal knowledge.
`az setup` stays the entry point, but it must stop being a kitchen-sink that
always pulls Ghidra+JDK.

### Setup profiles (product rule)

| Profile | Installs | Who |
| --- | --- | --- |
| **`core`** (default) | Project Python + venv deps + Caddy | Server/web contributors |
| **`re`** | core + Ghidra + JDK | Reverse engineers |
| **`openssl`** | Documented OpenSSL for the host (vcpkg/apt/msys — **not** random PATH pollution) | Anyone building `azoth-dtls` |
| **`all`** | core + re + openssl helper | Maintainers |

Rules:

1. Everything lives under **`.azoth/`** (or Docker volumes) — wipe = gone.
2. **No system leftovers** by default: no global PATH edits, no Start Menu
   shortcuts, no Admin installers unless the user opts in.
3. `az doctor` prints a checklist (Python, Caddy, Rust, OpenSSL link, Docker)
   with exact fix commands; `az setup --purge` deletes `.azoth` caches.
4. **Windows + Linux first-class** for server binaries; Windows remains the
   private-client host. Docker images are the Linux truth for CI/prod.
5. **Daily loop = native `az.py dev`** (Windows host processes). Compose is
   for Linux/CI/prod smoke only — [ADR 0009](adr/0009-native-dev-vs-compose.md).
   Do not develop the private-client path inside Docker on Windows.
6. Hot reload: gateway routes mtime-reload; restart Rust world after code
   changes. Loop: [`docs/runbooks/contributor-loop.md`](runbooks/contributor-loop.md).
7. Logs: `.azoth/logs/` + `az status`. No hunting AppData.
8. `.gitignore` only ignores regenerable / secret / huge local state.
9. First agentic RE after reorg:
   [`runbooks/agentic-boot-campaign.md`](runbooks/agentic-boot-campaign.md)
   (name everything from boot → InGame).

### OpenSSL install policy (ties to §0B / ADR 0004)

| Host | Preferred | Removable |
| --- | --- | --- |
| Windows MSVC | `vcpkg install openssl:x64-windows` under a **project or user vcpkg** dir documented by `az doctor` | delete vcpkg tree + unset `VCPKG_ROOT` |
| Windows GNU | only if rustc is GNU; MSYS2 `mingw-w64-x86_64-openssl` | pacman uninstall |
| Linux | `libssl-dev` / distro openssl-devel | apt/dnf remove |
| Docker | build stage installs headers; runtime uses distroless/slim with `.so` or static | image rebuild |

Never recommend “vendored OpenSSL every day on Windows.”

---

## 0E. Testing doctrine — real scenarios, not decorative units

**Hate signal we agree with:** a test that only asserts a getter or a happy-path
pure function while the real failure modes (expired ticket, bad cipher, chunk
loss, unauthorized API, empty AOI) are untested is **noise**. Prefer fewer,
meaner tests. Full doctrine: [ADR 0007](adr/0007-testing-doctrine.md).

### Layers (all languages)

| Layer | What it proves | Tools |
| --- | --- | --- |
| **Contract / property** | Parsers, codecs, invariants, round-trips; shrink failures | Rust `proptest`; JS property tests sparingly |
| **Scenario integration** | Multi-module behaviour with fakes: ticket expiry after auth must not kick; ladder order; privacy deny | Rust `tests/`; nextest; Vitest for API clients |
| **Harness / e2e** | Real processes: `channel`+`region`+`world` (+ optional private client headless/scripted) | `az test e2e …`; Playwright for web; recorded fixtures |
| **Benchmarks** | Tick p99, DTLS PPS, AOI cost — **with hardware record** | Criterion; separate CI job, not every PR |
| **Load** | CCU gates | Dedicated harness; publish JSON for site |

Rules:

1. Name tests `situation_expected_outcome` (readable in CI).
2. Default `cargo test` / Vitest: **no live network, no Steam, no real NW
   client**. Mark `#[ignore]` / `e2e` for those.
3. Every playable pillar ships an **e2e scenario** before “done.”
4. Web/dashboards: Vitest for pure logic; **Playwright** for critical user
   paths (login, privacy toggle, ban flow) — assert visible behaviour, not CSS
   class names ([Vitest component guidance](https://vitest.dev/guide/browser/component-testing.html)).
5. Coverage ratchets on **domain crates** only; do not farm % with trivial tests.
6. CI: `fmt` + `clippy -D warnings` + `cargo nextest` + doc check; e2e nightly
   or on label.

### What we delete

- Tests that mirror implementation line-by-line.
- Snapshots of unstable timestamps without redaction.
- “It compiles” tests with no assert on a failure mode.

---

## 0F. Funding — pay for servers, tokens, and labour (legally)

Servers, LLM tokens, and maintainer time are not free. We need a **funding
ladder** that starts honest and stays reversible if Amazon objects. Detail:
[ADR 0008](adr/0008-funding-ladder.md), [`LEGAL.md`](LEGAL.md) §Funding.

**Not legal advice.** Industry pattern (Facepunch / Bohemia-style where
allowed): cosmetics and access fees OK when publisher permits; **pay-to-win
and “donations” that are really sales with power** are the lawsuit magnets
(see e.g. emulator cases that mixed revenue with unauthorized servers).

| Tier | What we sell / accept | When | Risk notes |
| --- | --- | --- | --- |
| **F0** | Pure donations / Open Collective / Patreon **with no in-game perk** | As soon as public community exists | Lowest; still need entity + tax |
| **F1** | Merch, stickers, name-in-credits, Discord badge | After brand rename | No game power |
| **F2** | **Original cosmetics** we author (not Amazon assets): cloaks, titles, UI flair the client can show via our content packs | After content pipeline + counsel | Must be clearly ours; no ripped NW skins |
| **F3** | Optional supporter server slot / queue priority (cosmetic convenience) | After ops mature | Never combat power |
| **F4** | Hosting SaaS (“we run a world for your guild”) | After Docker/Linux stable | Separate ToS; still unofficial |
| **Blocked** | Selling Amazon PAKs, gold, gear, XP boosts, EAC bypasses | Never | |

Principles:

1. **Entity first** (nonprofit or company) before money moves at scale.
2. Ledger + transparency report for community funds.
3. Store SKUs are **first-party content**, never ripped assets.
4. Funding UI on the landing is opt-in and labelled unofficial.
5. If rights-holder demands stop: F2–F4 pause; F0 may remain as pure gift
   depending on counsel.

Playable spine still beats a store. Funding design runs **in parallel** so we
do not invent pay-to-win debt later.

---

## 1. Non‑negotiable principles

1. **Playable vertical before platform candy** — beat **2027-01-31** with a
   private playable loop; APIs/admin design early so we do not paint corners.
2. **Ontology before clever code** — purpose + authority + lifecycle for every
   concept.
3. **Domain never imports wire** — sim speaks types; codecs emit bytes.
   Apps must not be “byte archaeology” — that is prototype debt.
4. **Legal honesty** — no asset redistribution; unofficial; see §0A /
   [`LEGAL.md`](LEGAL.md).
5. **Security is a feature of every phase** — not a P99 add-on.
6. **Privacy default-deny for player data** — public sees what the owner allows.
7. **One command bus for all mutations** — web, in-game GM, CLI, bots, e2e.
8. **Ops never rides the tick** — `opsd` / `ops` subscribes; zero watchers ⇒
   zero cost.
9. **AI proposes; evidence promotes.**
10. **One winning behaviour; delete losers.**
11. **Python is scaffolding** — retired from the play path.
12. **No machine-specific paths in git** — clone + setup + migrate works.
13. **Steam install is sacred** — never delete/modify/hardlink destructively;
    private runtime is a copy/junction under project control.
14. **Containers are packaging of the same binaries** — behaviour identical in
    bare process, compose, and k8s.
15. **Falsifiable “better than Amazon”** — harness + hardware record required.
16. **Agent runs are durable and observed** — no overnight job without
    checkpoints + dashboard; no atlas promote without a verifier node.
17. **Docs are a product surface for agents** — taxonomy, link checks, no
    duplicated facts; speed of iteration depends on this as much as on Rust.

---

## 2. Priority spine: 100% playable server

Everything else serves this spine. “100% playable” for Azoth means a sustained
private session where a human (and later bots) can:

| Pillar | Player-visible | Server authority must own |
| --- | --- | --- |
| **Bootstrap** | Login → character → InGame, stable cable | sessions, tickets, state stream |
| **Movement** | WASD, correction, no desync kick loops | transform, validation |
| **Presence** | See other players | actor spawn/replicate/AOI |
| **Persistence** | Relog keeps character | character aggregate |
| **Gathering** | Nodes, tools, loot | node state, inventory grants |
| **Inventory / equip** | Bags, gear on body | items, slots, replication |
| **Progression** | XP, level, skills as client expects | xp rules, level gates |
| **Quests** | Accept, objectives, turn-in | quest state machine |
| **Combat PvE** | Hit mobs, die, respawn | damage, aggro, spawn tables |
| **Dungeons / instances** | Enter, complete, exit | instance lifecycle, loot tables |
| **Crafting / refining** | Stations, recipes | recipe validation, materials |
| **Economy basics** | Vendors / trading as scoped | prices, trades, ledger |
| **PvP** | Flagged combat, consequences | ruleset, safe zones, rewards |
| **Social minimum** | Party/friends as scoped | membership, invites |

Order inside the spine (do not scramble):

```text
P-play.0  Entry + soak stability
P-play.1  Movement authority + persistence
P-play.2  Presence (N players)
P-play.3  Inventory + gather + basic mobs
P-play.4  Quests + leveling
P-play.5  Dungeons / instances
P-play.6  Crafting + vendors
P-play.7  PvP ruleset
P-play.8  Polish (party, AH, …) as evidence demands
```

Platform tracks (ontology, security design, Dockerfiles, API stubs) **run in
parallel** as design/docs/scaffolding, but **gameplay acceptance** of each
P-play.* gate beats shipping rankings pages.

Each pillar requires: ontology concepts → wire layouts → domain rules →
replication → e2e scenario → retire Python path for that behaviour.

---

## 3. Absolute repository reorganization

### 3.1 Target tree (end state)

```text
Azoth/
  README.md                 # humans: clone → setup → play
  AGENTS.md                 # agents: ≤100 lines, pointers only
  STATUS.md                 # frontier ≤80 lines
  LICENSE*
  az.ps1 / az.py            # sole operator entry (thin)
  toolchain.lock.json

  server/                   # ONLY production runtime (Rust workspace)
    apps/
      channeld/             # platform HTTP
      regiond/              # discovery, tickets, placement
      worldd/               # authoritative sim + REP + DTLS
      opsd/                 # metrics fan-in, audit API, map, admin ingress
      botd/                 # optional: protocol bots / AI populace workers
    crates/
      azoth-model/          # domain types
      azoth-sim/            # tick + rules (no I/O)
      azoth-replica/        # snapshots, interest apply
      azoth-aoi/
      azoth-wire/           # codecs ONLY
      azoth-dtls/
      azoth-session/
      azoth-store/
      azoth-content/
      azoth-contract/       # exact client JSON
      azoth-http/
      azoth-observe/
      azoth-commands/       # typed admin/player commands + authz traits
      azoth-privacy/        # profile visibility policy evaluation
    xtask/

  platform/                 # player-facing non-sim (may start later)
    launcher/               # download, verify, patch, start
    web/                    # account, profile, rankings UI
    api/                    # OR fold public /v1 into channeld/opsd — decide at P8

  deploy/
    local/                  # compose for one-box
    k8s/                    # manifests / helm / agones fleets (future)
    caddy/
    certs/                  # local only, gitignored material

  research/
    atlas/                  # durable facts + ontology/
    docs/                   # focused RE/protocol refs
    sessions/               # gitignored raw captures

  reverse/
    tools/                  # static RE, Ghidra helpers
    probes/                 # Frida/live probes
    builds/                 # gitignored per-SHA corpora

  .agents/                  # skills, prompts, nested guidance
  docs/                     # plans + ARCHITECTURE + ADMIN
  site/                     # marketing / public roadmap (existing)

  private-client/           # gitignored runtime + profile
  .azoth/                   # gitignored tools, logs, state

  # REMOVED FROM RUNTIME PATH (after cutover)
  services/gateway|world    # deleted or archive/parity-only until retired
```

### 3.2 What “refactor absoluto” means in phases

| Reorg phase | Action | Gate |
| --- | --- | --- |
| **R0** | Freeze hot path; document actual vs target ownership | Port agent unblocked |
| **R1** | Knowledge OS: compact STATUS, ontology schema, indexes | Agents stop drowning |
| **R2** | Nested `AGENTS.md`; shorten root; skill split | Consistent AI behaviour |
| **R3** | Align `ARCHITECTURE.md` + README map to real `server/` apps | Docs match disk |
| **R4** | Domain lift in Rust (model/sim vs wire) | No offsets in `worldd` gameplay |
| **R5** | Introduce `azoth-commands` + `azoth-privacy` crates (API surface even if handlers stub) | Security model compilable |
| **R6** | `deploy/local` compose for channeld/regiond/worldd/opsd | Clone → compose up |
| **R7** | Retire Python play path | Rust-only `az.dev` |
| **R8** | `platform/launcher` + `platform/web` skeletons | Product entry |
| **R9** | `deploy/k8s` + world Fleet autoscaling | Dynamic worlds |
| **R10** | Archive historical Spanish/session noise; single docs index | Navigable |

**Rule:** no big-bang directory move mid-entry experiment. Moves happen behind
green parity tests for the plane being moved.

### 3.3 Clone-anywhere contract

A fresh Windows (and later Linux CI) checkout must:

1. `.\az.ps1 setup` → project-local Python/tools under `.azoth/` (checksum-locked).
2. Discover Steam install **read-only** OR accept `AZOTH_GAME_INSTALL`.
3. `az.py migrate` once on old machines; refuse overwrite conflicts.
4. `az.py mode private` + `az.py dev` (+ optional `docker compose`) starts
   stack with **zero** hardcoded user-profile paths in tracked files.
5. Logs/PIDs under `.azoth/state` and `.azoth/logs`.
6. Client runtime under `private-client/` (or documented `ProgramData` junction
   policy — one documented choice, not both ad hoc).
7. RE corpora under `reverse/builds/<full-sha256>/` only.

CI check: grep tracked tree for user home paths; fail on hit.

### 3.4 Dual-run during migration

```text
az.py dev --runtime python   # transitional
az.py dev --runtime rust     # default after cutover
az.py dev --runtime compose  # containers
```

One supervisor; one config schema; feature flags that select binaries — not
forked operator tribal knowledge.

---

## 4. Security architecture (first-class)

Security is not “HTTPS and hope.” It is layered controls with audit.

### 4.1 Threat model (condensed)

| Asset | Threat | Control |
| --- | --- | --- |
| Account | Credential stuffing, token theft | Argon2/bcrypt hashing, refresh rotation, device sessions, rate limits |
| Character / inventory / currency | Duping, packet forgery | Server authority; ignore client wealth claims |
| Admin commands | Privilege escalation | RBAC + mTLS/ops SSO + audit-before-apply |
| Private profile/stats | Scraping / doxxing | Privacy policy engine; default private |
| Launcher / patches | Supply chain | Ed25519/Sigstore-style signatures; hash pin; HTTPS only |
| World process | RCE via parse bugs | Bounded codecs; fuzz wire; no admin ports on world public NIC |
| DTLS / REP | Session hijack | Tickets one-time; IP/session binding policy; ban on anomaly |
| Secrets | Leak in git/logs | `.azoth` only; k8s Secrets; never log tokens |
| Containers | Escape / lateral | Non-root, read-only rootfs where possible, NetworkPolicy, PSS restricted |
| RE tooling | Accidental enablement of EAC analysis | Project rule: never attach while EAC uncertain; private launch ≠ proof |

### 4.2 Authn / authz

- **Players:** account credentials → short-lived access + refresh; world entry
  via **one-time ticket** from `regiond` (already in Rust plan).
- **Operators:** separate identity (SSO or ops accounts); roles
  `viewer|moderator|gm|economy|admin|owner`.
- **Services:** mesh or mTLS between channeld/regiond/worldd/opsd in cluster
  mode; shared secret only for local compose.
- **Commands:** every command declares required role + resource scope
  (realm/character/self).

### 4.3 Privacy profiles (player data)

Each account has privacy settings (extends the client’s privacy endpoint
requirement into a **real** Azoth policy):

| Field class | Default | Owner can set |
| --- | --- | --- |
| Online status | friends / private | public, friends, private |
| Character list | private | public, friends, private |
| Level / gear score | private | public, friends, private |
| Inventory / equipment detail | private | friends, private (**not** public by default; optional later) |
| Stats / rankings participation | opt-in | exclude from leaderboards |
| Location (map API) | never public | ops-only unless spectate consent |

**API rule:** `GET /v1/players/{id}/…` evaluates `azoth-privacy` **before**
read-model fetch. Unauthorized → `404` (no existence leak) or `403` per policy
table. Admins bypass with audit.

Rankings only include characters with `rankings: opt-in`.

### 4.4 Launcher security

- Patches and client builds addressed by **content hash + signature**.
- Launcher verifies signature before apply; refuses downgrade without explicit
  channel.
- Update channel: `stable|beta|dev`; config from Azoth CDN, not attacker LAN.
- Local game files: write only under Azoth-managed runtime dirs.
- No silent elevation; document Admin needs for host routing separately
  (`docs/ADMIN.md`).

### 4.5 World / wire security

- Authoritative validation on movement, inventory, combat, trades.
- Rate limits per session; disconnect + audit on impossible claims.
- Economy: append-only ledger (Rust plan §9.5); grants are commands.
- Fuzz `azoth-wire` decode paths in CI.
- Admin / metrics listeners bound to private networks in production.

### 4.6 Secrets & supply chain

- `toolchain.lock.json` pins hashes (already).
- Container images: immutable tags by digest; never `:latest` in prod.
- SBOM + dependency audit in CI when publishing images.
- Research captures with secrets stay in `research/sessions/` (gitignored).

---

## 5. Knowledge OS & ontology (Track A — still highest leverage for AI)

See prior plan sections; summarized and hardened:

- `research/atlas/ontology/` with schema, indexes, one file per concept.
- Confidence ladder: `bytes → layout → semantics → authoritative`.
- STATUS ≤ 80 lines; journals elsewhere.
- Mechanical `xtask`/`az.py atlas check` gates.
- Competency questions including privacy and admin command effects.
- AI decomp pipeline writes only to `reverse/builds/<sha>/ai/`; promotion is
  human/verifier.

Entrails goal: **exhaust the client** (types, endpoints, systems, content ids)
into ontology stubs, then promote along the playable spine — not a random wiki.

---

## 6. Runtime architecture (Amazon-grade layering)

```text
azoth-model / azoth-sim     domain rules, tick
azoth-aoi / azoth-replica   interest → view models
azoth-wire                  bytes in/out
azoth-dtls / azoth-session  transport
azoth-store                 identity + world DBs
azoth-content               datasheets / validation
azoth-commands              typed mutations + RBAC hooks
azoth-privacy               visibility decisions
azoth-observe               metrics/log/audit emit
apps: channeld regiond worldd opsd [botd]
```

HTTP planes use Axum/Tokio production patterns: shared pools, timeouts,
concurrency limits, `spawn_blocking` for SQLite, graceful shutdown.

World: fixed 50 Hz tick; network thread ≠ tick; bounded channels; map/admin
off the hot path (`PLAN-backend-rust.md` §8, §12–14).

---

## 7. Deploy: local → Docker → Kubernetes

### 7.1 Stage L — bare process (today)

`az.py dev` supervises Caddy + channeld + regiond + worldd (+ opsd when born).
Identical config schema to containers.

### 7.2 Stage D — Docker Compose (one box / small team)

```text
deploy/local/compose.yml
  caddy
  channeld
  regiond
  worldd          # one or N scaled manually
  opsd
  postgres-identity
  postgres-world  # or sqlite volume for tiny setups
  prometheus
  grafana
```

Rules:

- Same env/config as bare metal.
- Non-root users; read-only where possible; secrets via compose secrets.
- UDP host ports published for DTLS worlds.
- Healthchecks on HTTP `/healthz` and world admin localhost only.

### 7.3 Stage K — Kubernetes + dynamic worlds

| Workload | k8s shape | Scale trigger |
| --- | --- | --- |
| channeld | Deployment + HPA (CPU/RPS) | HTTP load |
| regiond | Deployment + HPA | placement QPS |
| opsd | Deployment | ops traffic (isolated) |
| worldd | **GameServer Fleet** (Agones or equivalent) | Ready buffer / allocations |
| DB | managed Postgres or operator | not app HPA |

World scaling pattern (industry: Agones FleetAutoscaler Buffer):

- Keep a **buffer of Ready** world pods.
- Allocate a world on demand (realm/region/map).
- Packed scheduling with cluster autoscaler, or Distributed on bare metal.
- Separate node pools: control plane / platform vs game servers vs metrics.
- NetworkPolicies: players → world DTLS + channel HTTPS only; ops network →
  opsd; worlds never expose admin to public.

**Multi-cluster** later for fault domains; not day one.

### 7.4 Config & discovery

- Channel document remains **generated from live registry** (Rust plan §4),
  not a checked-in lie.
- Worlds register heartbeat → regiond → channel document + metrics labels.
- Rolling updates: drain world (no new tickets) → empty → terminate.

---

## 8. Launcher, web, public API, privacy

### 8.1 Launcher

- Account login; realm list; download/verify/update runtime; start client.
- Owns patch channel security (§4.4).
- Passes bootstrap URLs for Azoth (sovereignty path).

### 8.2 Web

- Register/login; account security (sessions, 2FA later).
- Profile editor + **privacy toggles**.
- Character overview (as allowed).
- Rankings (opt-in only).
- Ban appeals / support stubs later.

### 8.3 Public API `/v1`

Read models with privacy evaluation. Mutations for “self” (e.g. privacy
settings) allowed; economy mutations are **never** public — admin/command bus
only.

Online counts: aggregate gauges from heartbeats (per world → region → realm).

---

## 9. Administration & real-time grants

Single command bus (`azoth-commands`), audited before apply:

Kick, Ban, Unban, MoveCharacterServer, GrantCurrency, GrantItem, SetRole,
Teleport, Spawn/Despawn, BotSpawn/Stop/Restart, Announce, …

Surfaces: opsd HTTP, in-game GM panel (same commands), CLI, e2e.

Live grants: if online → world apply → replicate → client sees; else persist.

Map: authoritative snapshot feed via opsd (Rust plan §13).

---

## 10. Playable systems architecture (content of the spine)

For each pillar in §2, the design template is identical:

```text
ontology concepts
  → wire/message layouts (evidence)
  → domain tables/rules in azoth-sim
  → persistence fields in store
  → replication dirty sets
  → admin commands if GM-visible
  → e2e bot scenario
  → metrics (counts, failures)
```

### 10.1 Examples of domain ownership

| System | Sim owns | Content owns | Wire owns |
| --- | --- | --- | --- |
| Gather | node respawn, tool reqs, loot rolls | node defs, loot tables | grant/inventory msgs |
| Quest | steps, flags, turn-in | quest defs | objective updates |
| Dungeon | instance id, wipe, lockout | encounter tables | presence inside instance |
| PvP | flag rules, damage mods | zone flags | combat replicate |
| Level | XP curve application | curve tables | progress replicate |

New Azoth-only content later = content + maybe client capability — never a
silent wire break for vanilla clients still supported.

---

## 11. Reverse engineering & decompilation (platform capability)

Not a side hobby — it feeds ontology and playable gates.

| Layer | Location | Rule |
| --- | --- | --- |
| Tools | `reverse/tools` | versioned via setup lock |
| Probes | `reverse/probes` | named; EAC uncertainty ⇒ stop |
| Corpora | `reverse/builds/<sha256>/` | ignored; regenerable |
| AI annotate | `…/ai/` | candidates only |
| Confirmed | `research/atlas/` | evidence required |
| Campaign | `az.py re campaign` | screen/phase map |

Headless Ghidra → compact.json → LLM → verify → promote. Live unmarshal for
runtime-built descriptors (presence). Full SHA-256 identity always.

Launcher + patch RE: treat official updater behaviours as ontology
`endpoint.*` / `flow.patch.*` when building Azoth’s own updater.

---

## 12. Agentic factory (LangGraph-class: measured, durable, overnight)

Chat sessions alone cannot win a multi-year MMO reverse-and-rebuild race.
Azoth needs an **agent factory**: typed workflows, durable state, human gates,
and full observability — the same ideas as LangGraph checkpointers + LangSmith
traces, implemented as Azoth-owned infrastructure (not a hard dependency on
any one vendor).

### 12.1 Why this is the competitive weapon

| Without factory | With factory |
| --- | --- |
| Agents re-read 3k-line STATUS and contradict each other | Frontier ≤80 lines + ontology; agents load only the subgraph they need |
| Overnight RE dies at hour 3; morning restart from zero | Checkpoint every super-step; resume `thread_id` |
| “The agent did something” | Dashboard: node, tool, cost, latency, promote/reject rate |
| Docs rot; humans fear large refactors | Doc-rewrite graphs with verifiers + link checkers |
| Competitors ship vibes | Azoth ships evidence + e2e on a cadence |

### 12.2 Execution model (ultra-measured)

Borrow the production patterns, keep ownership in-repo:

```text
azoth-agents/   (future package; name TBD)
  graphs/           # deterministic DAGs + agentic nodes
  checkpointer/     # Postgres (or sqlite local) per thread_id
  store/            # cross-thread memory: preferences, run bookmarks
  runners/          # worker pool; lease/heartbeat; crash resume
  traces/           # every node/tool/LLM call → observability sink
  gates/            # human-in-the-loop interrupt points
```

| Concept | Azoth meaning |
| --- | --- |
| **Graph** | Named workflow: `ontology-extract`, `ai-decomp-batch`, `parity-nightly`, `docs-rewrite`, `e2e-pack`, `play-spine-implement` |
| **Super-step / node** | One durable unit (decompile 50 fns, promote 20 stubs, run e2e suite) |
| **Checkpoint** | Persist state after each node; crash ⇒ resume, do not redo paid work |
| **Thread id** | One overnight job identity; dashboard filters by thread |
| **Interrupt** | Pause for human: promote candidates, approve admin schema, merge doc moves |
| **Time travel** | Replay/fork from checkpoint to debug a bad promote |
| **Eval set** | Golden tasks (known VA → expected concept; known e2e) scored offline |
| **Durability mode** | Sync checkpoint before irreversible side effects (git write, atlas promote, ban command in ops graphs) |

**Hard rule:** graphs that **promote atlas facts** or **mutate git** must
checkpoint *before* the write and require a verifier node (or human interrupt).
LLM nodes never write `confidence: verified` themselves.

### 12.3 Instruction stack (how agents load context)

| Layer | Role | Size |
| --- | --- | --- |
| Root `AGENTS.md` | Invariants + pointers | ≤ 100 lines |
| Nested `AGENTS.md` | Package-local commands/risks | shorter than root |
| Skills | Progressive disclosure + `paths:` | SKILL.md ≤ ~500 lines |
| Ontology / atlas | Facts | retrieved by uid, not pasted wholesale |
| Graph state | Run-local memory | checkpointer |
| STATUS | One frontier | ≤ 80 lines |

Anti-pattern: stuffing the whole repo narrative into every prompt. That is how
agentic projects drown and competitors with smaller, clearer loops pull ahead.

### 12.4 Agent monitoring dashboard

First-class ops surface (can live under `opsd` or `site` admin; later both):

| Panel | Shows |
| --- | --- |
| Active threads | running / paused / failed / completed |
| Timeline | node sequence, duration, retries |
| Cost | tokens / tool time / Ghidra batch time |
| Quality | promote vs reject; e2e pass rate; ontology check failures |
| Queue | overnight schedule (cron of graphs) |
| Leases | which worker owns which thread; stale lease alerts |
| Artifacts | links to compact.json, candidate diffs, PR drafts |

Traces must answer: *which node*, *which tool*, *which evidence ref*, *why
stopped*. Without that, long runs are expensive superstition.

### 12.5 Overnight / all-day job catalog (examples)

| Graph | Cadence | Output |
| --- | --- | --- |
| `ai-decomp-batch` | nightly | candidates under `reverse/builds/<sha>/ai/` |
| `ontology-stub-fill` | nightly | new `unknown` concepts from type registry |
| `ontology-promote-queue` | on interrupt | human/verifier promotions |
| `parity-wire` | on Rust change | fixture diffs |
| `e2e-smoke` | hourly/CI | L2/L3 results |
| `docs-link-check` | nightly | broken refs report |
| `status-compact` | weekly | propose STATUS shrink + journal move |
| `roadmap-sync` | on milestone | patch `roadmap-full.ts` + evidence checklist |
| `capacity-soak` | weekly | tick p99 artifact |

### 12.6 Skills to add

`azoth-ontology`, `azoth-parity`, `azoth-e2e`, `azoth-ops`, `azoth-security`,
`azoth-ai-decomp`, `azoth-agent-factory` (Orca/T3+Pi+Gentle binding — see
§14A), `azoth-docs-rewrite`, `azoth-roadmap-sync` — plus existing
server/RE/live.

Roles: Extractor · Analyst · Verifier · Implementer · Librarian · Security ·
E2E · **Orchestrator** (Orca/T3 only schedules; does not promote facts alone).

**Concrete machine binding** (2 workers, DeepSeek-flash, Gentle, Orca|T3) is
normative in **§14A** — follow that section when running overnight loops.

---

## 13. Documentation absolute reorg (everything readable again)

Today knowledge is fragmented across STATUS novels, ROADMAP, ARCHITECTURE,
multiple PLAN_*, research/docs, archive Spanish, prompts, and chat. That
**kills agentic speed**. The refactor is not “add another markdown”; it is a
**doc OS**.

### 13.1 Target doc taxonomy

```text
docs/
  INDEX.md                 # only index
  ARCHITECTURE.md          # thin; links out
  SECURITY.md              # threat + privacy (P1)
  ADMIN.md                 # host routing (exists)
  PLAN-master-platform.md  # THIS — product/reorg/agent/site north star
  PLAN-backend-rust.md     # runtime mechanics
  ROADMAP.md               # near-term engineering order (internal)
  journal/                 # archived STATUS diaries by month
  runbooks/                # how to operate compose/k8s/agents
  adr/                     # Architecture Decision Records (one decision each)

research/
  atlas/                   # ONLY durable facts + ontology
  docs/                    # focused protocol deep-dives (linked from ontology)
  sessions/                # gitignored raw

.agents/                   # skills + prompts (not product docs)

site/                      # public display only (see §14)
```

### 13.2 Rules

- One fact → one atlas/ontology home; docs **link**, they do not copy.
- ADR for irreversible choices (SQLite vs Postgres prod, Agones vs custom,
  LangGraph vendor vs in-house runner).
- Archive, do not delete, historical Spanish/session material under
  `docs/archive/` (already started).
- Mechanical: `az.py doc check` / xtask — broken links fail; STATUS line budget
  fails; roadmap `done` without evidence id fails.
- Doc-rewrite **graph** moves files; humans approve the migration map once.

### 13.3 Near-term doc rewrite batches (when authorized)

1. Compact STATUS → journal.  
2. Ontology schema + seed.  
3. Collapse overlapping PLAN/ARCHITECTURE pointers (no contradictory “Python
   is the server”).  
4. Nested AGENTS.  
5. SECURITY.md + privacy matrix.  
6. Runbooks for agent factory + compose.  
7. Public roadmap sync process automated from internal milestones.

---

## 14. Roadmap system v2 (replace the replay-era public roadmap)

### 14.0 Diagnosis of today’s public roadmap

`site/src/data/roadmap-full.ts` is large, facet/PAK-driven, and still framed
around the **Python/replay prototype era** (tick evidence citing `rep.py`,
“streaming already works (replay proves it)”, Phase A session contract as if
Rust authority were not the product). It is valuable as a **content inventory**
of client surfaces, but it is the wrong shape for:

- communicating the Rust authoritative platform,
- the playable spine in this master plan,
- agent factory / security / Docker / open-source phases,
- a living public narrative that updates without becoming a 1000-item novel.

**Decision:** treat the current `roadmap-full.ts` as **v1 archive input** (mine
for item ids and evidence), then ship **roadmap v2** generated from a smaller
scalable source of truth.

### 14.1 Three-layer roadmap (scalable)

```text
Layer 1 — GATES (few, stable)
  docs/PLAN-master-platform.md §18 phases + play spine
  Each gate: id, acceptance, evidence refs, state

Layer 2 — WORK GRAPH (many, machine-friendly)
  research/atlas/work/ or .azoth/work/ (generated OK)
  nodes: issues, agent tasks, dependsOn[], owner, harness graph id
  NOT shown raw on the landing page

Layer 3 — PUBLIC DISPLAY (curated)
  site/src/data/roadmap-v2.ts → roadmap.json
  Only gates + a handful of active epics per era
  Evidence + captures required for `done`
```

| Layer | Who edits | Size target | Tooling |
| --- | --- | --- | --- |
| Gates | humans + ADR | ~20–40 | this plan + `docs/ROADMAP.md` |
| Work graph | agents + GH issues | thousands OK | JSON/YAML + `az.py work` |
| Public | sync script from closed gates | ≤ ~12 groups, ≤ ~80 visible items | `gen-roadmap.mjs` |

**Rule:** public never lists every facet codec. Public lists eras:
Foundation → Playable loop → Ops/platform → Scale/open-source → Extensions.

### 14.2 Proposed public eras (v2 groups — replace A–J display)

| Era | Maps to | Public goal (one sentence) |
| --- | --- | --- |
| **E0 Foundation** | P0–P2 | Authoritative Rust entry: InGame, domain lift, knowledge OS |
| **E1 Presence & persist** | P3–P4 | Multiplayer visibility + durable characters |
| **E2 Playable loop** | P5–P9 | Gather, combat, quests, level, dungeons, craft, PvP |
| **E3 Studio ops** | P10–P11, P15 | Admin bus, map, privacy API, GM panel |
| **E4 Ship & scale** | P12–P14, P16, P20 | Compose/k8s, launcher, capacity gates |
| **E5 Open & extend** | P14b, P17–P19, P21 | Public site, GitHub community, content, AI populace |

v1 items (combat facets, settlements, …) become **work-graph backlog** linked
from E2+, not a wall of `planned` on the homepage.

Migration procedure (when authorized):

1. Freeze v1 → `site/src/data/roadmap-v1-archive.ts` (no longer served).  
2. Author v2 groups/items from eras above; carry forward only `done` with
   still-valid evidence; re-state active items in Rust/authority language.  
3. `gen-roadmap.mjs` reads v2 only.  
4. Agent graph `roadmap-sync` updates item state when a gate’s acceptance file
   appears under `research/atlas/evidence/`.

### 14.3 Two roadmaps (do not merge meanings)

| Surface | Canonical source | Audience | Updates when |
| --- | --- | --- | --- |
| **Internal gates** | this plan §18 + short `docs/ROADMAP.md` | builders/agents | every experiment |
| **Work graph** | issues + `work/*.json` | agents/CI | continuously |
| **Public** | `roadmap-v2.ts` → `roadmap.json` | community/competitors | milestone + evidence only |

### 14.4 Site evolution (player landing)

| Stage | What visitors see |
| --- | --- |
| **Now** | Vision, **roadmap v2**, live badge, verification ethos |
| **S1** | Auto-synced gates; published harness tick charts (cited hardware) |
| **S2** | Account register/login |
| **S3** | Character analyzer (privacy-gated), opt-in leaderboards |
| **S4** | Realm/region status: online, tick p50/p99, version, incidents |
| **S5** | Launcher CTA, patch notes, full app shell |

### 14.5 Agent dashboard vs public site

- **Agent dashboard** — private; Orca/T3 threads, Pi sessions, promote rates.  
- **Public site** — sanitized fleet + roadmap v2 + player data.  
Never expose prompts, tickets, or raw captures publicly.

---

## 14A. Agentic stack for *this* machine (Pi + Gentle + Orca/T3 + DeepSeek)

You typically run **2 concurrent workers**, **DeepSeek-v4.1-flash** via **Pi
harness**, **Gentle AI** for Organic Driven Development, and **Orca or T3** as
the outer orchestrator. The plan locks a topology that matches that budget
instead of fantasizing 20 parallel Claudes.

### 14A.1 Recommended topology (2 slots)

```text
┌─────────────────────────────────────────────────────────┐
│ ORCHESTRATOR (1 of 2 slots, or a thin always-on pane)   │
│  Orca Run+Tasks  OR  T3 orchestrator MCP                │
│  Owns: DAG, gates, heartbeats, “what is next”           │
│  Does NOT bulk-edit game code                           │
└─────────────┬───────────────────────────────────────────┘
              │ worker-start / delegate_task (max 1–2)
              ▼
┌─────────────────────────────────────────────────────────┐
│ WORKER slot(s) — Pi + Gentle AI + DeepSeek-v4.1-flash   │
│  Isolated git worktree (Orca) or T3 thread              │
│  Gentle: explore → track → apply → verify               │
│  Pi durable session: resume after crash/quit            │
│  Subagents only for named Gentle reasons                │
└─────────────────────────────────────────────────────────┘
```

With **exactly 2 concurrencies**:

| Mode | Slot A | Slot B |
| --- | --- | --- |
| **Default** | Orchestrator (Orca/T3) | One Pi+Gentle worker on a worktree |
| **Fan-out** | Worker “implement” | Worker “verify” (disjoint paths) — orchestrator is human or paused |
| **Overnight** | Orchestrator cron wakes worker | Second worker only if tasks are independent (e.g. ontology stub vs decomp batch) |

Never run two writers on the **same** worktree (Pi durable-subagents and Orca
both warn: writer lock / worktree isolation).

### 14A.2 What each tool is for (research-backed)

| Tool | Role in Azoth | Do not use it for |
| --- | --- | --- |
| **[Orca](https://www.onorca.dev/docs/cli/orchestration)** | Run/Task/Dispatch, worktrees, `worker_done`, decision gates, heartbeats, supervised overnight loops | Replacing ontology or CI |
| **[T3 Code](https://t3.codes/)** | Cross-provider delegate, lineage UI, mobile control, resume-limited threads | Being the only source of project rules |
| **[Pi](https://github.com/earendil-works/pi)** + durable harness | Long DeepSeek sessions, lanes, crash resume, RPC/automation | Unbounded context without Gentle backstop |
| **[DeepSeek harness](https://github.com/deepseek-ai/deepseek-harness)** | Durable turn/step log, parallel tool caps, resume sessions | Promoting atlas without verifier |
| **[Gentle AI](https://github.com/gentleman-programming/gentle-ai)** | ODD: authorize → explore → ask → classify → track → implement → verify; **delegate only with a named reason** | Spawning subagents by file count |

### 14A.3 How long agents survive (do this or they die)

Patterns from Pi durable / DeepSeek loop / Orca / Gentle / general durable-agent
literature:

1. **Checkpoint at task boundaries**, not every token — goal, next action,
   evidence paths, budget, operation ids.  
2. **Worktrees** for any parallel writer (Orca native).  
3. **Heartbeats** during long work (`orca orchestration` heartbeat /
   Pi wake jobs).  
4. **One `worker_done` per dispatch** with outcome + files touched.  
5. **Human/decision gates** for atlas promote, SECURITY, public roadmap `done`.  
6. **Context backstop** (Gentle ~150k): hand next unit to a fresh worker; do
   not keep one infinite chat that “knows the whole STATUS novel.”  
7. **Verifier ≠ author** for high-risk (wire, economy, privacy, auth).  
8. **Idempotent external effects** — tickets, DB migrations, bans: operation
   log before apply; resume must not double-grant.  
9. **Eval set** — golden tasks scored offline so flash models do not silently
   regress.  
10. **Repo rules in nested AGENTS + ontology**, not pasted into every prompt.

### 14A.4 Gentle delegation policy (Azoth binding)

Parent stays coordinator. Delegate only when:

- **Exploration** — more than one read batch / ~5 lookups → explore subagent,
  return ≤~2k tokens with `path:line`.  
- **Parallel writers** — ≥2 independent units, **disjoint** edit surfaces,
  each heavy enough to justify cold start.  
- **Context backstop** — parent too large → next bounded unit to fresh Pi.  
- **Independent verifier** — wire/security/economy/privacy changes.

Otherwise: **inline**. File count alone never triggers a subagent.

### 14A.5 Overnight recipe (Orca-shaped)

```text
1. run-create --objective "Azoth overnight: <gate id>"
2. task-create DAG: extract → (optional) implement → verify → handoff-doc
3. worker-start --worktree new-child --agent pi   # DeepSeek flash via Pi
4. Worker loads: AGENTS.md + skill + gate acceptance + ontology uids only
5. Heartbeat every N minutes; ask() for product decisions
6. worker_done succeeded|failed + evidence paths
7. Orchestrator: if succeeded and gate says promote → decision gate for human
8. Morning: dashboard shows thread; human resolves gates; merge PR
```

Same DAG can be expressed in T3 via `delegate_task` + wait/mailbox if Orca is
not the outer shell that night.

### 14A.6 Model placement

| Work | Model / harness |
| --- | --- |
| Bulk decomp annotate, ontology stubs, link checks | DeepSeek-v4.1-flash + Pi (cheap, long) |
| Wire layout / security / economy design | Stronger model via T3/Orca handoff when needed |
| Orchestrator routing | Small/fast or human; must not “creatively” edit sim |
| PR review bot (future GH) | Flash for triage; stronger for high-risk labels |

---

## 14B. Open GitHub (when the server is stable)

**Gate to go public:** playable foundation green (at least P2–P3 acceptance),
secrets scrubbed, `docs/SECURITY` + CONTRIBUTING, CI required, no private
captures in git history.

### 14B.1 Community loop (agentic + human)

```text
Issue opened
  → triage workflow (labels: type, size, risk, area)
  → duplicate detect
  → if `good-first-agent` → optional implement bot on fork branch
PR opened
  → path filters → lint/test/ontology-check/parity
  → risk classifier → depth of review
  → agent review comment (read-only on fork PRs)
  → label panel-review → human or multi-persona verdict
  → merge only with required checks + maintainer approval
```

Patterns to copy: label-gated agent workflows (cost control), risk-aware PR
harness, fork-safe `pull_request_target` with **no checkout of untrusted code
into writey jobs**, auto-merge only for low-risk trusted bots.

### 14B.2 Repo automation checklist

- [ ] `CONTRIBUTING.md` + issue/PR templates  
- [ ] CODEOWNERS for `azoth-wire`, `azoth-privacy`, `deploy/`, atlas promote  
- [ ] Required CI: `xtask check`, ontology, unit, e2e-smoke  
- [ ] Label taxonomy: `area:*`, `risk:low|high`, `gate:P*`, `agent:ok`  
- [ ] Stale-bot + security advisory process  
- [ ] DCO or CLA if needed  
- [ ] Public roadmap v2 synced on release tags  
- [ ] Branch protection: no direct push to main  

### 14B.3 What agents may do unattended vs not

| Allowed unattended | Never unattended |
| --- | --- |
| Triage labels, ask clarifying questions | Merge high-risk PRs |
| Draft PR from labeled issue on bot branch | Promote atlas to `verified` |
| Run tests / post review comments | Change privacy defaults / ban logic without human |
| Update work-graph JSON | Publish “done” on public roadmap without evidence |

---

## 15. E2E, bots, AI populace

Pyramid L0–L5 (unit → protocol bot → scenarios → soak → rare real client).

Scenarios track the playable spine (gather, quest turn-in, dungeon complete,
PvP flag interaction).

AI populace (late): same protocol; ops-controlled spawn/stop/restart;
personalities as configs; world does not trust “bot” flag for rules.

---

## 16. Observability (game + agents)

**Game plane:** metrics / logs / audit split (`PLAN-backend-rust.md` §12).
Grafana provisioned from repo. Map feed. Alert on tick overrun, world down,
cert expiry, privacy API error spikes, admin command failures.

**Agent plane:** separate dashboards (§12.4) — thread health, node latency,
cost, promote/reject, stale leases. Do not mix agent-token metrics into
player-facing cardinality.

---

## 17. Client sovereignty & future improvements

1. Inventory all AWS dependencies in ontology.  
2. Launcher + remote-config point to Azoth.  
3. Patches per build hash.  
4. Capability bits for extensions.  
5. Protocol optimizations / UX only after playable + secure vanilla path.

---

## 18. Master phase map (everything, ordered)

Dependencies flow downward; parallel tracks marked.

| Phase | Name | Parallel OK? | Done when |
| --- | --- | --- | --- |
| **P0** | Knowledge OS + STATUS compact + ontology schema + **doc taxonomy lock** | yes beside port | checks green; 20 concepts; INDEX taxonomy live |
| **P0r** | **Public roadmap v2** (archive v1; eras E0–E5; gen from gates) | yes | landing serves v2; no replay-framed active items |
| **P0L** | **Legal + collab + rename track** | yes | LEGAL/NOTICE/CONTRIBUTING; ADRs 0003–0006; rename shortlist locked |
| **P0$** | **Funding ladder design** (F0–F4; no pay-to-win) | yes | ADR 0008 + LEGAL §Funding; entity checklist |
| **P0dx** | **`az` DX**: setup profiles, doctor, logs, gitignore audit, contributor loop | yes | `setup --core` default; `az doctor`; Linux server path documented |
| **P0t** | **Testing doctrine + first real scenario harness** | yes | ADR 0007; nextest; one e2e entry scenario; Criterion stub |
| **P0c** | **Crypto/link hygiene** (`azoth-dtls` + one Windows OpenSSL path) | yes | documented toolchain; no MinGW/MSVC mix; harness stub |
| **P0b** | **Agent factory MVP** on Orca/T3+Pi+Gentle (1 overnight DAG + resume) | yes | kill worker → resume; `worker_done` contract; dashboard/thread visible |
| **P1** | Security & privacy **design** locked | yes | `cmd.*` + privacy concepts + SECURITY.md |
| **P2** | Domain lift + entry soak (play.0–1) — **MMO-shaped code, not byte soup** | limited | InGame stable; model types in ladder; spawn seed retirement plan |
| **P3** | Presence (play.2) | | N bots see each other |
| **P4** | Persist + inventory foundation | | relog; item aggregate |
| **P5** | Gather + basic combat PvE | | e2e gather/kill |
| **P6** | Quests + leveling | | e2e quest + level-up |
| **P7** | Dungeons | | instance enter/complete |
| **P8** | Crafting/vendors + economy ledger | | e2e craft |
| **P9** | PvP ruleset | | flagged combat e2e |
| **P10** | Command bus + opsd + Grafana + map | with P4+ | kick/ban/grant live audited |
| **P11** | Public API + privacy enforcement | after P4 | unauthorized reads blocked |
| **P12** | Docker compose clone path | after P2 binaries | compose up playable |
| **P13** | Kill Python runtime | after feature parity | rust-only play path |
| **P14** | Launcher + signed patches + web accounts | after P11–13 | download→play |
| **P14b** | **Public landing S2–S4** (auth, profiles, status/tick charts, leaderboards opt-in) | with P11+ | privacy-gated pages live |
| **P15** | In-game GM panel | after P10 + client hook | same commands |
| **P16** | k8s + world Fleet autoscaling | after P12–13 | buffer scale test |
| **P17** | Client sovereignty (no AWS) | after P14 | play path Azoth-only |
| **P18** | Content packs + extensions | after P9+ | authored content live |
| **P19** | AI populace | after P3+P10+P12 | ops-managed personalities |
| **P20** | Capacity gate 2.5k / chase 10k | after AOI+P3 | harness record published |
| **P21** | Full doc rewrite complete (archive noise, ADR set, runbooks) | ongoing from P0 | link-check green; no STATUS novel |
| **P22** | **Open GitHub** (CI, templates, agent triage/review, branch protection) | after P2–P3 + scrub | external PRs merge under required checks |

**Explicit:** Playable P5–P9 acceptance is not blocked by a pretty website.
P0/P0r/P0b/P1 run **in parallel** with the port so iteration speed compounds.
Public roadmap updates only on evidenced milestones (`site/` rules).
Open source (P22) waits for a stable authoritative slice — not for “everything.”

---

## 19. Absolute refactor workstreams (analysis checklist)

Use this as the audit backlog before moving files:

### 19.1 Knowledge & docs

- [x] Compact STATUS; archive journal  
- [x] Ontology schema + indexes + seed concepts  
- [x] Lock doc taxonomy (§13); rewrite INDEX  
- [x] ADR folder for irreversible decisions  
- [x] Deduplicate ROADMAP / ARCHITECTURE / plans (pointers only)  
- [x] Nested AGENTS + skill progressive disclosure  
- [x] Remove contradictory “Python is the server” language  
- [x] **Roadmap v2:** archive v1; eras E0–E5; sync script from gates  
- [ ] Work-graph store for facet/content backlog (not on landing)  
- [x] LEGAL / NOTICE / CONTRIBUTING drafts (P0L)  
- [x] Rename + binary-name ADRs (0005, 0006)  
- [x] DTLS/OpenSSL ADR (0004)  
- [x] Testing + funding ADRs (0007, 0008)  
- [x] `az setup` profiles (`core`/`re`/`all`) + `az doctor` + purge  
- [x] `.gitignore` audit (secrets, targets, playwright, .env)  
- [x] Contributor loop runbook (dev / RE / e2e / logs)  
- [x] Linux Dockerfile for world+region+channel + `deploy/local/compose.yml`  
- [x] Archive noisy docs (`docs/archive/…`); delete migration-map indirection  
- [x] `platform/` launcher+web skeletons  
- [x] `scripts/check-paths.py`  
- [x] ADR 0009 native `az.dev` vs Compose  
- [x] Agentic boot-naming campaign runbook + prompt  

### 19.1b Domain Rust (feel like a real MMO)

- [x] `azoth-model` stub + ladder `ontology_uid`  
- [x] `azoth-commands` + `azoth-privacy` called from worldd/regiond  
- [ ] Presence layouts → ontology `layout`  
- [ ] Compose spawn from domain snapshot (retire capture seed)  
- [ ] `azoth-sim` / `azoth-replica` crates when presence needs AOI  
- [ ] Ban new raw offset constants in `apps/*` (xtask lint)  

### 19.2 Agentic factory (Pi + Gentle + Orca/T3)

- [x] `.agents/README.md` catalog + ontology/knowledge skills + boot/world prompts  
- [x] Document binding: 2-slot topology (ADR 0001 / §14A.1)  
- [x] Overnight runbook draft (`docs/runbooks/agent-overnight.md`)  
- [ ] Orca Run recipe + `worker_done` / heartbeat / ask contract (live demo)  
- [ ] Pi durable session + Gentle ODD for DeepSeek-flash workers  
- [ ] Writer lock / worktree isolation enforced  
- [ ] First overnight DAG + resume-after-kill demo  
- [ ] Verifier≠author for wire/privacy  
- [ ] Eval set for flash-model regression  
- [ ] Agent dashboard (threads/cost/promote)  
- [ ] Optional T3 delegate path for stronger-model handoff  

### 19.2b Open GitHub

- [ ] CONTRIBUTING + templates + CODEOWNERS  
- [ ] Required CI + risk labels  
- [ ] Triage / review agent workflows (fork-safe)  
- [ ] Branch protection; no unattended high-risk merge  
- [ ] History scrub before public  

### 19.3 Code layout

- [ ] Map every Python gateway/world module → Rust owner or retirement  
- [ ] Split wire vs sim vs commands vs privacy  
- [ ] Ensure `opsd` boundary exists before admin features sprawl into worldd  
- [ ] xtask line/env/ontology gates  

### 19.4 Security & privacy

- [x] Threat model doc in `docs/SECURITY.md` (draft)  
- [ ] Privacy matrix in ontology  
- [ ] Secret scan + path scan in CI  
- [ ] Admin audit schema  

### 19.4b Testing & benches

- [x] nextest.toml present (`cargo nextest run`)  
- [x] Scenario tests for ticket/RBAC/privacy failure modes  
- [x] `az test e2e entry` offline stub  
- [ ] Criterion benches for wire + tick hot paths  
- [ ] Playwright smoke for landing critical paths  
- [ ] Ban trivial unit-test PRs that add no failure-mode coverage  

### 19.5 Deploy

- [ ] One config schema  
- [x] Dockerfile per app (Linux OpenSSL)  
- [x] compose local  
- [ ] k8s/Agones sketches (no need to run until P16)  

### 19.5b Funding

- [ ] Entity + payment provider shortlist  
- [ ] F0 donation page (no perks)  
- [ ] F1 merch / credits  
- [ ] F2 original cosmetic pipeline (never Amazon assets)  
- [ ] Transparency report template  

### 19.6 Playable

- [ ] Per-pillar ontology + e2e list  
- [ ] Content id stability rules  
- [ ] Instance/dungeon lifecycle design  

### 19.7 Client, launcher, site

- [ ] Patch signature design  
- [ ] Endpoint cutover inventory  
- [ ] GM UI hook strategy  
- [ ] Landing stages S1–S5 wired to privacy API + published harness JSON  
- [ ] Supporter / store pages behind funding policy  

### 19.8 RE

- [ ] AI compact pipeline spec  
- [ ] Presence live layout campaign  
- [ ] Build-hash discipline automated  
- [ ] `az setup --re` only path for Ghidra (not default)  

---

## 20. Success criteria

1. Clone on a clean PC → setup → (compose or dev) → InGame.  
2. Playable spine through dungeon + gather + quest + level + PvP basics.  
3. Ontology answers “why message X?” without chat archaeology.  
4. Private profiles: stranger cannot read inventory/stats without permission.  
5. Admin grant gold → online client updates; audit row exists.  
6. Worlds scale via Fleet buffer under load test.  
7. Python absent from play path.  
8. Tick/CCU claims cite harness + hardware — also on the public status page.  
9. Launcher only runs signed patches.  
10. Agents follow nested AGENTS/skills without reinventing STATUS novels.  
11. **Overnight Pi/Orca worker survives kill and resumes; `worker_done` always fires.**  
12. **With 2 concurrencies, no two writers share a worktree.**  
13. **Agent dashboard shows node/tool/cost/promote for every long run.**  
14. **Public roadmap is v2 eras**, not the replay-era A–J wall; `done` always
    has evidence.  
15. Doc link-check green; new contributors (human or agent) find the frontier
    in &lt; 5 minutes.  
16. External PRs cannot merge without CI + human on `risk:high`.

---

## 21. Non-goals

- Recreating Amazon’s org chart of services  
- Public inventory APIs without privacy engine  
- k8s before bare/compose playable  
- Trusting the client for wealth or bans  
- LLM auto-verified atlas facts  
- Region transfers before handoff protocol  
- Modifying Steam in place  
- Admin ports on public world interfaces  
- Using the public landing as the engineering task board  
- Exposing agent traces, prompts, or raw captures on the public site  
- Vendor lock that prevents swapping the agent runner later  

---

## 22. Maintenance

- Product / security / reorg / deploy / **agent factory** / **site** vision →
  this file.  
- Tick/wire/DTLS/store mechanics → `PLAN-backend-rust.md`.  
- Short architecture summary → `ARCHITECTURE.md` (keep thin; link here).  
- Frontier → `STATUS.md` only.  
- Public display roadmap → `site/src/data/roadmap-v2.ts` (v1 archived).  
- Legal / collab → `LEGAL.md`, `NOTICE`, `CONTRIBUTING.md`.  
- Crypto mechanics → `PLAN-backend-rust.md` §0.3 + ADR 0004.  
### Reorg completeness (as of branch `refactor/knowledge-os`)

| Slice | State |
| --- | --- |
| Knowledge OS / docs / ADRs / ontology seeds | **Done** |
| DX (`setup` profiles, doctor, contributor loop, gitignore) | **Done** |
| Domain crates model/commands/privacy + ladder ontology | **Wired** |
| `deploy/local` + Linux Dockerfiles + `platform/` skeletons | **Done** |
| Archive noise (`odd` → archive); no migration-map doc | **Done** |
| Daily loop = native `az.dev` (ADR 0009) | **Done** |
| Agentic boot-naming campaign ready | **Ready to run** |
| R7 retire Python play path | **Open** (needs parity) |
| Playable spine / presence / capacity | **Open** (gameplay) |

**Next execution (agentic):**

1. Run boot-naming campaign (ontology coverage from open → InGame)  
2. Presence layouts → compose spawn; enter world via `az.py dev`  
3. MSVC + vcpkg OpenSSL (`az doctor`)  
4. Lock rename (ADR 0005)  
