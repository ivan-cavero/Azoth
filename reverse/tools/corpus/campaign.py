#!/usr/bin/env python3
"""Incremental, phase-scoped decompilation campaign runner.

The bulk corpus (corpus.py) proves coverage; understanding is built phase by
phase. This tool keeps a persistent per-build work queue so an agent can grow
the decompilation "little by little" without losing track:

  - a committed manifest (`research/atlas/decomp-campaign.json`) defines the
    player-visible phases and their seed targets (atlas symbols or VAs);
  - per-build state (pending/done/failed, one .c file per function) lives under
    the ignored `reverse/builds/<full-sha256>/campaign/` workspace;
  - batches go through the long-lived decomp server when it is up (seconds per
    function after the first import), otherwise through one-shot headless runs.

Usage:
  python az.py re campaign init                 # sync manifest -> per-build state
  python az.py re campaign status               # per-phase coverage
  python az.py re campaign add world-entry --target 0x146b6eb70 --note "inbound decode"
  python az.py re campaign expand world-entry 0x146b6eb70   # + callers of that VA
  python az.py re campaign run --phase login --batch 10
  python az.py re campaign run                  # next pending batch from any phase

A phase is "understood" only when its message contract and state transitions are
in `research/atlas/` with evidence labels; done here means decompiled and
reviewable, not verified semantics.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import decomp  # noqa: E402  (same tools directory, shares server + helpers)
from common import default_paths  # noqa: E402
from peutil import PEx  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "research" / "atlas" / "decomp-campaign.json"
STATE = decomp.WORK / "campaign-state.json"
OUT_DIR = decomp.WORK / "campaign"


def load_manifest() -> dict:
    if not MANIFEST.is_file():
        raise SystemExit(f"missing manifest: {MANIFEST}")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def save_manifest(manifest: dict) -> None:
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _spec_identity(spec: dict) -> tuple:
    """The declarative part of a spec, so a note change is not a new target."""
    for key in ("symbol", "va", "callers_of", "range"):
        if key in spec:
            return (key, spec[key])
    return ("unknown", json.dumps(spec, sort_keys=True))


def persist_spec_to_manifest(phase: str, spec: dict) -> bool:
    """Record a grown target in the committed manifest.

    `add`/`expand` are the documented growth path, but they used to write only
    the per-build state, which is ignored by git. The grown list therefore died
    with the workspace and did not exist on another machine (2026-10-09: a
    session grew the manifest to 108 targets on one host while the committed
    manifest still declared 45). The manifest is the phase map that `init`
    replays, so growth has to land there to be durable.
    """
    manifest = load_manifest()
    entry = next((p for p in manifest["phases"] if p["name"] == phase), None)
    if entry is None:
        entry = {"name": phase, "title": "", "targets": []}
        manifest["phases"].append(entry)
    identity = _spec_identity(spec)
    for existing in entry.setdefault("targets", []):
        if _spec_identity(existing) == identity:
            return False
    entry["targets"].append(spec)
    save_manifest(manifest)
    return True


def load_state() -> dict:
    if STATE.is_file():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"phases": {}}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def resolve(pex: PEx, spec: dict) -> list[tuple[int, int]]:
    """One spec -> exact .pdata ranges, snapped like decomp.resolve_targets."""
    if "symbol" in spec:
        symbols = decomp.load_symbols()
        sym = symbols.get(spec["symbol"])
        if not sym:
            raise SystemExit(
                f"unknown atlas symbol {spec['symbol']!r}; add it to "
                "research/atlas/client-functions.json first"
            )
        va = int(sym["va"].split("-")[0], 16)
        r = pex.func_at(va)
        if r is None:
            # A symbol whose VA is not inside a .pdata function can never become
            # a target (e.g. `login_error_enum`, which is a string blob in
            # .rdata, not code). Say so instead of dropping it silently, which
            # is how it sat in the manifest resolving to nothing.
            print(
                f"warning: symbol {spec['symbol']!r} at {hex(va)} is not inside "
                "a .pdata function; skipped"
            )
            return []
        return [r]
    if "va" in spec:
        va = int(spec["va"], 16)
        r = pex.func_at(va)
        if r is None:
            print(f"warning: {spec['va']} is not inside a .pdata function; skipped")
            return []
        return [r]
    if "callers_of" in spec:
        return list(pex.caller_funcs(int(spec["callers_of"], 16)))
    if "range" in spec:
        s, e = (int(x, 16) for x in spec["range"].split("-"))
        hit = decomp.pdata_overlap(pex, s, e)
        return hit or [(s, e)]
    raise SystemExit(f"target without va/symbol/range/callers_of: {spec}")


def cmd_init(pex: PEx, args: argparse.Namespace) -> int:
    manifest = load_manifest()
    state = load_state()
    phases = state.setdefault("phases", {})
    for phase in manifest["phases"]:
        name = phase["name"]
        entry = phases.setdefault(name, {"targets": {}})
        for spec in phase.get("targets", []):
            for start, end in resolve(pex, spec):
                key = f"{start:x}-{end:x}"
                entry["targets"].setdefault(
                    key,
                    {
                        "start": hex(start),
                        "end": hex(end),
                        "status": "pending",
                        "note": spec.get("note", ""),
                    },
                )
    save_state(state)
    return cmd_status(args)


def cmd_add(pex: PEx, args: argparse.Namespace) -> int:
    state = load_state()
    entry = state["phases"].setdefault(args.phase, {"targets": {}})
    spec: dict = {"note": args.note or ""}
    if args.target:
        spec["va"] = args.target
    elif args.callers_of:
        spec["callers_of"] = args.callers_of
    elif args.range:
        spec["range"] = args.range
    else:
        raise SystemExit("pass one of --target / --callers-of / --range")
    resolved = resolve(pex, spec)
    added = 0
    for start, end in resolved:
        key = f"{start:x}-{end:x}"
        if key not in entry["targets"]:
            entry["targets"][key] = {
                "start": hex(start),
                "end": hex(end),
                "status": "pending",
                "note": spec["note"],
            }
            added += 1
    save_state(state)
    # Keep the committed phase map in sync, or the growth is lost with the
    # build workspace. A spec that resolved to nothing is not recorded.
    persisted = persist_spec_to_manifest(args.phase, spec) if resolved else False
    suffix = " (manifest updated)" if persisted else ""
    print(f"[campaign] {args.phase}: +{added} target(s){suffix}")
    return 0


def cmd_expand(pex: PEx, args: argparse.Namespace) -> int:
    """Grow the phase with the callers of a VA (call-graph outward walk)."""
    args.target = None
    args.range = None
    args.callers_of = args.va
    args.note = args.note or f"callers of {args.va}"
    return cmd_add(pex, args)


def parse_output(text: str) -> list[str]:
    """Split one decomp output file into blocks, in request order.

    The Java helper writes, per requested range: a `FUNC name entry=0x.. body=N`
    line plus C, or a `NO FUNCTION` / `DECOMP-FAIL` / `ERR ` line. Ranges are
    processed in request order, so blocks pair with the requested list.
    """
    blocks: list[str] = []
    current: list[str] | None = None
    for line in text.splitlines(keepends=True):
        if line.startswith("FUNC "):
            if current is not None:
                blocks.append("".join(current))
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        blocks.append("".join(current))
    return blocks


def pending(state: dict, phase: str | None) -> list[tuple[str, dict]]:
    phases = state["phases"]
    names = [phase] if phase else list(phases)
    out: list[tuple[str, dict]] = []
    for name in names:
        if name not in phases:
            raise SystemExit(f"unknown phase {name!r}; run `campaign init` first")
        for key, t in phases[name]["targets"].items():
            if t["status"] == "pending":
                out.append((name, {**t, "key": key}))
    return out


def cmd_run(pex: PEx, args: argparse.Namespace) -> int:
    problems = decomp.check_install()
    if problems:
        for p in problems:
            print("MISSING " + p, file=sys.stderr)
        return 1
    state = load_state()
    queue = pending(state, args.phase)[: args.batch]
    if not queue:
        print("[campaign] nothing pending")
        return 0
    ranges = [(t["key"], int(t["start"], 16), int(t["end"], 16)) for _, t in queue]
    out_file = OUT_DIR / f"batch-{int(time.time())}.c"
    if decomp.server_pid():
        decomp.wait_ready(args.timeout)
        decomp.enqueue(ranges, out_file, args.timeout)
    else:
        decomp.run_ghidra(ranges, out_file, args.timeout)
    blocks = parse_output(out_file.read_text(encoding="utf-8", errors="replace"))
    if len(blocks) != len(queue):
        print(
            f"[campaign] warning: {len(blocks)} output blocks for "
            f"{len(queue)} requested ranges; pairing by order"
        )
    for (name, t), block in zip(queue, blocks):
        phase_dir = OUT_DIR / name
        phase_dir.mkdir(parents=True, exist_ok=True)
        func_file = phase_dir / f"{t['start']}-{t['end']}.c"
        ok = (
            bool(block)
            and "FUNC " in block
            and "DECOMP-FAIL" not in block
            and "ERR " not in block
            and "NO FUNCTION" not in block
        )
        func_file.write_text(block if block else "(no output)\n", encoding="utf-8")
        # pending() returns shallow copies; write the outcome into the real
        # state record or the ledger never advances past "pending".
        record = state["phases"][name]["targets"][t["key"]]
        record["status"] = "done" if ok else "failed"
        record["out"] = str(func_file.relative_to(decomp.WORK))
        t["status"] = record["status"]
    save_state(state)
    done = sum(1 for _, t in queue if t["status"] == "done")
    print(f"[campaign] batch: {done}/{len(queue)} decompiled -> {OUT_DIR}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state = load_state()
    total = {"pending": 0, "done": 0, "failed": 0}
    for name, entry in sorted(state.get("phases", {}).items()):
        counts = {"pending": 0, "done": 0, "failed": 0}
        for t in entry["targets"].values():
            counts[t["status"]] = counts.get(t["status"], 0) + 1
        for k in total:
            total[k] += counts[k]
        print(f"{name:16} done={counts['done']:4} pending={counts['pending']:4} failed={counts['failed']:3}")
    print(f"{'TOTAL':16} done={total['done']:4} pending={total['pending']:4} failed={total['failed']:3}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Incremental decompilation campaign")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="sync the manifest into per-build state")
    sub.add_parser("status", help="per-phase decompilation coverage")

    p_add = sub.add_parser("add", help="add a target to a phase")
    p_add.add_argument("phase")
    p_add.add_argument("--target", help="hex VA inside a function")
    p_add.add_argument("--callers-of", dest="callers_of", help="hex VA; add its callers")
    p_add.add_argument("--range", help="hex start-end")
    p_add.add_argument("--note")

    p_exp = sub.add_parser("expand", help="add the callers of a VA to a phase")
    p_exp.add_argument("phase")
    p_exp.add_argument("va", help="hex VA whose callers to add")
    p_exp.add_argument("--note")

    p_run = sub.add_parser("run", help="decompile the next pending batch")
    p_run.add_argument("--phase")
    p_run.add_argument("--batch", type=int, default=10)
    p_run.add_argument("--timeout", type=int, default=3600)

    args = ap.parse_args()
    pex = PEx(default_paths()["exe"])
    if args.cmd == "init":
        return cmd_init(pex, args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "add":
        return cmd_add(pex, args)
    if args.cmd == "expand":
        return cmd_expand(pex, args)
    if args.cmd == "run":
        return cmd_run(pex, args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
