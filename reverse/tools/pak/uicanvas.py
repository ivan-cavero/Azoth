#!/usr/bin/env python3
r"""Read, parse and re-serialize New World LyShine UI canvases (AZ ObjectStream).

WHY THIS EXISTS
===============
The game's UI lives in `lyshineui/` inside `DataStrm*.pak`: 164
`.dynamicuicanvas` canvases, ~54k `.dds` sprites and ~1.1k `.luac` scripts. The
canvas container is AZ ObjectStream, the public O3DE binary serialization
format, so a reader is reproducible on any machine instead of a blind
reverse-engineering pass.

This tool is the FOUNDATION of the LyShine UI pipeline (`odd/tasks/lyshine-ui.md`,
task T1). It does one thing and proves it: parse the ObjectStream into a neutral
IR (a plain Python dict) and re-serialize it **byte-for-byte identical**. Every
byte that is not a field this tool names is carried through verbatim, so an
untouched canvas round-trips exactly and a later edit can only change fields it
is allowed to touch.

FORMAT (from O3DE `AzCore/Serialization/ObjectStream.cpp`)
==========================================================
Stream header, 5 bytes:

    [u8  s_binaryStreamTag = 0][u32 BE s_objectStreamVersion = 3]

Each element, in order:

    flags (u8; upper 5 bits, low 3 bits = value-size or size-field width)
    [nameCrc u32 BE]        if FLAG_HAS_NAME
    [element version u8]    if FLAG_HAS_VERSION
    typeId (16 raw bytes)   always present (AZ::Uuid)
    [size field]            if FLAG_HAS_VALUE and FLAG_EXTRA_SIZE_FIELD
    value (size bytes)      if FLAG_HAS_VALUE (a leaf)
    child elements ...      otherwise (an aggregate), closed by flags == 0

`flags == 0` is ST_BINARYFLAG_ELEMENT_END and closes the current level.

Usage:
    python ef.py re uicanvas read <pak> <entry> [--out FILE] [--ir FILE]
    python ef.py re uicanvas roundtrip <pak> <entry>
    python ef.py re uicanvas selftest
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pakread  # noqa: E402  (same folder; reuses the PAK/Kraken decoder)

# --- ObjectStream binary grammar (O3DE ObjectStream.cpp, BinaryFlags) ---------
STREAM_TAG = 0
STREAM_VERSION = 3

FLAG_MASK = 0xF8             # upper 5 bits of the flags byte
VALUE_SIZE_MASK = 0x07       # lower 3 bits of the flags byte
FLAG_ELEMENT_HEADER = 1 << 3  # 0x08
FLAG_HAS_VALUE = 1 << 4       # 0x10
FLAG_EXTRA_SIZE_FIELD = 1 << 5  # 0x20
FLAG_HAS_NAME = 1 << 6        # 0x40
FLAG_HAS_VERSION = 1 << 7     # 0x80
FLAG_ELEMENT_END = 0

MAX_DEPTH = 512

# Known-good canvases on client build 1.460 (all in DataStrm-part3.pak), used by
# the self-test as byte-exact round-trip fixtures.
SELFTEST_CANVASES = (
    ("DataStrm-part3.pak", "lyshineui/benchmark/fpsscreen.dynamicuicanvas", 7314),
    ("DataStrm-part3.pak", "lyshineui/_debug/fullscreenassert.dynamicuicanvas", 8903),
    ("DataStrm-part3.pak", "lyshineui/buildbanner/buildbanner.dynamicuicanvas", 10483),
)


class CanvasError(ValueError):
    """A payload that is not a well-formed v3 AZ ObjectStream."""


def _read_element(buf: bytes, off: int, depth: int) -> tuple[dict | None, int]:
    """Parse one element at `off`; return (element | None, new offset).

    `None` means the byte was FLAG_ELEMENT_END, i.e. the end of the parent's
    children, and `off` already points past it.
    """
    if depth > MAX_DEPTH:
        raise CanvasError(f"element nesting exceeds {MAX_DEPTH} levels")
    if off >= len(buf):
        raise CanvasError("truncated stream: expected an element header")

    flags = buf[off]
    off += 1
    if flags == FLAG_ELEMENT_END:
        return None, off

    name_crc = None
    version = None
    if flags & FLAG_HAS_NAME:
        name_crc = int.from_bytes(buf[off:off + 4], "big")
        off += 4
    if flags & FLAG_HAS_VERSION:
        version = buf[off]
        off += 1
    type_id = uuid.UUID(bytes=bytes(buf[off:off + 16]))
    off += 16

    value = None
    if flags & FLAG_HAS_VALUE:
        if flags & FLAG_EXTRA_SIZE_FIELD:
            width = flags & VALUE_SIZE_MASK
            if width not in (1, 2, 4):
                raise CanvasError(f"invalid size-field width {width}")
            size = int.from_bytes(buf[off:off + width], "big")
            off += width
        else:
            size = flags & VALUE_SIZE_MASK
        value = bytes(buf[off:off + size])
        if len(value) != size:
            raise CanvasError("truncated stream: value runs past the buffer")
        off += size

    # EVERY element is closed by its own FLAG_ELEMENT_END (O3DE CloseElement runs
    # for leaves too), so children are always read; a leaf just has none.
    children: list = []
    while True:
        child, off = _read_element(buf, off, depth + 1)
        if child is None:
            break
        children.append(child)

    return {
        "flags": flags,
        "name_crc": name_crc,
        "version": version,
        "type_id": type_id,
        "value": value,
        "children": children,
    }, off


def parse(data: bytes) -> dict:
    """Parse a v3 AZ ObjectStream into an IR dict. Raises CanvasError otherwise."""
    if len(data) < 5:
        raise CanvasError("stream too short for a 5-byte header")
    if data[0] != STREAM_TAG:
        raise CanvasError(f"not a binary ObjectStream (tag byte 0x{data[0]:02x}, expected 0x00)")
    stream_version = int.from_bytes(data[1:5], "big")
    if stream_version != STREAM_VERSION:
        raise CanvasError(f"unsupported ObjectStream version {stream_version} (only {STREAM_VERSION} is known)")

    root, off = _read_element(data, 5, depth=1)
    if root is None:
        raise CanvasError("stream has no root element")
    # The stream ends with one more close tag after the root element.
    if off >= len(data) or data[off] != FLAG_ELEMENT_END:
        raise CanvasError("missing the stream terminator after the root element")
    off += 1
    if off != len(data):
        raise CanvasError(f"trailing bytes after the stream terminator ({len(data) - off} left)")
    return {"stream_version": stream_version, "root": root}


def value_size_encoding(flags: int, length: int) -> tuple[int, bytes]:
    """Recompute the value-size encoding for `length` bytes.

    Returns `(flags, size_prefix)`: the flags byte with the name/version/type
    bits preserved but the low 3 size bits (and FLAG_EXTRA_SIZE_FIELD) derived
    from the ACTUAL value length -- inline when < 8, else the extra size field
    with the minimal width 1/2/4. This is what lets an edit that changes a
    value's length re-serialize correctly, while an unedited value recomputes
    to the same byte (real canvases store the minimal width).
    """
    base = flags & ~(FLAG_EXTRA_SIZE_FIELD | VALUE_SIZE_MASK)
    if length < 8:
        return base | length, b""
    width = 1 if length < 0x100 else 2 if length < 0x10000 else 4
    return base | FLAG_EXTRA_SIZE_FIELD | width, length.to_bytes(width, "big")


def _write_element(e: dict) -> bytes:
    flags = e["flags"]
    value = e.get("value")
    size_prefix = b""
    if flags & FLAG_HAS_VALUE:
        flags, size_prefix = value_size_encoding(flags, len(value))
    out = bytearray([flags])
    if flags & FLAG_HAS_NAME:
        out += e["name_crc"].to_bytes(4, "big")
    if flags & FLAG_HAS_VERSION:
        out += bytes([e["version"]])
    out += e["type_id"].bytes
    if flags & FLAG_HAS_VALUE:
        out += size_prefix
        out += value
    for child in e["children"]:
        out += _write_element(child)
    out += bytes([FLAG_ELEMENT_END])
    return bytes(out)


def serialize(ir: dict) -> bytes:
    """Re-serialize an IR dict back to bytes. Byte-exact against parse()."""
    return (
        bytes([STREAM_TAG])
        + ir["stream_version"].to_bytes(4, "big")
        + _write_element(ir["root"])
        + bytes([FLAG_ELEMENT_END])
    )


def count_elements(ir: dict) -> int:
    """Total element count (root included)."""
    def walk(e: dict) -> int:
        return 1 + sum(walk(c) for c in e["children"])
    return walk(ir["root"])


def summarize(ir: dict) -> dict:
    """A compact, JSON-friendly view of the tree for `read`."""
    classes: dict[str, int] = {}
    named = valued = 0
    max_depth = 0

    def walk(e: dict, depth: int) -> None:
        nonlocal named, valued, max_depth
        max_depth = max(max_depth, depth)
        classes[str(e["type_id"])] = classes.get(str(e["type_id"]), 0) + 1
        if e["name_crc"] is not None:
            named += 1
        if e["value"] is not None:
            valued += 1
        for c in e["children"]:
            walk(c, depth + 1)

    walk(ir["root"], 1)
    return {
        "stream_version": ir["stream_version"],
        "root_class": str(ir["root"]["type_id"]),
        "elements": count_elements(ir),
        "named": named,
        "with_value": valued,
        "max_depth": max_depth,
        "classes": dict(sorted(classes.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def to_jsonable(ir: dict) -> dict:
    """IR as JSON-safe data (values and uuids become strings)."""
    def conv(e: dict) -> dict:
        return {
            "flags": e["flags"],
            "name_crc": e["name_crc"],
            "version": e["version"],
            "type_id": str(e["type_id"]),
            "value": e["value"].hex() if e["value"] is not None else None,
            "children": [conv(c) for c in e["children"]],
        }
    return {"stream_version": ir["stream_version"], "root": conv(ir["root"])}


def parse_entry(pak_rel: str, entry: str) -> tuple[dict, dict]:
    """Decode and parse a canvas entry from the install. Returns (IR, meta)."""
    data, meta = pakread.read_entry(pak_rel, entry)
    return parse(data), meta


def cmd_read(pak_rel: str, entry: str, out: str | None, ir_out: str | None) -> int:
    data, meta = pakread.read_entry(pak_rel, entry)
    tree = parse(data)
    report = summarize(tree)
    report["sha256"] = hashlib.sha256(data).hexdigest()
    print(json.dumps(report, indent=1))
    if out:
        Path(out).write_bytes(data)
    if ir_out:
        Path(ir_out).write_text(json.dumps(to_jsonable(tree)), encoding="utf-8")
    return 0


def cmd_roundtrip(pak_rel: str, entry: str) -> int:
    data, meta = pakread.read_entry(pak_rel, entry)
    tree = parse(data)
    again = serialize(tree)
    ok = again == data
    print(f"{'OK' if ok else 'FAIL'} {pak_rel}::{entry} "
          f"({len(data)} B in, {len(again)} B out, {count_elements(tree)} elements)")
    return 0 if ok else 1


def selftest() -> int:
    checks: list[tuple[str, bool]] = []
    for pak, entry, usize in SELFTEST_CANVASES:
        try:
            data, _ = pakread.read_entry(pak, entry)
            tree = parse(data)
            checks.append((f"{entry} decodes ({usize} B)", len(data) == usize))
            checks.append((f"{entry} round-trips byte-exact", serialize(tree) == data))
            checks.append((f"{entry} has elements", count_elements(tree) > 1))
        except Exception as e:  # noqa: BLE001
            print(f"  {entry}: {e}")
            checks.append((f"{entry} parsed", False))
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
        ir_out = argv[argv.index("--ir") + 1] if "--ir" in argv else None
        return cmd_read(argv[1], argv[2], out, ir_out)
    if cmd == "roundtrip" and len(argv) >= 3:
        return cmd_roundtrip(argv[1], argv[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
