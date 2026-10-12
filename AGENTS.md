# Azoth working rules

Use these rules for code, research, and runtime work in this repository.

## Read first

- [README.md](README.md) for the project map and local commands.
- [STATUS.md](STATUS.md) for the one active project frontier.
- [docs/ROADMAP.md](docs/ROADMAP.md) for sequencing and cleanup decisions.
- `.agents/prompts/README.md` for reusable, focused task prompts.
- `.agents/skills/azoth-re/SKILL.md` for static RE and decompilation.
- `.agents/skills/azoth-live-debug/SKILL.md` before a live game experiment.
- `.agents/skills/azoth-server/SKILL.md` for server, Rust, or content work.

## Durable facts

- Protocol facts and client-request schemas live in `research/atlas/`.
- Confirmed native function names and evidence live in
  `research/atlas/client-functions.json`.
- Static analysis tools live in `reverse/tools/`; build-specific live probes
  live in `reverse/probes/client/`. Invoke a probe with `python az.py probe`
  and its name. Ghidra projects, pseudocode,
  and indexes default to ignored `reverse/builds/<client-sha256>/`. Tool binaries
  and Python dependencies live under ignored `.azoth/` after `./az.ps1 setup`
  (or `python az.py setup` if Python is already installed).
- The private runtime and client profile live under ignored
  `private-client/runtime/` and `private-client/profile/`. Steam is a
  read-only source: never delete, move, modify, or hardlink anything under
  the Steam install. Losing `assets/*.pak` (~76 GB) on 2026-10-06 cost a
  full re-download; after anything touches the install, re-verify the
  executable SHA-256 before reusing build-scoped analysis.
- `python az.py dev` owns hidden Caddy, gateway, and world processes. Use
  `python az.py dev stop`, `python az.py game restart`, `python az.py status`,
  and `python az.py stop` for lifecycle management. PIDs and logs live under
  `.azoth/state/` and `.azoth/logs/`.
- A finding is not durable if it exists only in chat, a session note, or
  `STATUS.md`. Update the source registry when evidence is obtained.
- Mark an unverified field as `"evidence": "guessed"`. Do not silently turn a
  candidate name or decompiler guess into a confirmed fact.
- `research/sessions/` contains local raw captures. Keep secrets and full
  payloads there; do not commit raw captures.

## Reverse engineering

- Identify the exact client build before relying on an address or offset.
- Use the full executable SHA-256 to keep Ghidra projects and generated corpora
  isolated by build. A short hash or version string is not a build identity.
- Start with the cached xref map, then strings/reflection metadata, then a
  targeted Ghidra decompile (`python az.py re xref`, then
  `python az.py re decompile`); use Capstone for byte-level questions.
- For screen-by-screen understanding, run the incremental campaign
  (`python az.py re campaign`) and write every learned behavior into the
  growing knowledge plan under `research/atlas/client-map/`, with evidence
  links.
- Decompiler output is pseudocode, not verified source. Record the VA, what was
  observed, and how it was confirmed. Verify important conclusions against a
  second signal where practical.
- Never use ReadProcessMemory, Frida, or a debugger while EAC is active or its
  state is uncertain. Project fact: **Azoth never runs EAC** — the private
  client is launched with EAC disabled and no Azoth workflow ever enables it.
  The caution exists only because a private launch by itself does not prove
  the EAC process is absent; verify that before any live-analysis session.
- Capture traffic only from Azoth's own gateway. Do not attempt MITM against
  Amazon endpoints.
- Treat `Game.log` as evidence for client state and RMI names. Ingest it with
  `python az.py re ingest-log ingest --log <Game.log>`.
- Gateway requests append to `services/gateway/traffic.jsonl`; endpoint
  summaries go to `research/atlas/observed-endpoints.json`. After a play
  session, run `python az.py doc` to refresh `research/atlas/openapi.json`.

## Runtime and evidence

- `python az.py ...` is the supported entry point for local operations.
- On an existing checkout, close NewWorld and any analysis process using the
  old per-user state, then run `python az.py migrate` once. It moves the old
  game profile/runtime into ignored `private-client/` paths and caches/tools
  into ignored `.azoth/`; it refuses destination conflicts and never overwrites.
