#!/usr/bin/env python3
"""PE/RE catalog extractor: turn NewWorld.exe into machine-readable JSON.

The emulator is data-driven: every endpoint, model, enum, cvar and host it needs
already exists as a string or a table inside the client binary. This tool dumps
those into `research/derived/*.json` so gateway code consumes a versioned
artifact instead of ad-hoc archaeology per session.

Disk only. Never opens the game process (see reverse/tools/memory.py for that rule).

Sections (each also printed as a short report):
  pe          section map + file-offset <-> VA helpers, xref scanner
  routes      REST paths (/prod/..., /game/...) + operation names
  models      *RequestBody/*ResponseBody names + their member-key tables
  enums       candidate value sets for enum-typed members (with xref evidence)
  grpc        /Javelin.RPC.<service>/<method>
  config      client-connection.*, javelin.*, g_*, lc_*, log_*, sys_*, flb_*
  stubs       Stubbed*Service classes + _persistence/* files
  assets      @assets@/... and @savedata@/... paths
  hosts       domains + emulator role

Usage:
  python reverse/tools/catalog.py [--exe PATH] [--out research/derived]
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import default_paths, role_for_host, write_json  # noqa: E402

# ---------------------------------------------------------------- PE helpers


class PE:
    """Minimal PE reader: sections, offset<->VA, RIP-relative xrefs."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = path.read_bytes()
        data = self.data
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe : pe + 4] != b"PE\0\0":
            raise ValueError(f"not a PE file: {path}")
        nsec = struct.unpack_from("<H", data, pe + 6)[0]
        optsz = struct.unpack_from("<H", data, pe + 20)[0]
        self.image_base = struct.unpack_from("<Q", data, pe + 24 + 24)[0]
        self.sections: list[dict] = []
        off = pe + 24 + optsz
        for i in range(nsec):
            o = off + i * 40
            name = data[o : o + 8].rstrip(b"\0").decode("latin-1")
            vsize, vaddr, rsize, raw = struct.unpack_from("<IIII", data, o + 8)
            self.sections.append(
                {
                    "name": name,
                    "va": self.image_base + vaddr,
                    "vsize": vsize,
                    "raw": raw,
                    "rsize": rsize,
                }
            )

    def section(self, name: str) -> dict:
        for s in self.sections:
            if s["name"] == name:
                return s
        raise KeyError(name)

    def foff_to_va(self, fo: int) -> int | None:
        for s in self.sections:
            if s["raw"] <= fo < s["raw"] + s["rsize"]:
                return s["va"] + (fo - s["raw"])
        return None

    def va_to_foff(self, va: int) -> int | None:
        for s in self.sections:
            if s["va"] <= va < s["va"] + s["rsize"]:
                return s["raw"] + (va - s["va"])
        return None

    def read_va(self, va: int, n: int) -> bytes:
        fo = self.va_to_foff(va)
        if fo is None:
            return b""
        return self.data[fo : fo + n]

    def cstring_at(self, fo: int, limit: int = 200) -> str:
        end = self.data.find(b"\0", fo, fo + limit)
        if end < 0:
            end = fo + limit
        return self.data[fo:end].decode("latin-1", "replace")

    def find_all(self, needle: bytes) -> list[int]:
        """All file offsets of a literal byte string (no re.escape pitfalls)."""
        out, start = [], 0
        while True:
            i = self.data.find(needle, start)
            if i < 0:
                return out
            out.append(i)
            start = i + 1

    def xrefs_to_va(
        self, va: int, rex: tuple[int, ...] = (0x48, 0x4C, 0x49, 0x4D)
    ) -> list[int]:
        """File offsets of `lea r64, [rip+disp32]` instructions targeting va.

        x64 RIP-relative addressing needs REX.W; the reg field is free, so accept
        the REX bytes that carry W (0x48 | reg bits) and ModRM with mod=00, rm=101.
        """
        text = self.section(".text")
        data = self.data
        lo, hi = text["raw"], text["raw"] + text["rsize"] - 7
        hits = []
        for i in range(lo, hi):
            if data[i] not in rex or data[i + 1] != 0x8D:
                continue
            if (data[i + 2] & 0xC7) != 0x05:
                continue
            disp = struct.unpack_from("<i", data, i + 3)[0]
            own = self.foff_to_va(i)
            if own is not None and own + 7 + disp == va:
                hits.append(i)
        return hits

    def strings_in(
        self, va_start: int, va_end: int, min_len: int = 2
    ) -> list[tuple[int, str]]:
        fo_s, fo_e = self.va_to_foff(va_start), self.va_to_foff(va_end)
        if fo_s is None or fo_e is None:
            return []
        out = []
        for m in re.finditer(rb"[\x20-\x7e]{%d,}" % min_len, self.data[fo_s:fo_e]):
            out.append((self.foff_to_va(fo_s + m.start()), m.group().decode("latin-1")))
        return out


