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
- [ ] T4 — Monitor `progress.json` to `status=complete`; retry `status=fail`
      rows later with a higher `--timeout`.
- [ ] T5 — Commit the layer-1 milestone to docs with evidence.

## Blocked by this feature

Layer 2 (PAK index) must not fight the dump for disk, and layer 3 (naming the
loaders) needs the corpus to search. Protocol captures (work order step 4) are
independent and stay on the 2027-01-31 deadline.

## Evidence log

| When | What |
| --- | --- |
| 2026-10-01 | exe present, sha256 matches the plan. `peutil.py selftest` OK (6/6). |
| 2026-10-01 | `decomp.py --selftest` → `MISSING Ghidra headless not found`. No `%USERPROFILE%\tools\ghidra_*`, no `GHIDRA_HOME`, no `%LOCALAPPDATA%\Azoth\decomp\ghproj`. Blocker: no decompiler on this machine. |
| 2026-10-01 | T1: Ghidra 12.1.4 installed at `C:\Users\ivang\tools\ghidra_12.1.4_PUBLIC` (569,649,598-byte release zip). `check_install()` returns no problems; JDK 25 accepted. |
| 2026-10-01 | T2: `peutil.py selftest` OK 6/6; `decomp.py --selftest` OK, `ghproj` created (459 MB). |
| 2026-10-01 | T3: `corpus.py` launched, pid 21212, 423,579 ranges, sha256 re-verified, version string `[RETAIL].Javelin.1.400.6031.6004151`, 8 threads, 12 GB heap. Rate fell 111 → 60 func/s as functions got larger; 24 `status=fail` so far. |
