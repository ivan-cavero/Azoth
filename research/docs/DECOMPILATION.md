# Decompilation — how to extract anything from the client

The long-term program (why we are decompiling, the corpus path, and how to
resume) is [DECOMP-PLAN.md](DECOMP-PLAN.md). This file is the tool procedure.

The client is the source of truth. When a string is not enough (which JSON key it
reads, which predicate discards a world, what an error code means), you read the
code. This document is the procedure and the tooling already installed.

Target client: `[RETAIL].Javelin.1.400.6031.6004151` (179 MB, image base
`0x140000000`). The executable location is resolved by `common.py` from the
local game install; do not add machine-specific paths to scripts or docs.

**Discipline (non-negotiable):** every confirmed finding goes into the atlas
(`research/atlas/`) **at the moment of discovery** — key names, types, required/
optional, and the VA as evidence — and confirmed function addresses go into
`research/derived/symbols.json` with `va`, `what`, `found_by`. If it only lives in
the conversation, it does not exist. This is what makes the work cumulative.

## Tools (all in `research/tools/reversing/`)

| Tool | For |
| --- | --- |
| `peutil.py` | PE + function table (`.pdata`), callers (`call rel32`), strings by VA. **Start here.** |
| `decomp.py` | Decompiles specific functions with Ghidra headless, caches the project. |
| `xrefmap.py` | One-pass xref map (per-query scans timeout on 179 MB); persists by executable size/mtime under `%LOCALAPPDATA%\Azoth\decomp\xrefmap.json`. |
| `catalog.py` | Bulk dump: routes, models, enums, gRPC, config keys, hosts → `derived/*.json`. |
| `ghidra/DecompileTargets.java` | Helper compiled and run inside Ghidra by `decomp.py`. |

One-time install:

```powershell
# Ghidra is auto-discovered under %USERPROFILE%\tools\ghidra_*; set this only
# when it is installed elsewhere. JDK resolves from JAVA_HOME or javac on PATH.
$env:GHIDRA_HOME = "<path-to-ghidra-install>"
# Optional override for the Ghidra project, classes, queue, and logs:
$env:AZOTH_DECOMP_WORK = "$env:LOCALAPPDATA\Azoth\decomp"
```

Verify (must print `OK`; otherwise trust nothing below):

```bash
python research/tools/reversing/peutil.py selftest    # 6/6 PASS, 423,594 functions
python research/tools/reversing/decomp.py --selftest  # compiles the helper, decompiles 1 fn
```

## Procedure: from a question to code

### 1. Find the anchor

A string, an HTTP route, or a JSON key. `peutil` resolves VAs and finds who touches them:

```bash
python research/tools/reversing/peutil.py info                       # sections + image base
python research/tools/reversing/peutil.py resolve 0x1483c09a0        # VA -> 'publicName'
python research/tools/reversing/peutil.py str publicStatusCode       # string -> VAs
python research/tools/reversing/peutil.py func 0x144f54d63           # VA -> function range
python research/tools/reversing/peutil.py callers 0x1417c40a0        # who calls it
```

Method warning: a string with **0 xrefs** may be dead **or** referenced through a
pointer table. Verify with an 8-byte pointer search before concluding (happened
with the aws-sdk model table: it was decorative).

### 2. Read the code

```bash
# a function we already know by symbolic name
python research/tools/reversing/decomp.py --symbol worldtype_mapper

# the code that reads a key (VA of the xref)
python research/tools/reversing/decomp.py --target 0x144f54d63

# every function calling a helper (to climb from a leaf)
python research/tools/reversing/decomp.py --callers-of 0x1417c40a0

# explicit range (when .pdata is not enough). A sloppy window is snapped
# onto the real .pdata functions so Ghidra is not asked to decompile
# mid-instruction (that produced a 1-byte halt_baddata stub).
python research/tools/reversing/decomp.py --range 144f40780-144f555e0
```

Default output: `derived/decomp/<start>-<end>.c` (gitignored; regenerable).
First run imports the exe into a Ghidra project (~4 min). Later one-shot runs
reuse the project (`-process -readOnly`) and do **not** rewrite the ~480 MB
project database — that rewrite was most of the per-call wait.