# ---------------------------------------------------------------- extractors

OPERATION_BLOCK = re.compile(
    rb"\b(Get|List|Post|Patch|Delete|Queue|Refresh|Link|Unlink|Validate)[A-Za-z]{4,60}\b"
)
ROUTE_RE = re.compile(
    rb"/(?:prod|game|players|applications|newsstories|marketingtiles|motd|images|auth)(?:/[A-Za-z0-9_%\.\-\*]+)*"
)
GRPC_RE = re.compile(rb"/Javelin\.RPC\.[A-Za-z0-9_]+/[A-Za-z0-9_]+")
MODEL_RE = re.compile(
    rb"[A-Za-z][A-Za-z0-9]{3,60}(?:RequestBody|ResponseBody|Result|Request)"
)
STUB_RE = re.compile(rb"Stubbed[A-Za-z]{3,40}")
PERSIST_RE = re.compile(rb"_persistence/[A-Za-z0-9_\.\-/]{1,60}")
ASSET_RE = re.compile(
    rb"@(?:assets|savedata|error_loading_assets|savedata_)[A-Za-z0-9_/@\.\-]{2,80}"
)
HOST_RE = re.compile(
    rb"[a-z0-9][a-z0-9\-\.]{3,60}\.(?:amazongames\.com|cloudfront\.net|amazonaws\.com|newworld\.com|vivox\.com)"
)
CONFIG_RE = re.compile(
    rb"(?:client-connection|javelin|g|lc|log|sys|flb|r|bg|net|http|aws|s3|omni|persona)"
    rb"[\.\-_][A-Za-z0-9_\.\-]{3,70}"
)

# members whose enum values matter for the emulator (RE'd member names)
ENUM_MEMBERS = (
    "WorldStatus",
    "WorldType",
    "WorldPopulationStatus",
    "RecommendationType",
    "TransferToRegion",
    "IsRecommended",
    "FilterType",
    "AccountIsLocked",
)

MODEL_KEY_WINDOW = 0x1200  # bytes around a model name to look for its key table


def section_routes(pe: PE) -> dict:
    routes = sorted({m.group().decode("latin-1") for m in ROUTE_RE.finditer(pe.data)})
    ops = sorted(
        {m.group().decode("latin-1") for m in OPERATION_BLOCK.finditer(pe.data)}
    )
    # the exact operation/path pair table sits contiguously right after "/prod"
    fo = pe.data.find(b"/prod\0")
    table: list[str] = []
    if fo > 0:
        end = pe.data.find(b"x-nw-auth", fo)
        chunk = pe.data[fo : end if end > 0 else fo + 2000]
        table = [s.decode("latin-1") for s in re.findall(rb"[\x20-\x7e]{3,}", chunk)]
    return {"routes": routes, "operations": ops, "path_table": table}


def section_models(pe: PE) -> dict:
    names = sorted({m.group().decode("latin-1") for m in MODEL_RE.finditer(pe.data)})
    models: dict[str, dict] = {}
    for name in names:
        fo = pe.data.find(name.encode() + b"\0")
        if fo < 0:
            continue
        va = pe.foff_to_va(fo)
        keys: list[str] = []
        if va is not None:
            s, e = va - MODEL_KEY_WINDOW // 2, va + MODEL_KEY_WINDOW // 2
            for _, txt in pe.strings_in(s, e, min_len=3):
                if txt == name or txt in keys:
                    continue
                keys.append(txt)
        models[name] = {"va": hex(va) if va else None, "nearby_keys": keys}
    return models


