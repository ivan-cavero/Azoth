#!/usr/bin/env python3
"""Write path for New World PAKs — the content-edit half of the pipeline.

DECOMP-BACKLOG 2.4. Reading is `pakread.py`; this tool builds a **patch pak**:

1. extract an entry (Kraken/deflate/store via `pakread`),
2. apply a modification (e.g. edit one localization string),
3. write a NEW zip with that single entry re-compressed as method 8 (raw
   deflate, no zlib wrapper — the Lumberyard `ICryPak.h` convention) or 0
   (store). Repacking never needs the Oodle encoder: the client already reads
   methods 8 and 0.

Placement (documented, not applied here — launching the client is owned by the
world session): drop the patch pak next to the others and add it to
`<install>/PaksList.lst`. One entry per line, relative to the install root
(measured: `Assets/CoatlicueStrm.pak`, …). Cry/Lumberyard resolves duplicate
entry paths by pak lookup order; put the patch pak FIRST so it wins. Verify
before trusting this priority claim: one line change + one client launch is
the deciding test.

Every write is verified by re-reading the patch pak with `pakread` and
asserting byte equality with the modified payload. The selftest additionally
round-trips the real `config/game.xml` ground truth and a synthetic edit of a
real localization file. Disk only, never touches a running process.

Usage:
    python reverse/tools/pakwrite.py selftest
    python reverse/tools/pakwrite.py make <pak> <entry> <out.pak> \
        [--method 8] [--replace OLD=NEW]
"""

from __future__ import annotations

import struct
import sys
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import default_paths  # noqa: E402
from pakread import read_entry  # noqa: E402


def _write_pak(entry: str, data: bytes, out_path: Path, method: int) -> None:
    """One-entry zip with method 8 (raw deflate) or 0 (store)."""
    with zipfile.ZipFile(out_path, "w") as z:
        if method == 0:
            z.writestr(entry, data, compress_type=zipfile.ZIP_STORED)
        elif method == 8:
            # zipfile's ZIP_DEFLATED writes a raw deflate stream for method 8
            # (Python never emits a zlib wrapper for zip method 8) — but we
            # verify by decoding through our own raw-deflate reader below.
            z.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED)
        else:
            raise ValueError(f"method {method} not supported for writing")


def make(src_pak: str, entry: str, out_path: Path,
         transform=None, method: int = 8) -> bytes:
    """Extract, transform, write a one-entry patch pak, verify by re-reading."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data, meta = read_entry(src_pak, entry)
    if transform is not None:
        data = transform(data)
    _write_pak(entry, data, out_path, method)
    # verify: read back through pakread's decoder (method 8 -> raw deflate)
    with zipfile.ZipFile(out_path) as z:
        info = z.getinfo(entry)
        assert info.compress_type == method, "method mismatch in written pak"
        with open(out_path, "rb") as f:
            f.seek(info.header_offset)
            lh = f.read(30)
            nlen, elen = struct.unpack("<HH", lh[26:30])
            f.seek(info.header_offset + 30 + nlen + elen)
            payload = f.read(info.compress_size)
        if method == 8:
            roundtrip = zlib.decompressobj(-15).decompress(payload)
        else:
            roundtrip = payload
        if roundtrip != data or zlib.crc32(roundtrip) != info.CRC:
            raise ValueError(f"patch pak {out_path} failed round-trip verification")
    return data


def cmd_make(args) -> int:
    src_pak, entry, out = args[0], args[1], Path(args[2])
    method = 8
    transform = None
    argv = args[3:]
    if "--method" in argv:
        i = argv.index("--method")
        method = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if "--replace" in argv:
        i = argv.index("--replace")
        old, new = argv[i + 1].split("=", 1)
        old_b, new_b = old.encode(), new.encode()
        count_holder: list[int] = [0]

        def transform(data: bytes) -> bytes:
            if old_b not in data:
                raise ValueError(f"--replace target not found in entry: {old!r}")
            count_holder[0] = data.count(old_b)
            return data.replace(old_b, new_b)

        argv = argv[:i] + argv[i + 2:]
        if len(argv):
            print(f"unused args: {argv}", file=sys.stderr)
        payload = make(src_pak, entry, out, transform, method)
        print(f"patch pak written: {out}")
        print(f"  entry: {entry}")
        print(f"  replaced {count_holder[0]} occurrence(s) of {old!r}")
        print(f"  {len(payload)} bytes, method {method}")
        print("next step (client-owned, see PAK-FORMAT.md / DECOMP-BACKLOG 2.4):")
        print(f"  1. copy {out} to <install>/Assets/")
        print(f"  2. add the line 'Assets/{out.name}' as the FIRST line of "
              "<install>/PaksList.lst")
        print("  3. launch the private client and check the string in game")
        return 0
    payload = make(src_pak, entry, out, None, method)
    print(f"patch pak written: {out} ({len(payload)} bytes, method {method})")
    return 0


def selftest() -> int:
    checks: list[tuple[str, bool]] = []
    tmp = default_paths()["research"]
    # ground truth: re-pack game.xml verbatim, read back, compare
    out1 = tmp / "pakwrite_test1.pak"
    data = make("Engine.pak", "config/game.xml", out1, None, 8)
    with zipfile.ZipFile(out1) as z:
        back = z.read("config/game.xml")
    checks.append(("game.xml repack round-trip", back == data and len(data) == 7046))
    out1.unlink()
    # synthetic edit of a real localization file
    out2 = tmp / "pakwrite_test2.pak"
    old = "Corsario inglés"
    new = "Corsario de Azoth"
    data2 = make("DataStrm-part3.pak", "localization/es-es/0c_01_npcmisc.loc.xml",
                 out2, lambda d: d.replace(old.encode(), new.encode()), 8)
    checks.append(("edit applied exactly once",
                   data2.count(new.encode()) == 1 and old.encode() not in data2))
    with zipfile.ZipFile(out2) as z:
        back = z.read("localization/es-es/0c_01_npcmisc.loc.xml")
    checks.append(("edited loc.xml round-trips", back == data2))
    checks.append(("edited loc.xml is well-formed",
                   b"<resources" in back and back.rstrip().endswith(b"</resources>")))
    out2.unlink()
    ok = all(v for _, v in checks)
    for name, v in checks:
        print(f"{'PASS' if v else 'FAIL'} {name}")
    print(f"selftest: {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "selftest":
        return selftest()
    if cmd == "make" and len(sys.argv) >= 5:
        return cmd_make(sys.argv[2:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