Keep one JVM up and the later calls are a queue round-trip:

```bash
python research/tools/reversing/decomp.py --serve    # blocks; leave it running
python research/tools/reversing/decomp.py --target 0x144f54d63
python research/tools/reversing/decomp.py --stop
```

`--serve` only `-process`es an existing project. The first open is still the
slow part; each function after `ready` should be seconds, not a new JVM. For a
focused RE session: import once with the first `--target`, start `--serve`, then
batch symbols/targets/callers through that one server. `xrefmap.py` persists its
map outside the repo, so later xref queries do not rescan the 179 MB executable.
Pass `--rebuild` after replacing the executable or when debugging cache validity.

### 3. Record the finding

- Confirmed **wire keys / models / errors** → `research/atlas/models.json`,
  `endpoints.json`, `errors.json` (with the VA as `evidence`).
- Confirmed **function addresses** → `research/derived/symbols.json` with `va`,
  `what`, `found_by`, so next session writes `--symbol <name>` instead of
  re-deriving.
- **Debug levers / config switches** spotted in memory → `research/atlas/levers.md`
  ("To investigate" section) immediately, not "later".

## Modern tooling landscape (researched 2026-09-13)

| Tool | Verdict for Azoth |
| --- | --- |
| **Ghidra headless + `decomp.py`** (current) | **Keep.** Free, scriptable, project cache works. This is the automation backbone. |
| **PyGhidra** (bundled since Ghidra 11.2; ex-`pyhidra`) | **Adopt when needed.** Drives Ghidra from native CPython 3 (no Jython): `import pyghidra; with pyghidra.open_program(exe) as flat: ...` — lets RE scripts live in the same Python env as the atlas tooling. Upgrade path for `decomp.py` if Jython friction bites. |
| **ghidra_bridge** | Alternative CPython bridge (RPC server inside Ghidra). Prefer PyGhidra: first-party, no server process. |
| **Binary Ninja** | Best-in-class HLIL API and decompiler UX, but paid. Not needed: our targets are JSON parsers and reflection tables, well within Ghidra's reach. |
| **IDA Pro** | Industry king, priced for studios. Same verdict as Binary Ninja. |
| **angr** | Symbolic execution. Overkill for wire-format RE; potentially useful later for finding predicate inputs (e.g. the world-filter check) if decompilation stalls. |
| **x64dbg / Cheat Engine** | Live debugging only — forbidden while EAC is active (see `EAC.md`); use only after confirming the private target process has EAC inactive. |

## Traffic capture: why our gateway beats a MITM proxy

Generic game-RE workflow uses mitmproxy/mitmproxy2swagger against the live client,
then fights TLS and certificate pinning. We do not need any of that:

1. **The client talks to OUR gateway** (hosts + local CA, private mode). We see every
   request and response **in plaintext** at the server — no pinning to defeat, no
   proxy certs, no baneable interception of Amazon traffic.
2. **Full body capture is built in** (`routes/traffic.py`): readable records and
   redacted headers land in `services/gateway/traffic.jsonl`; exact request and
   response body bytes are stored in ignored `services/gateway/traffic-payloads/`
   sidecars with lengths and SHA-256 references. The atlas keeps compact examples.
   For a world run, use `scripts/capture-world-run.py` to snapshot the Game.log,
   one complete REP session, matching gateway traffic plus exact HTTP body
   sidecars, ACK analysis, process hash, and optional probe log/reduced shot.
   Raw payloads remain local because they can contain live identity/session data.
3. **`python az.py doc`** renders `research/atlas/openapi.json` (OpenAPI 3.1) from
   that traffic — our equivalent of mitmproxy2swagger, but sourced from the server
   itself, so it is always exact.
4. External capture (pktmon via `research/tools/capture/`) stays useful ONLY for
   official sessions (encrypted: gives IPs, ports, sizes, timing — never bodies).

### Capture every boundary we own