def section_enums(pe: PE) -> dict:
    """For each enum member: where the literal lives, who reads it, what neighbours."""
    out: dict[str, dict] = {}
    for member in ENUM_MEMBERS:
        fo = pe.data.find(member.encode() + b"\0")
        if fo < 0:
            out[member] = {"found": False}
            continue
        va = pe.foff_to_va(fo)
        xrefs = pe.xrefs_to_va(va) if va else []
        # candidate values: short capitalised tokens in the same cluster
        values: list[str] = []
        if va is not None:
            for _, txt in pe.strings_in(va - 400, va + 400, min_len=3):
                if re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-]{2,30}", txt):
                    values.append(txt)
        out[member] = {
            "found": True,
            "va": hex(va) if va is not None else None,
            "file_offset": hex(fo),
            "xrefs": len(xrefs),
            "xref_offsets": [hex(x) for x in xrefs[:10]],
            "cluster": values[:40],
        }
    return out


def section_grpc(pe: PE) -> dict:
    full = sorted({m.group().decode("latin-1") for m in GRPC_RE.finditer(pe.data)})
    services: dict[str, list[str]] = {}
    for f in full:
        _, _, rest = f.partition("Javelin.RPC.")
        svc, _, method = rest.partition("/")
        services.setdefault(svc, []).append(method)
    return {"endpoints": full, "services": services}


def section_config(pe: PE) -> dict:
    keys = sorted({m.group().decode("latin-1") for m in CONFIG_RE.finditer(pe.data)})
    groups: dict[str, list[str]] = {}
    for k in keys:
        groups.setdefault(k.split(".", 1)[0].split("-", 1)[0], []).append(k)
    return {"count": len(keys), "groups": groups}


def _plain(pe: PE, rx: re.Pattern[bytes]) -> list[str]:
    return sorted({m.group().decode("latin-1") for m in rx.finditer(pe.data)})


def run(exe: Path, out: Path) -> dict:
    pe = PE(exe)
    sections = {
        "pe": {
            "path": str(exe),
            "size": len(pe.data),
            "image_base": hex(pe.image_base),
            "sections": pe.sections,
        },
        "routes": section_routes(pe),
        "models": section_models(pe),
        "enums": section_enums(pe),
        "grpc": section_grpc(pe),
        "config": section_config(pe),
        "stubs": {
            "services": _plain(pe, STUB_RE),
            "persistence": _plain(pe, PERSIST_RE),
        },
        "assets": _plain(pe, ASSET_RE),
        "hosts": [{"host": h, "role": role_for_host(h)} for h in _plain(pe, HOST_RE)],
    }
    for name, payload in sections.items():
        write_json(out / f"{name}.json", payload)
    write_json(out / "summary.json", {k: _summarize(v) for k, v in sections.items()})
    return sections


def _summarize(v) -> object:
    if isinstance(v, dict):
        return {k: _summarize(x) for k, x in v.items() if k != "sections"}
    if isinstance(v, list):
        return len(v)
    return v


def report(sections: dict) -> None:
    r = sections["routes"]
    print(f"[routes] {len(r['routes'])} paths, {len(r['operations'])} operations")
    for p in r["routes"]:
        if "/prod/" in p or p.startswith("/game"):
            print(f"    {p}")
    print(f"\n[models] {len(sections['models'])} models")
    for name in ("ListWorldsResponseBody", "ListWorldsRequestBody"):
        m = sections["models"].get(name)
        if m:
            print(f"    {name}: {m['nearby_keys'][:16]}")
    print("\n[enums]")
    for name, info in sections["enums"].items():
        if not info.get("found"):
            print(f"    {name}: NOT FOUND")
            continue
        print(
            f"    {name} @{info['va']} xrefs={info['xrefs']} cluster={info['cluster'][:12]}"
        )
    print(
        f"\n[grpc] {len(sections['grpc']['endpoints'])} endpoints, "
        f"{len(sections['grpc']['services'])} services"
    )
    print(f"[config] {sections['config']['count']} keys")
    for g, ks in sorted(sections["config"]["groups"].items()):
        print(f"    {g}: {len(ks)}")
    print(
        f"[stubs] {len(sections['stubs']['services'])} services, "
        f"{len(sections['stubs']['persistence'])} persistence files"
    )
    print(f"[assets] {len(sections['assets'])} paths")
    print(f"[hosts] {len(sections['hosts'])} hosts")


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract the New World client catalog")
    ap.add_argument("--exe")
    ap.add_argument("--out")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    p = default_paths()
    exe = Path(args.exe) if args.exe else p["exe"]
    out = Path(args.out) if args.out else p["research"] / "derived"
    if not exe.is_file():
        print(f"exe not found: {exe}", file=sys.stderr)
        return 1
    sections = run(exe, out)
    if not args.quiet:
        report(sections)
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
