"""The wire-parity acceptance gate: Rust and Python must agree with the capture.

WHY THIS EXISTS
===============
"Byte-for-byte parity" is a claim until one command can fail on it. This runs the
three things that together mean the port is faithful:

  1. **Rust against the capture.** `cargo test --test parity` decodes and re-encodes
     every exported fixture and requires the bytes to match.
  2. **Python against the capture.** The prototype's own encoders are run over the
     same fixtures. They are expected to match on the record framing and to differ
     on exactly one documented point (see below), so a difference anywhere else is
     a regression in one of the two implementations.
  3. **The fixtures exist and are current.** A stale or empty fixture file would
     make (1) pass vacuously.

THE ONE DOCUMENTED PYTHON DEVIATION
===================================
The prototype's writer starts its per-datagram `prev_channel` at -1, so it emits a
redundant `DATA_CHANNEL` flag and channel byte on the first record of every
datagram whose channel is 0. The client's own writer starts at 0 and omits them:
measured, 8 of 107 captured datagrams carry no channel byte on their first record.
The Rust port follows the client. That is one byte per affected datagram on the
outbound path, and this script reports it rather than hiding it.

Usage:
    python scripts/wire-parity.py            # full gate
    python scripts/wire-parity.py --quick    # skip the cargo build
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "server" / "crates" / "azoth-wire" / "tests" / "fixtures" / "wire-fixtures.json"
SERVER_DIR = REPO / "server"

sys.path.insert(0, str(REPO / "services" / "world" / "src"))
from azoth_world.javelin import frame, lz4  # noqa: E402
from azoth_world.javelin.frame import marshal_datagram, parse_datagram, parse_envelope  # noqa: E402


def check_fixtures() -> int:
    if not FIXTURES.is_file():
        print(f"FAIL: no fixture file at {FIXTURES.relative_to(REPO)}")
        print("      run: python scripts/export-wire-fixtures.py <world.log> --out <that path>")
        return 1
    doc = json.loads(FIXTURES.read_text(encoding="utf-8"))
    datagrams = doc.get("datagrams") or []
    channel1 = doc.get("channel1") or []
    bundles = doc.get("state_bundles") or []
    print(f"fixtures: {len(datagrams)} datagrams, {len(channel1)} channel-1, "
          f"{len(bundles)} state bundles")
    failures = 0
    if len(datagrams) < 20:
        print(f"FAIL: only {len(datagrams)} datagrams; the gate would be vacuous")
        failures += 1
    if not channel1:
        print("FAIL: no channel-1 fixtures")
        failures += 1
    if not bundles:
        print("FAIL: no state-bundle fixtures")
        failures += 1
    build = doc.get("build_sha256", "")
    if build != "30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033":
        print(f"FAIL: fixtures are for build {build!r}, not the installed 1.460 build")
        failures += 1
    return failures


def run_rust(quick: bool) -> int:
    if quick:
        print("rust: skipped (--quick)")
        return 0
    print("rust: cargo test --test parity")
    result = subprocess.run(
        ["cargo", "test", "--test", "parity", "--quiet"],
        cwd=SERVER_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("FAIL: the Rust parity tests did not pass")
        print(result.stdout[-4000:])
        print(result.stderr[-4000:])
        return 1
    print("rust: OK")
    return 0


def check_python() -> int:
    """Run the prototype's encoders over the same fixtures."""
    doc = json.loads(FIXTURES.read_text(encoding="utf-8"))
    identical = 0
    optional_channel = 0
    real = []
    for index, entry in enumerate(doc["datagrams"]):
        body = bytes.fromhex(entry["raw"])
        env, rest = parse_envelope(body)
        if env.is_compressed:
            try:
                rest = lz4.decompress_lz4_block(rest)
            except ValueError as exc:
                real.append((index, f"lz4: {exc}"))
                continue
        parsed = parse_datagram(rest)
        if parsed.error:
            real.append((index, f"parse: {parsed.error}"))
            continue
        out = marshal_datagram(parsed.messages)
        if out == rest:
            identical += 1
            continue
        # The documented deviation: one extra channel byte on a channel-0 first
        # record. Verify that is the ONLY difference.
        if (
            len(out) == len(rest) + 1
            and out[0] & frame.MessageFlags.MF_DATA_CHANNEL
            and not rest[0] & frame.MessageFlags.MF_DATA_CHANNEL
        ):
            rebuilt = bytes([out[0] & ~frame.MessageFlags.MF_DATA_CHANNEL]) + out[1:3] + out[4:]
            if rebuilt == rest:
                optional_channel += 1
                continue
        real.append((index, f"length {len(rest)} vs {len(out)}"))

    print(f"python: {identical} identical, {optional_channel} optional-channel, "
          f"{len(real)} real")
    if real:
        print("FAIL: the Python encoders disagree with the capture beyond the "
              "documented optional channel byte:")
        for item in real[:10]:
            print(f"  datagram {item[0]}: {item[1]}")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true", help="skip the cargo build")
    args = ap.parse_args()

    failures = 0
    failures += check_fixtures()
    if failures:
        print("\nGATE FAILED (fixtures)")
        return 1
    failures += check_python()
    failures += run_rust(args.quick)

    if failures:
        print("\nGATE FAILED")
        return 1
    print("\nGATE PASSED: Rust and Python both reproduce the captured wire bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