For a local test, server-side application logs are the authoritative payload
capture: gateway request/response bodies are exact `.bin` sidecars, REP inbound
records are post-DTLS plaintext, server sends are recorded before DTLS wrapping,
and `AZOTH_LOG_RAW=1` keeps the matching encrypted UDP datagrams. This lets one
attempt correlate encrypted carrier packet → decrypted stream → replay record
without asking a packet dissector to guess the application protocol.

Keep raw captures local: “full capture” can include login tokens, persona and
character IDs, and binary account state. For long external packet captures, use
bounded ring files and preserve the handshake/context packets that explain later
traffic; ring rollover can split protocol context ([Wireshark capture-file
guide](https://www.wireshark.org/docs/wsug_html_chunked/ChCapCaptureFiles.html)).

Memory evidence should be boundary-scoped: capture function entry/exit,
arguments, return value, and only the object fields needed to decide one
hypothesis. Whole-process dumps or continuous high-volume hooks are slower,
harder to correlate, and more sensitive than targeted snapshots. Revalidate the
exact build and EAC state before every live probe.

For this black frame, graphics profiling is a later branch. If the player-holder
gets populated and the frame remains black, use Windows Performance Recorder
with GPUView/WPA to separate CPU submission from GPU work ([Microsoft DirectX
profiling guide](https://learn.microsoft.com/en-us/windows/win32/direct2d/profiling-directx-applications)).
Current evidence instead has a null local-player holder, so first follow
application dispatch and possession. Time Travel Debugging can record and replay
a process backward, which may help if a specific field writer remains elusive,
but recording adds overhead and stopping it terminates the process; reserve it
for a focused private, EAC-free attempt ([TTD recording guide](https://learn.microsoft.com/en-us/windows-hardware/drivers/debuggercmds/time-travel-debugging-record)).

Reference for the generic approach if ever needed offline: mitmproxy2swagger
(converts mitmproxy flows to OpenAPI). We already have the better source.

## Method rules (learned the hard way)

- **`.pdata` gives exact bounds.** Ghidra needs start **and** end; an xref is not
  an entry point.
- **Ghidra 12 loads scripts as OSGi bundles.** A loose `.java` fails with "class
  could not be found"; compile and place the `.class` in a script dir (`decomp.py`
  does this).
- **`analyzeHeadless` + `cmd.exe`**: paths with parentheses (`Program Files (x86)`)
  break parsing. Use the short name `C:\PROGRA~2\...` (`decomp.py` does this).
- **Do not pipe Ghidra output through `| head`**: SIGPIPE kills the run mid-import
  and leaves a half-finished project.
- **Property names are the reflection registry's names**, not the aws-sdk model's.
  Confirmed: `WorldMetadata` uses `name`/`type`/`status`, not
  `worldName`/`worldType`/`worldStatus`.
- **The function that registers properties also states the TYPE**: each property is
  registered with a different helper (int / string / enum / nested object / bool).
  That distinguishes an enum from a free string without guessing.
- **Reflection registration blocks are gold**: the block at `0x144f54cda` lists the
  exact `WorldMetadata` keys in order; the camelCase UI block at `0x1483c0900` is
  the live wire serialization; the PascalCase block at `0x148703900` is decorative
  (0 xrefs of any kind).

## Established findings

See `derived/symbols.json` (source of truth, with VA and how each was found). Summary:

| Symbol | What it is |
| --- | --- |
| `worldtype_mapper` `0x1417c40a0` | Maps string→enum: `"FTUE"`→0, `"OpenWorld"`→1, rest→2 |
| `worldmetadata_property_table` `~0x144f54c00` | `WorldMetadata` schema with per-property types |
| `worlds_info_accessor` `0x144ad6e70` | `WorldsInfo` accessor (FNV-1a hash) |
| `big_parser` `0x144f40780` | 85 KB: property registration + world model parsing |
| `getlogininfo_request_builder` `0x1474ea680` | Builds the request (`channelId`, `includeNames`, `isTrialOwner`) |
| `login_error_enum` `0x147fc3d08` | Error tokens (`login_no_worlds`, `MAINTENANCE_MODE`, …) |
| `aws_model_name_table` `0x148702000` | aws-sdk name table: **decorative**, 0 xrefs |

## Still unresolved

**Mostly resolved — kept as the record of that hunt.** The world panel went from empty to a
working login on 2026-09-14 (the dual-schema answer: one body serves both the lowercase
`worlds` dropdown and the PascalCase `LoginInfoList` character gate — [LESSONS.md](LESSONS.md)
§3–4). The world now loads, spawns and renders (2026-10-02); the live frontier is owned by
[STATUS.md](../../STATUS.md) (as of 2026-10-04: the client self-reconnects ~5 s after spawn and
destroys its `ClientContext`). What remains from the list below is only item 2's technique
(RTTI/lambda member extraction), which folds into DECOMP-BACKLOG §7's RTTI recovery note.

<details><summary>The 2026-09-13 open-lead list (historical)</summary>

1. **Decompile the real GetLoginInfo unmarshaller** — done (2026-09-13):
   handler `0x1464154e0` builds the result via `FUN_146456b60` -> `FUN_1464033e0`.
   The intermediate model has FOUR vectors (0x168/0x420/0x170/0x78) + an error
   flag at +0x70 that gates success vs error rendering. Vector A = worlds
   (converter calls world-entry ctor + worldtype_mapper). The handler is invoked
   via vtable (no direct callers). Remaining: the JSON root key that fills the
   four vectors (aws-sdk-cpp/1.7.193 deserializer, reached through the callback
   mechanism). Ground truth: the client requests `worlds/list` only when the
   region dropdown opens.
2. **Lambda RTTI** `MakeReturnCallbackWithStatus<GetLoginInfoResult, LoginInfoList>`
   — the helper extracts `&result.<member>`; reading the lambda body yields the
   member offset, then find the member written by the unmarshaller.
3. **400-probe A/B**: serving HTTP 400 makes the UI advance (ValidationException
   path); a 200 that parses OK does not. If we serve the correct 200, the panel
   advances without error.
4. `type` registers as an **enum** (different helper than `status`), members
   `eWorldType_FTUE` / `eWorldType_OpenWorld` / `eWorldType_Unknown`. Try the wire
   with the registered member name, not the mapper's bare token.
5. `FUN_146474d00` (`RequestLogin`) does `SelectWorldByType` and logs
   `"Unable to find %s world, will use default/empty world id."` on failure → check
   `FUN_146465260` (the by-type lookup) and which container it uses.
6. `FUN_146407ad0` is the common world-entry constructor (called by all 3
   converters). Decompiling it shows which fields are mandatory.
7. Cvar `g_loginWithWorldTypes` ("Consider available world types before requesting
   login"): if there is an allowed-type list, an out-of-list type is silently
   discarded.
</details>

## Version-to-version survival of findings (researched 2026-10-05)

Every finding in `symbols.json` is anchored to one exe hash. When (if) a maintenance client
ships, the first line of defense is **ours, not a new tool**:

1. Hash the new exe, give it its own corpus directory (DECOMP-PLAN's rule).
2. Re-derive the known anchors with the existing kit: `peutil.py str` for each named string,
   the cached `xrefmap` (rebuilt with `--rebuild`), and `bytepat.py` for the byte-pattern
   sites (the DTLS verify site was already byte-identical across 1.365 → 1.400).
3. Re-validate `symbols.json` entries and record the new VAs beside the old ones.

If whole-build diffing is ever genuinely needed: **BinExport** (first-party Ghidra extension,
github.com/google/binexport) + **BinDiff** (github.com/google/bindiff, free for non-commercial
use, Ghidra as backend). **Diaphora** is IDA/radare2-only — not our path. **Ghidra Function ID**
signature databases work exactly when compiled function bytes are unchanged, which is the
frozen-build case. Ghidra's Version Tracking is a GUI session workflow — heavy; keep as last
resort. Detail in [DECOMP-BACKLOG.md](DECOMP-BACKLOG.md) §11.