- A world A/B measurement requires a fresh `NewWorld.exe`. Confirm the current
  run in `Game.log`; interpret probe counters only after it shows
  `ProcessPendingReliableMsgQueue processing 26 messages`.
- Set `AZOTH_LOG_RAW=1` on the world server when distinguishing missing UDP
  traffic from DTLS rejection. `python az.py dev` does not forward environment
  changes made in another shell; start the world process with the variable set.
- Gateway and world traffic logs are append-only while their service is
  running. Stop the service before editing or replacing a log.
- Restart the world server when its peer table has accumulated stale sessions.
  It resets a reused client source port on a new ClientHello, but a long-lived
  server still retains dead peers.
- A gateway shape change does not refresh the open game UI; restart the game
  before comparing a new response body. `python az.py shape <body.json>` is the
  end-to-end harness.
- Before reading a screenshot, shrink it with
  `python scripts/shrink-image.py <capture.png>`. Never read the raw PNG.

## Code and documentation

- Gateway and tooling use the Python standard library. `services/world` has one
  intentional external dependency, pyOpenSSL, for DTLS. Local Frida tooling
  uses the repo-local `.azoth/venv/`; run scripts through `python az.py run`.
- Keep paths relative to the repository or an OS-provided data directory. Do
  not add machine-specific user paths.
- Keep modules focused. Add abstraction only when it removes real duplication
  or makes a measured hot path clearer. Comments should explain wire behavior
  and non-obvious constraints.
- Docs, code comments, and technical artifacts are in English. Historical
  `docs/sessions/` material remains in Spanish.
- Keep `STATUS.md` short and current. Put detailed evidence in the atlas,
  symbol registry, or a focused reference; do not copy it between documents.
- `site/public/roadmap.json` is the public roadmap display on the landing
  page. Update it after milestones (state, evidence, new points, reorder),
  but it is not the work tracker: planning and current status stay in
  `STATUS.md` and `docs/ROADMAP.md`. The canonical public roadmap source is
  `site/src/data/roadmap-full.ts`; regenerate its display copy with
  `node site/scripts/gen-roadmap.mjs`. See `site/README.md` for evidence rules.
- Close every successful experiment: write down the winning behavior, why it
  worked, its side effects, and the evidence; keep one implementation of the
  supported behavior; remove failed alternatives from runtime code and tool
  indexes. Keep useful negative results in the atlas so they do not turn into
  branches that the server can still execute.
- Use the existing `unittest` suites for code changes when validation is
  requested or needed before a commit. Do not add a test framework.

## Agent work and durable handoffs

- A contribution is not complete when the work exists only in a chat summary.
  Before handing it back, document the result in its canonical repository home:
  implementation in code, protocol/client facts in `research/atlas/`, the active
  blocker in the short `STATUS.md`, and sequencing in `docs/ROADMAP.md`. Update
  the public roadmap only when a milestone or its evidence changes.
- Every handoff must state what changed or was learned, the files/artifacts,
  exact build and experiment/capture identifiers, what was directly observed vs
  inferred or guessed, validation performed (or not performed), failed
  hypotheses, side effects, and the next concrete blocker.
- Every completed public-roadmap deliverable needs a clear description and a
  unique, authentic capture that demonstrates that specific result. Curated,
  public-safe evidence images may live under `site/public/evidence/`; never
  reuse an unrelated screenshot or treat a planned/active item's image as
  proof of completion. If a real capture does not exist yet, leave it marked
  pending and capture it when the acceptance condition is met.
- The coordinating agent checks each handoff against its evidence, resolves
  conflicts with existing records, and updates the canonical docs before
  declaring the task done. Preserve useful negative results. Raw captures and
  secrets stay in the ignored research-session paths.

## Repository hygiene

- Do not commit or push unless the user explicitly asks.
- Keep certificates, local game files, raw captures, generated decompile
  workspaces, logs, and raw screenshots out of Git. The only screenshot
  exception is a deliberately curated public-roadmap proof under
  `site/public/evidence/`; never copy raw captures or secrets there.
- Read `docs/ADMIN.md` before changing Windows host routing. Do not start
  privileged operations as part of static repository work.
- Do not delete or archive a research tool until its callers, evidence, and
  reproducibility value have been checked.
