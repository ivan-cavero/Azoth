# Extraction inventory — build 1.460, 2026-10-22

What one machine and three live sessions produced from the **official Amazon
servers** before they close, and what is still open. Every claim is tagged
**[observed]** (read from a file, a pcap, a `netstat` sample, or `Game.log`) or
**[inferred]**.

Build in scope: **`1.460.6033.6024067`**, SHA-256
`30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`,
179,214,008 B. The repository's prior analysis was all measured on
`1.400.6031.6004151` / `8654f01d…`; see [builds.json](../research/atlas/builds.json).

## What was captured

Three passive sessions against live Amazon, **EAC active throughout**, with no
process memory read, no injection, no debugger. `Game.log` watcher + `pktmon` at
the NIC + `netstat` per PID + DNS cache.

| Session | Duration | In world | Purpose |
| --- | --- | --- | --- |
| `live_20261022_r1460_first` | 1247 s | ~17 min | walk, combat, inventory, first protocol picture |
| `live_20261022_r1460_auction_craft` | 492 s | 3 min 20 s | auction and crafting, first attempt |
| `live_20261022_r1460_trading_timed` | 1525 s | ~22 min | auction and crafting with **a timestamped marker before every action** |

## Static artifacts, regenerated for 1.460

| Artifact | 1.400 | 1.460 | Validation |
| --- | --- | --- | --- |
| `research/atlas/az-type-registry.json` | 4,818 | **5,109** | 17 hand-verified GUIDs reproduce |
| `research/atlas/javelin-messages.json` | 144 | **147** | all 12 movement wire types reproduce |
| `research/derived/wire-type-names.json` | 2,037 named | **2,239 / 7,052** | 8 anchors re-derived on this image |
| `research/derived/client-facet-factories.json` | 369 tables | **369 / 368 names** | identical name set to 1.400 |
| `research/derived/pak-summary.json` | 1,413,205 | **1,414,367** entries / 123 paks | exe hash measured, not assumed |
| `reverse/builds/30fe6461…/corpus/` | — | **423,609 ranges, 421,742 ok / 27 fail** | 1.1 GB, 3,396 shards |

**[observed] The wire numbering did not change between builds.** All 7,052 GUIDs
in the wire-type table are identical to 1.400; only the `.rdata` string layout
moved. A type that was wire 726 in 1.400 is wire 726 in 1.460.

## What the live sessions established

### The auction and crafting have no transport of their own

Seven timestamped markers, each with a connection snapshot, in
`research/sessions/live_20261022_r1460_trading_timed/MARKER_*.txt`:

| Action | Marker (UTC) | New host | New port |
| --- | --- | --- | --- |
| standing at the trading post | 10:30:34 | — baseline — | — |
| opened | 10:36:46 | no | no |
| searched with a filter | 10:38:14 | no | no |
| published an item | 10:42:32 | no | no |
| cancelled the sale | 10:46:40 | no | no |
| bought an item | 10:48:31 | no | no |
| crafted an item | 10:49:56 | no | no |

**[observed]** The REP flow (`192.168.50.12:27000 ↔ 35.71.153.244:53731`,
125,485 packets, 34 MB) runs at a **flat 82 packets/s** through all seven
windows, peak 85–88 in every one, against a whole-session median of 82 and p95 of
86. Reproduce with `research/sessions/live_20261022_r1460_trading_timed/rep_timeline.py`.

**[inferred]** The auction and crafting therefore ride the already-open REP DTLS
stream, multiplexed at the normal state-stream rate, with no observable
signature. The keep-alive-TLS alternative is not ruled out, only not observed.

**Consequence for the private server:** reproducing the auction is an
application-protocol problem, not an infrastructure one. There is no hidden
channel to clone and no AWS backend to emulate for it.

### The trading post is not a Javelin facet path

**[observed]** In the 1.460 type registry, `TradingPostComponentClientFacet`,
`TradingPostComponentServerFacet`, `TradingPostEventBusHandler`,
`GlobalMarketData`, `MarketData` and `MarketDataBinder` all carry
`wire_type: null`. Six types, **zero wire-addressable**. Crafting has 24 types
with 8 addressable; storage/search 19 with 10.

## Traps recorded so they are not repeated

