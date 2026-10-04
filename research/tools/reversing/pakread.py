#!/usr/bin/env python3
"""Read and decode a single entry from a New World PAK, any compression method.

Layer 2 tool (DECOMP-BACKLOG 2.1c/2.2). Stdlib `zipfile` reads the directory
metadata but raises on method 15, so the payload is read manually from the
local header and decoded here:

* method 0  — stored (as-is)
* method 8  — raw deflate, no zlib wrapper (`zlib.decompressobj(-15)`), the
  Lumberyard `ICryPak.h` convention, verified in PAK-FORMAT.md §3
* method 15 — RAD Oodle **Kraken**, via the third-party `kraken-decompressor`
  wheel (a C++ port of the ooz-family Kraken decoder). Validated 2026-10-05:
  31/31 exact CRC matches against this install (PAK-FORMAT.md §4f). The wheel
  is bootstrapped ONCE into `%LOCALAPPDATA%\\Azoth\\tools\\krakenv` (gitignored,
  like the Ghidra install); `services/` stays stdlib-only per repo rules.

Every decode is verified against the ZIP central-directory CRC-32. A mismatch
is a hard failure, never a warning.

Disk only. Never touches a running process.

Usage:
    python research/tools/reversing/pakread.py selftest
    python research/tools/reversing/pakread.py read Engine.pak config/game.xml --out game.xml
    python research/tools/reversing/pakread.py info SharedDataStrm.pak <entry-path>
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import default_paths  # noqa: E402

GROUND_TRUTH = ("Engine.pak", "config/game.xml")
GROUND_TRUTH_CRC = 0xF8ED6F3C


def _krakenv_dir() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "Azoth" / "tools" / "krakenv"


def _venv_python() -> Path:
    return _krakenv_dir() / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _ensure_decoder() -> None:
    """Import kraken_decompressor, bootstrapping the LOCALAPPDATA venv if needed."""
    try:
        import kraken_decompressor  # noqa: F401
        return
    except ImportError:
        pass
    venv = _krakenv_dir()
    if not _venv_python().exists():
        print(f"bootstrapping Oodle reader venv -> {venv} (one-time, needs network)", file=sys.stderr)
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        subprocess.run([str(_venv_python()), "-m", "pip", "install", "--quiet",
                        "kraken-decompressor"], check=True)
    # Same interpreter major.minor: the wheel is a compiled C extension.
    if sys.version_info[:2] == (3, 14) and os.name == "nt":
        for sp in (_krakenv_dir() / "Lib" / "site-packages",):
            if sp.exists():
                sys.path.insert(0, str(sp))
                import kraken_decompressor  # noqa: F401
                return
    # Different interpreter: re-exec under the venv python, transparently.
    if "--reexeced" not in sys.argv:
        os.execv(str(_venv_python()), [str(_venv_python()), __file__, "--reexeced", *sys.argv[1:]])
    raise RuntimeError("kraken-decompressor unavailable after bootstrap")


def decode(payload: bytes, method: int, usize: int, crc: int, label: str) -> bytes:
    if method == 0:
        out = payload
    elif method == 8:
        out = zlib.decompressobj(-15).decompress(payload)
    elif method == 15:
        _ensure_decoder()
        from kraken_decompressor import decompress
        out = decompress(payload, usize)
    else:
        raise NotImplementedError(f"compression method {method} not supported")
    got = zlib.crc32(out)
    if len(out) != usize or got != crc:
        raise ValueError(
            f"{label}: decode FAILED (got {len(out)} B crc={got:08x}, "
            f"expected {usize} B crc={crc:08x})")
    return out


def read_entry(pak_rel: str, entry: str) -> tuple[bytes, dict]:
    pak = default_paths()["install"] / "assets" / pak_rel
    with zipfile.ZipFile(pak) as z:
        info = z.getinfo(entry)
        with open(pak, "rb") as f:
            f.seek(info.header_offset)
            lh = f.read(30)
            if lh[:4] != b"PK\x03\x04":
                raise ValueError(f"{pak_rel}::{entry}: bad local header")
            nlen, elen = struct.unpack("<HH", lh[26:30])
            f.seek(info.header_offset + 30 + nlen + elen)
            payload = f.read(info.compress_size)
    meta = {
        "pak": pak_rel, "path": entry, "method": info.compress_type,
        "csize": info.compress_size, "usize": info.file_size,
        "crc": f"{info.CRC:08x}",
    }
    return decode(payload, info.compress_type, info.file_size, info.CRC,
                  f"{pak_rel}::{entry}"), meta


def cmd_read(pak_rel: str, entry: str, out: str | None) -> int:
    data, meta = read_entry(pak_rel, entry)
    meta["sha256"] = hashlib.sha256(data).hexdigest()
    if out:
        Path(out).write_bytes(data)
        print(json.dumps(meta, indent=1))
    else:
        sys.stdout.buffer.write(data)
    return 0


def cmd_info(pak_rel: str, entry: str) -> int:
    data, meta = read_entry(pak_rel, entry)
    meta["decoded_bytes"] = len(data)
    print(json.dumps(meta, indent=1))
    return 0


def selftest() -> int:
    checks: list[tuple[str, bool]] = []
    data, meta = read_entry(*GROUND_TRUTH)
    checks.append(("ground truth decodes (game.xml, method 15)", data[:13] == b"<ObjectStream"))
    checks.append(("ground truth CRC matches", meta["crc"] == f"{GROUND_TRUTH_CRC:08x}"))
    # the documented header-exception entry (PAK-FORMAT.md §4a)
    dds, _ = read_entry("Engine.pak", "engineassets/animated/watervolume.dds")
    checks.append(("dds header-exception decodes", len(dds) == 524416))
    # a method-8 entry through the same path
    con = __import__("sqlite3").connect(
        Path(os.environ["LOCALAPPDATA"]) / "Azoth" / "pakindex" / "pakindex.db")
    row = con.execute(
        "SELECT pak, path FROM entry WHERE method=8 LIMIT 1").fetchone()
    if row is None:
        checks.append(("method-8 sample (run pakindex.py build first)", False))
    else:
        try:
            read_entry(row[0], row[1])
            checks.append((f"method-8 entry decodes ({row[0]}::{row[1]})", True))
        except Exception as e:  # noqa: BLE001
            print(f"  {e}")
            checks.append(("method-8 entry decodes", False))
    ok = all(v for _, v in checks)
    for name, v in checks:
        print(f"{'PASS' if v else 'FAIL'} {name}")
    print(f"selftest: {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


def main() -> int:
    argv = [a for a in sys.argv[1:] if a != "--reexeced"]
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "selftest":
        return selftest()
    if cmd == "read" and len(argv) >= 3:
        out = argv[argv.index("--out") + 1] if "--out" in argv else None
        return cmd_read(argv[1], argv[2], out)
    if cmd == "info" and len(argv) >= 3:
        return cmd_info(argv[1], argv[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
