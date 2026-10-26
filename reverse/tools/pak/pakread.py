#!/usr/bin/env python3
r"""Read and decode a single entry from a New World PAK.

Layer 2 tool (DECOMP-BACKLOG 2.1c/2.2). The standard-library ZIP reader
handles directory metadata but not method 15, so payloads are decoded from
the local header:

* Method 0: stored data.
* Method 8: raw deflate, as verified in PAK-FORMAT.md §3.
* Method 15: RAD Oodle Kraken through the vendored ooz decoder. Its C++ shim
  builds to `.azoth/tools/ooz/kraken.dll` when g++ or clang++ is available.
  The optional `kraken-decompressor` wheel is isolated in a subprocess because
  it can corrupt the heap for some payloads. Its one-time venv is kept under
  `.azoth/venvs/kraken`.

Every decoded payload is checked against the central-directory CRC-32; a
mismatch is a hard failure. This reads files on disk and never attaches to a
running process.

Usage:
    python ef.py re pak-read selftest
    python ef.py re pak-read read Engine.pak config/game.xml --out game.xml
    python ef.py re pak-read info SharedDataStrm.pak <entry-path>
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import default_paths  # noqa: E402

GROUND_TRUTH = ("Engine.pak", "config/game.xml")
GROUND_TRUTH_CRC = 0xF8ED6F3C


def _krakenv_dir() -> Path:
    return default_paths()["state"] / "venvs" / "kraken"


def _venv_python() -> Path:
    return _krakenv_dir() / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _dll_path() -> Path:
    return default_paths()["state"] / "tools" / "ooz" / "kraken.dll"

def _find_cxx() -> str | None:
    for name in ("g++", "clang++", "c++"):
        for d in os.environ.get("PATH", "").split(os.pathsep):
            p = Path(d)
            if p.joinpath(f"{name}.exe").exists() or p.joinpath(name).exists():
                return name
    return None

def _build_dll() -> Path | None:
    """Compile the vendored ooz decoder once (needs g++/clang++ on PATH)."""
    cxx = _find_cxx()
    if not cxx:
        return None
    vendor = Path(__file__).resolve().parents[1] / "vendor" / "ooz"
    out = _dll_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [cxx, "-shared", "-O2", "-static", "-o", str(out),
         str(vendor / "kraken.cpp"), str(vendor / "ooz_shim.cpp")],
        capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        print(f"ooz build failed: {r.stderr[-400:]}", file=sys.stderr)
        return None
    return out

def _decode_dll(payload: bytes, usize: int) -> bytes:
    path = _dll_path()
    if not path.exists():
        path = _build_dll()
    if not path or not path.exists():
        raise FileNotFoundError("ooz kraken.dll not built and no g++/clang++ on PATH")
    import ctypes
    dll = ctypes.CDLL(str(path))
    dll.ooz_decompress.restype = ctypes.c_int
    dll.ooz_decompress.argtypes = [ctypes.c_char_p, ctypes.c_size_t,
                                   ctypes.c_char_p, ctypes.c_size_t,
                                   ctypes.POINTER(ctypes.c_size_t)]
    dst = ctypes.create_string_buffer(usize)
    written = ctypes.c_size_t(0)
    rc = dll.ooz_decompress(payload, len(payload), dst, usize, ctypes.byref(written))
    if rc != 0:
        raise ValueError(f"ooz decode failed (rc={rc})")
    return dst.raw[:written.value]

def _ensure_decoder() -> None:
    """Import kraken_decompressor, bootstrapping its project-local venv if needed."""
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

def _decode_wheel_subprocess(payload: bytes, usize: int) -> bytes:
    """Fallback: the kraken-decompressor wheel, isolated in a subprocess.

    The wheel allocates exactly dst_len while ooz may write up to 64 bytes
    past it, so SOME payloads crash the child process (0xc0000374). Isolating
    the call keeps pakread alive; a crashed child is a failed decode, never a
    corrupt result. The DLL path above is the fix (vendor/ooz/README.md).
    """
    _ensure_decoder()
    code = (
        "import sys\n"
        "from kraken_decompressor import decompress\n"
        "payload = sys.stdin.buffer.read()\n"
        f"sys.stdout.buffer.write(decompress(payload, {usize}))\n"
    )
    r = subprocess.run([str(_venv_python()), "-c", code], input=payload,
                       capture_output=True, timeout=300)
    if r.returncode != 0:
        raise ValueError(f"wheel decoder crashed (rc={r.returncode})")
    return r.stdout


def decode(payload: bytes, method: int, usize: int, crc: int, label: str) -> bytes:
    if method == 0:
        out = payload
    elif method == 8:
        out = zlib.decompressobj(-15).decompress(payload)
    elif method == 15:
        try:
            out = _decode_dll(payload, usize)
        except (FileNotFoundError, OSError) as e:
            print(f"ooz DLL unavailable ({e}); falling back to wheel subprocess",
                  file=sys.stderr)
            out = _decode_wheel_subprocess(payload, usize)
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
    # the wheel-crasher regression: the ooz DLL must decode it exactly
    # (first reproduction of the heap corruption, 2026-10-05)
    perks, pmeta = read_entry(
        "SharedDataStrm-part6.pak",
        "sharedassets/springboardentitites/datatables/javelindata_perks.datasheet")
    checks.append(("perks datasheet decodes (wheel-crasher regression)",
                   len(perks) == 305638 and pmeta["crc"] == "5c661d7f"))
    # the documented header-exception entry (PAK-FORMAT.md §4a)
    dds, _ = read_entry("Engine.pak", "engineassets/animated/watervolume.dds")
    checks.append(("dds header-exception decodes", len(dds) == 524416))
    # a method-8 entry through the same path
    con = __import__("sqlite3").connect(
        default_paths()["state"] / "cache" / "pak-index" / "pakindex.db")
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
