#!/usr/bin/env python3
"""Strings y PE del EXE en disco. No es memoria del proceso en ejecucion."""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    INTERESTING_HOST_RE,
    URL_RE,
    default_paths,
    ensure_dir,
    write_json,
)

NEEDLES = (
    "https://",
    "http://",
    "cloudfront",
    "amazonaws",
    "amazongames",
    "execute-api",
    "tokenservice",
    "Omni",
    "Javelin",
    "GridMate",
    "AuthManager",
    "GameConnection",
    "WaitingForREP",
    "credentials/omni",
    "DTLS",
    "ECDHE-RSA-AES256-GCM-SHA384",
    "EasyAntiCheat",
    "Campfire",
    "Slayer",
    "Coatlicue",
    "Vivox",
    "STEAM_APP",
    "BEGIN CERTIFICATE",
    "BEGIN PRIVATE",
)


def extract_ascii(exe: Path, min_len: int = 8):
    urls: set[str] = set()
    interesting: list[str] = []
    certs: list[str] = []
    buf = bytearray()
    n = 0
    in_pem = False
    pem: list[str] = []
    with exe.open("rb") as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)
            if not chunk:
                break
            for b in chunk:
                if 32 <= b < 127:
                    buf.append(b)
                else:
                    if len(buf) >= min_len:
                        s = buf.decode("ascii")
                        n += 1
                        if any(x in s for x in NEEDLES):
                            interesting.append(s)
                            for u in URL_RE.findall(s):
                                urls.add(u)
                        if "BEGIN CERTIFICATE" in s:
                            in_pem = True
                            pem = [s]
                        elif in_pem:
                            pem.append(s)
                            if "END CERTIFICATE" in s:
                                certs.append("\n".join(pem))
                                in_pem = False
                                pem = []
                    buf.clear()
    return n, sorted(set(interesting)), sorted(urls), certs


def pe_imports(exe: Path) -> dict:
    """Tabla de imports PE32+ (aprox.). Sirve para ver ws2_32, secur32, steam, eac."""
    data = exe.read_bytes()
    if data[:2] != b"MZ":
        return {"error": "not MZ"}
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew : e_lfanew + 4] != b"PE\x00\x00":
        return {"error": "not PE"}
    magic = struct.unpack_from("<H", data, e_lfanew + 24)[0]
    # PE32+ optional header: Import Directory RVA at +120 from optional header start
    # optional starts at e_lfanew+24
    if magic != 0x20B:
        return {"error": f"optional magic {magic:#x} (need PE32+)"}
    import_rva, import_size = struct.unpack_from("<II", data, e_lfanew + 24 + 120)
    num_sections = struct.unpack_from("<H", data, e_lfanew + 6)[0]
    opt_size = struct.unpack_from("<H", data, e_lfanew + 20)[0]
    sec_off = e_lfanew + 24 + opt_size
    sections = []
    for i in range(num_sections):
        o = sec_off + i * 40
        name = data[o : o + 8].split(b"\x00", 1)[0].decode("ascii", "replace")
        vsize, va, rsize, raw = struct.unpack_from("<IIII", data, o + 8)
        sections.append((name, va, vsize, raw, rsize))

    def rva_to_off(rva: int) -> int | None:
        for _, va, vsize, raw, rsize in sections:
            if va <= rva < va + max(vsize, rsize):
                return raw + (rva - va)
        return None

    dlls = []
    off = rva_to_off(import_rva)
    if off is None:
        return {
            "sections": [s[0] for s in sections],
            "import_rva": import_rva,
            "dlls": [],
        }
    while True:
        lookup, _t, _f, name_rva, iat = struct.unpack_from("<IIIII", data, off)
        if lookup == 0 and name_rva == 0:
            break
        no = rva_to_off(name_rva)
        dll = ""
        if no is not None:
            end = data.index(b"\x00", no)
            dll = data[no:end].decode("ascii", "replace")
        dlls.append(dll)
        off += 20
        if len(dlls) > 400:
            break
    interesting = [
        d
        for d in dlls
        if any(
            x in d.lower()
            for x in (
                "ws2",
                "winhttp",
                "wininet",
                "secur32",
                "crypt",
                "ssl",
                "steam",
                "eac",
                "easy",
                "vivox",
                "bink",
            )
        )
    ]
    return {
        "sections": [
            {"name": n, "va": va, "vsize": vs, "raw": raw}
            for n, va, vs, raw, _ in sections
        ],
        "dlls_count": len(dlls),
        "dlls": dlls,
        "network_related": interesting,
    }


def run(exe: Path, out: Path) -> None:
    ensure_dir(out)
    print(f"Leyendo {exe} ({exe.stat().st_size} bytes)...")
    n, interesting, urls, certs = extract_ascii(exe)
    (out / "interesting_strings.txt").write_text(
        "\n".join(interesting) + "\n", encoding="utf-8"
    )
    (out / "urls.txt").write_text("\n".join(urls) + "\n", encoding="utf-8")
    hosts = sorted({s for s in interesting if INTERESTING_HOST_RE.search(s)})
    (out / "hosts_raw.txt").write_text("\n".join(hosts) + "\n", encoding="utf-8")
    if certs:
        (out / "embedded_certs.pem").write_text(
            "\n\n".join(certs) + "\n", encoding="utf-8"
        )
    pe = pe_imports(exe)
    write_json(out / "pe_imports.json", pe)
    write_json(
        out / "summary.json",
        {
            "exe": str(exe),
            "ascii_strings": n,
            "interesting": len(interesting),
            "urls": len(urls),
            "certs": len(certs),
            "network_dlls": pe.get("network_related"),
        },
    )
    print(
        json.dumps(
            {"interesting": len(interesting), "urls": len(urls), "certs": len(certs)}
        )
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe")
    ap.add_argument("--out")
    args = ap.parse_args()
    p = default_paths()
    exe = Path(args.exe) if args.exe else p["exe"]
    out = Path(args.out) if args.out else p["repo"] / "sessions" / "static_exe"
    run(exe, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
