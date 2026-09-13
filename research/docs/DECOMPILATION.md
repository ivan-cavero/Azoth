# Decompilation — how to extract anything from the client

The client is the source of truth. When a string is not enough (which JSON key it
reads, which predicate discards a world, what an error code means), you read the
code. This document is the procedure and the tooling already installed.

Target client: `[RETAIL].Javelin.1.400.6031.6004151`
(`C:\Program Files (x86)\Steam\steamapps\common\New World\Bin64\NewWorld.exe`,
179 MB, image base `0x140000000`).

**Discipline (non-negotiable):** every confirmed finding goes into the atlas
(`research/atlas/`) **at the moment of discovery** — key names, types, required/
optional, and the VA as evidence — and confirmed function addresses go into
`research/derived/symbols.json` with `va`, `what`, `found_by`. If it only lives in
the conversation, it does not exist. This is what makes the work cumulative.

## Tools (all in `research/tools/re/`)

| Tool | For |
| --- | --- |
| `peutil.py` | PE + function table (`.pdata`), callers (`call rel32`), strings by VA. **Start here.** |
| `decomp.py` | Decompiles specific functions with Ghidra headless, caches the project. |
| `xrefmap.py` | One-pass xref map (per-query scans timeout on 179 MB). |
| `catalog.py` | Bulk dump: routes, models, enums, gRPC, config keys, hosts → `derived/*.json`. |
| `ghidra/DecompileTargets.java` | Helper compiled and run inside Ghidra by `decomp.py`. |

One-time install:

```powershell
# Ghidra 12.1.3 + JDK 21 (already at C:\Users\ivang\tools\ghidra_12.1.3_PUBLIC)
$env:GHIDRA_HOME = "C:\Users\ivang\tools\ghidra_12.1.3_PUBLIC"
$env:JAVA_HOME   = "C:\Program Files\Eclipse Adoptium\jdk-21.0.11.10-hotspot"
$env:AZOTH_DECOMP_WORK = "C:\Users\ivang\tools"   # Ghidra project + classes + logs
```

Verify (must print `OK`; otherwise trust nothing below):

```bash
python research/tools/re/peutil.py selftest    # 6/6 PASS, 423,594 functions
python research/tools/re/decomp.py --selftest  # compiles the helper, decompiles 1 fn
```

## Procedure: from a question to code

### 1. Find the anchor

A string, an HTTP route, or a JSON key. `peutil` resolves VAs and finds who touches them:

```bash
python research/tools/re/peutil.py info                       # sections + image base
python research/tools/re/peutil.py resolve 0x1483c09a0        # VA -> 'publicName'
python research/tools/re/peutil.py str publicStatusCode       # string -> VAs
python research/tools/re/peutil.py func 0x144f54d63           # VA -> function range
python research/tools/re/peutil.py callers 0x1417c40a0        # who calls it
```

Method warning: a string with **0 xrefs** may be dead **or** referenced through a
pointer table. Verify with an 8-byte pointer search before concluding (happened
with the aws-sdk model table: it was decorative).

### 2. Read the code

```bash
# a function we already know by symbolic name
python research/tools/re/decomp.py --symbol worldtype_mapper

# the code that reads a key (VA of the xref)
python research/tools/re/decomp.py --target 0x144f54d63

# every function calling a helper (to climb from a leaf)
python research/tools/re/decomp.py --callers-of 0x1417c40a0

# explicit range (when .pdata is not enough)
python research/tools/re/decomp.py --range 144f40780-144f555e0
```

Default output: `derived/decomp/<start>-<end>.c` (gitignored; regenerable).
First run imports the exe into a Ghidra project (~4 min); later runs reuse the
project (`-process`) and take ~1-2 min of startup + decompilation.

### 3. Record the finding

- Confirmed **wire keys / models / errors** → `research/atlas/models.json`,
  `endpoints.json`, `errors.json` (with the VA as `evidence`).
- Confirmed **function addresses** → `research/derived/symbols.json` with `va`,
  `what`, `found_by`, so next session writes `--symbol <name>` instead of
  re-deriving.
- **Debug levers / config switches** spotted in memory → `research/atlas/levers.md`
  ("To investigate" section) immediately, not "later".

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

The world panel list stays empty ("no hay mundos activos en tu región" =
`Errors::login_no_worlds`). The model (`WorldMetadata`) and its schema are RE'd,
and the client **parses without error** (the failure is semantic). The missing
piece is either the **root JSON key** of the getlogininfo body that fills the
worlds vector, or a **predicate** discarding our entry. Open leads, by value:

1. **Decompile the real GetLoginInfo unmarshaller** — paths `0x1464154e0` /
   `0x146412430` (NOT the result vtable `0x148503018`, which only holds
   dtor/copy). The unmarshaller names the root key it visits.
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
