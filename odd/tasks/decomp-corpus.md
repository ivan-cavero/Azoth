# decomp-corpus — full client decompilation, layer 1 (code corpus)

Owner feature doc for [DECOMP-PLAN.md](../../research/docs/DECOMP-PLAN.md) work order
step 1: Ghidra pseudocode of every `.pdata` function of the frozen client build.

Frozen target (verified this session):

| | |
| --- | --- |
| exe | `C:\Program Files (x86)\Steam\steamapps\common\New World\Bin64\NewWorld.exe` |
| sha256 | `8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e` (matches DECOMP-PLAN) |
| size | 179,204,176 bytes |
| .pdata ranges | 423,579 (zero-length dropped) |
| corpus dir | `%LOCALAPPDATA%\Azoth\decomp\corpus\8654f01d324636d9\` (outside the repo) |
| Ghidra project | `%LOCALAPPDATA%\Azoth\decomp\ghproj` program `azoth` / `NewWorld.exe` |

## Why this feature exists

The corpus is the search index for all later RE. Without it every question about
"where is the loader" costs a fresh Ghidra session. It is a one-time dump per
frozen build; a maintenance exe gets its own corpus directory.

## Tasks

- [x] T1 — Install Ghidra 12.1.4 under `%USERPROFILE%\tools\` so
      `decomp.py:resolve_ghidra_home()` discovers it.
- [x] T2 — Toolchain preflight: `peutil.py selftest` (6/6), then
      `decomp.py --selftest` which imports the exe into `ghproj` once.
- [x] T3 — Launch the full corpus run in the background (`corpus.py`).
- [x] T4 — Monitor `progress.json` to `status=complete`; retry `status=fail`
      rows later with a higher `--timeout`.
- [x] T5 — Record the layer-1 milestone in this file and in `STATUS.md`.

## Blocked by this feature

Layer 2 (PAK index) no longer has to wait for disk: the corpus is done. Layer 3
(naming the loaders) can now search the corpus. Protocol captures (work order
step 4) are independent and stay on the 2027-01-31 deadline.

## Evidence log

| When | What |
| --- | --- |
| 2026-10-01 | exe present, sha256 matches the plan. `peutil.py selftest` OK (6/6). |
| 2026-10-01 | `decomp.py --selftest` → `MISSING Ghidra headless not found`. No `%USERPROFILE%\tools\ghidra_*`, no `GHIDRA_HOME`, no `%LOCALAPPDATA%\Azoth\decomp\ghproj`. Blocker: no decompiler on this machine. |
| 2026-10-01 20:04 CEST | Blocker cleared by another session: Ghidra 12.1.4 landed at `%USERPROFILE%\tools\ghidra_12.1.4_PUBLIC`, the exe was imported into `ghproj`, and `corpus.py` started with 8 threads. |
| 2026-10-01 22:21 CEST | **Corpus complete**: `finished=423579` of 423579 ranges, 1695 shards. The Ghidra JVM exited and the project lock is free, so `decomp.py --symbol/--target` works again. First use: the manager gate chain, cached at `research/derived/decomp/gate-chain.c`. |
| 2026-10-02 | **Authoritative counts from the shard index files** (not from `progress.json`, whose counters were reset when the run was resumed): 423579 idx rows, **423542 `ok` / 37 `fail`**, 423579 distinct starts, **0 missing and 0 duplicates** against `ranges.txt`. The earlier `ok=423554 / fail=25` reading came from a stale `progress.json` and is superseded. The 37 failures stay in their shards; retry them later with `--timeout 180` and a small `--limit`. |
| 2026-10-01 | The `status=fail` rows stay inside their shards; retry them later with `--timeout 180` and a small `--limit`. They do not block layer 2 or the loaders. |