- **`Game.log` is blind to these systems.** It contains **zero** occurrences of
  auction, trading, craft, recipe, salvage — and even `inventory`, which
  demonstrably works. An early "no coverage" verdict came from reading the log's
  silence as the world's silence.
- **`ReceiveStorageSearchItems` is not auction activity.** It fired 23 times in
  two sessions, all carrying the *same* timestamp, one second **before** the
  InGame transition: the login burst.
- **`pktmon --comp nics` captures the whole machine.** A session pcap contains
  the agent's own tooling. The 22,273-packet flow to `51.222.108.239` was first
  read as voice from its OVH reverse DNS; with SNI it is `code.verboo.ai`. A raw
  top-IP table is not a game-flow table.
- **`18.172.218.10` is not the craft.** It resolves to
  `d1hkbwzm1bktgo.cloudfront.net` (the CMS/MOTD CDN) and opened 35 s *before* the
  craft marker: the periodic CMS poll.
- **A stale address pin is dangerous, not merely useless.** `0x141698eb0` was a
  `GameRigidBody` facet factory in 1.400 and is a **live factory in 1.460 for a
  different class** (`AoiGhostListenTestComponentClientFacet`).

## Tooling defects found and fixed

| Tool | Defect | Fix |
| --- | --- | --- |
| `reverse/tools/net.py` | `extract_sni` read the SNI lengths two bytes early, so **no pcap could name a single host** (0 → 28 hosts) | offsets corrected, 4 tests, differential clean |
| `reverse/tools/pakindex.py` | `exe_sha256_prefix` was a **hardcoded literal**, stamping the old build on a new inventory | measured from the installed exe, 3 tests |
| `reverse/tools/scan-client-facets.py` | pinned to moved `.text` pointers **and** imported Capstone, absent from the venv | pins re-derived, stdlib decoder, 11 tests |
| `reverse/tools/scan-wire-names.py` | pinned to the old build and refused to write | 8 anchors re-derived, pin moved, 16 tests |
| `reverse/tools/scan-az-types.py` | only the 1.400 brace form; the 1.460 form carries pointer qwords between name and `{GUID}`, losing 111 names | field-block form added, 939 table-resident pairs |
| `az.ps1` | did not wait on the Python installer, read an empty exit code, so a clean machine could not run `setup` | waits on the process, reads the real code |
| `research/tools/capture/Start-NwCapture.ps1` | resolved `tools/re/`, which moved to `reverse/tools/` — the kit would have died after a full capture | path corrected |
| `research/.gitignore` | re-included `REPORT.md` and `extracted/*.json`, which carry the persona id, character UUID and REP endpoint | excluded after the negation |

## Still open

- **5,015 of 7,052 wire types unnamed.** The registry is the bottleneck: 939
  table-resident pairs, but many brace-wrapped GUIDs in the image are still not
  attributed to a name by either route.
- **`rdata` adjacency is build-fragile** even with identical GUIDs: 530 rows
  changed name between the two artifacts and the name-like filter still admits
  fragments (wire 41 `ppSA`, wire 67 `min`). The 8 anchors plus ~1,716 stable rows
  are the trustworthy core.
- **`ReceiveActorMsg` changed GUID** (`764599e8…` → `b232749e…`) and both exist in
  the 1.460 table (wire 921 and 522), so it is not an index shift. Whether the
  type changed or the name-to-GUID pairing drifted needs its descriptor getter
  decompiled — the corpus now makes that possible.
- **The render blocker is untouched by any of this.** The server owns a captured
  actor's position and the client re-imposes it; no body is drawn. That is a
  render problem, not a position or authority one, and it is independent of the
  auction work.
- **`python az.py shot` returns a black frame** on this client's DX12 swapchain
  (`PrintWindow`). A DPI-aware screen grab works.

## Next useful session

The one thing the wire cannot answer is what the auction messages *contain*. The
next session that pays for itself is not another trading-post visit — it is a
session that exercises a system whose facets **do** have wire types, so the
content can be compared against the corpus: an **expedition** (a new `level.pak`
and a separate REP or instance), a **territory change / fast travel**, and
**war**. Each of those is a state transition, which is exactly what the corpus
can now be read against.
