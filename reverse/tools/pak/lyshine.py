#!/usr/bin/env python3
r"""Name a LyShine UI canvas and render it to a STATIC HTML preview.

WHY THIS EXISTS
===============
The canvas reader (`uicanvas`, T1) turns a `.dynamicuicanvas` into a neutral IR,
and the asset classifier (`uiassets`, T2) says which 164 canvases exist. To see
and later edit the UI without the game, the IR needs *names*: every element has a
class GUID and every field has a CRC32 of its lowercase name. Two maps make a
canvas readable (`research/derived/lyshine-classes.json`):

  * `classes`: type GUID -> class name (`AZ::Entity`, `LyShine::UiTextComponent`,
    `AZ::Vector2`, ...), from the public O3DE LyShine/AZ RTTI.
  * `field_seed`: a CRC vocabulary; an element's `name_crc` is
    `zlib.crc32(name.lower())`, so a matching CRC names the field. A CRC with no
    seed entry is reported as `unknown <crc>` -- never guessed.

This tool is tasks T3/T6 (`odd/tasks/lyshine-ui.md`, specs S2 and S4): it names
the model and renders it to ONE self-contained HTML file (inline CSS, absolutely
positioned divs). It can also embed each element's sprite as a PNG data URI,
resolved through the pak index and decoded by `dds` (T5) -- those game texture
bytes go ONLY into the private, ignored preview output under
`.azoth/tmp/lyshine/`, never into the repo (docs/LEGAL.md S5). The HTML is a
*view*; the IR stays the source of truth (decision L6). Unknown classes/fields
degrade to an honest dashed placeholder, so a preview never invents a layout it
cannot decode.

THE MODEL
=========
`build_model(ir)` returns a JSON-safe dict: the decoded class/field names, the
canvas size, every `AZ::Entity`, and a `scene` of positioned rectangles. A UI
element's rectangle comes from its `LyShine::UiTransform2dComponent`:

    x1 = parent.x + anchors.left  * parent.w + offsets.left
    y1 = parent.y + anchors.top   * parent.h + offsets.top
    x2 = parent.x + anchors.right * parent.w + offsets.right
    y2 = parent.y + anchors.bottom* parent.h + offsets.bottom

`anchors` are normalized 0..1 in the parent, `offsets` are pixels. The parent of
the canvas's `rootElement` is the canvas viewport (its `CanvasSize`); children are
resolved through the `UiElementComponent` `childEntityId` list. `scale` is applied
about `pivot`; `rotation` is carried to the HTML as a CSS rotate.

FLOAT BYTE ORDER (measured 2026-11-01, fpsscreen)
=================================================
The ObjectStream header is `[u8 0][u32 BE 3]`, and the values are written with the
same big-endian convention. Little-endian was tried first and rejected: as
little-endian, anchors decode to denormals (~1e-43), while as big-endian they are
the normalized 0..1 the format documents (`3f000000` = 0.5) and `CanvasSize`
decodes to 1920x1080 (`44f0000044870000`). So every numeric leaf is read
big-endian.

Usage:
    python ef.py re lyshine render <pak> <entry> [--out FILE] [--no-sprites]
    python ef.py re lyshine set <pak> <entry> --field NAME --value VAL [--where NAME] [--out FILE]
    python ef.py re lyshine patch <pak> <entry> --field NAME --value VAL [--where NAME] --out patch.pak
    python ef.py re lyshine selftest

`render` embeds each element's sprite by default (the pak index is opened
read-only); `--no-sprites` skips that and writes the layout only. `set` edits one
named field and exports the modified `.dynamicuicanvas` (the
value-size encoding is recomputed, so a length-changing edit re-serializes
correctly). `patch` writes the same edit as a one-entry method-8 patch pak and
re-reads it to verify. Both REFUSE -- nonzero exit, no file -- when the field is
missing, ambiguous without `--where`, or the value cannot be decoded as its type.
A `--where` matches the parent class name or the enclosing entity's `Name`.
Never touches the install; without `--out` writes under the gitignored
`.azoth/tmp/lyshine/`.

Without `--out` the preview goes under the gitignored `.azoth/tmp/lyshine/`.
"""

from __future__ import annotations

import base64
import html
import json
import re
import sqlite3
import struct
import sys
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pakread  # noqa: E402  (same folder; reuses the PAK/Kraken decoder)
import pakwrite  # noqa: E402  (the patch-pak writer, method 8)
import uicanvas  # noqa: E402
import dds  # noqa: E402  (DDS -> PNG, task T5)

REPO = Path(__file__).resolve().parents[3]
CLASS_MAP = REPO / "research" / "derived" / "lyshine-classes.json"
DEFAULT_OUT_DIR = REPO / ".azoth" / "tmp" / "lyshine"
PAK_INDEX = REPO / ".azoth" / "cache" / "pak-index" / "pakindex.db"

ENTITY_CLASS = "AZ::Entity"
TRANSFORM_CLASS = "LyShine::UiTransform2dComponent"
ELEMENT_CLASS = "LyShine::UiElementComponent"
CANVAS_CLASS = "LyShine::UiCanvasComponent"

# Field names confirmed by CRC against fpsscreen on 1.460 (see field_seed); the
# CRC of `lower(name)` is what an element's name_crc carries.
FIELD_ID = "id"
FIELD_NAME = "name"
FIELD_COMPONENTS = "components"
FIELD_ELEMENT = "element"
FIELD_PIVOT = "pivot"
FIELD_ROTATION = "rotation"
FIELD_SCALE = "scale"
FIELD_SCALE_TO_DEVICE = "scaletodevice"
FIELD_ALPHA = "alpha"
FIELD_COLOR = "color"
FIELD_TEXT = "text"
FIELD_FONT_SIZE = "fontsize"
FIELD_CANVAS_SIZE = "canvassize"
FIELD_ROOT_ELEMENT = "rootelement"
FIELD_CHILD_ENTITY_ID = "childentityid"
FIELD_LEFT = "left"
FIELD_TOP = "top"
FIELD_RIGHT = "right"
FIELD_BOTTOM = "bottom"

# A UiImageComponent carries its sprite as a named-blob leaf (name CRC
# 0x8DF2FDBE); a UiImageSequenceComponent carries its frame folder as a plain
# AZStd::string leaf (name CRC 0xCEE077ED). Measured 2026-11-02, client
# 1.460.6033.6024067; neither CRC is in the field seed map.
SPRITE_REF_CRC = 0x8DF2FDBE
SEQUENCE_SPRITE_CRC = 0xCEE077ED
# The blob header before the path: 16B asset GUID + 16B zeros + 16B sprite-type
# GUID + a u64 BIG-ENDIAN path length. The path bytes follow.
SPRITE_BLOB_HEADER = 56

# The normalized float value order. See the module docstring for the measurement.
FLOAT_ORDER = ">"
_F = struct.Struct(FLOAT_ORDER + "f")
_V2 = struct.Struct(FLOAT_ORDER + "2f")

SELFTEST_CANVAS = ("DataStrm-part3.pak", "lyshineui/benchmark/fpsscreen.dynamicuicanvas")


class EditError(ValueError):
    """A named-field edit cannot be applied unambiguously and safely."""


# --- maps --------------------------------------------------------------------

def load_maps(path: str | Path | None = None) -> tuple[dict[str, str], dict[int, str]]:
    """Load the class map (GUID -> name) and the field CRC map (crc -> name)."""
    doc = json.loads(Path(path or CLASS_MAP).read_text(encoding="utf-8"))
    classes = {str(k).lower(): str(v) for k, v in doc["classes"].items()}
    fields = {
        zlib.crc32(str(n).lower().encode("ascii")) & 0xFFFFFFFF: str(n)
        for n in doc.get("field_seed", [])
    }
    return classes, fields


def class_name(type_id, classes: dict[str, str]) -> str | None:
    """Class name for a type GUID, or None when the map does not name it."""
    return classes.get(str(type_id).lower())


def field_name(name_crc: int | None, fields: dict[int, str]) -> str | None:
    """Field name for a CRC, or None when the seed vocabulary has no match."""
    if name_crc is None:
        return None
    return fields.get(name_crc)


def field_label(name_crc: int | None, fields: dict[int, str]) -> str | None:
    """Field name, or an honest `unknown <crc>` placeholder. None means no name."""
    if name_crc is None:
        return None
    return fields.get(name_crc) or f"unknown {name_crc:08x}"


def is_field(e: dict, name: str, fields: dict[int, str]) -> bool:
    """True when `e`'s CRC names the field `name` (case-insensitive)."""
    got = field_name(e["name_crc"], fields)
    return got is not None and got.lower() == name.lower()


# --- typed leaves ------------------------------------------------------------

def decode_leaf(field: str | None, cls: str | None, raw: bytes | None):
    """Decode a leaf's bytes for the types the layout needs.

    Unsupported or unknown types return a `{"bytes", "hex"}` record, so the model
    keeps the bytes without pretending to understand them.
    """
    if raw is None:
        return None
    if cls == "AZ::Vector2" and len(raw) == 8:
        return list(_V2.unpack(raw))
    if cls == "float" and len(raw) == 4:
        return _F.unpack(raw)[0]
    if cls == "bool" and len(raw) >= 1:
        return raw[0] != 0
    if cls == "AZStd::string":
        return raw.decode("utf-8", "replace")
    if cls in ("AZ::u64", "EntityId") and len(raw) == 8:
        return int.from_bytes(raw, "big")
    if cls == "AZ::u32" and len(raw) == 4:
        return int.from_bytes(raw, "big")
    if cls == "int" and len(raw) == 4:
        return int.from_bytes(raw, "big", signed=True)
    # `Color` has no class entry in the map, but its field name is confirmed and
    # its value is N big-endian floats (RGB or RGBA). Decode it honestly.
    if field and field.lower() == FIELD_COLOR and len(raw) in (12, 16):
        return list(struct.unpack(FLOAT_ORDER + "f" * (len(raw) // 4), raw))
    return {"bytes": len(raw), "hex": raw.hex()}


# --- IR helpers --------------------------------------------------------------

def _nodes(e: dict):
    yield e
    for c in e["children"]:
        yield from _nodes(c)


def _child_by_field(e: dict, name: str, fields: dict[int, str]) -> dict | None:
    for c in e["children"]:
        if is_field(c, name, fields):
            return c
    return None


def _direct_value(e: dict, name: str, fields: dict[int, str]) -> bytes | None:
    node = _child_by_field(e, name, fields)
    return node["value"] if node else None


def _first_id_leaf(e: dict, fields: dict[int, str]) -> int | None:
    """The first `Id` u64 anywhere under `e` (an entity/EntityId's own id)."""
    for n in _nodes(e):
        if n["value"] is not None and is_field(n, FIELD_ID, fields):
            return int.from_bytes(n["value"], "big")
    return None


def _id_of(node: dict, fields: dict[int, str]) -> int | None:
    """The entity id behind an `EntityId` node (or an `Id` leaf)."""
    if node["value"] is not None:
        return int.from_bytes(node["value"], "big")
    for n in _nodes(node):
        if n["value"] is not None and is_field(n, FIELD_ID, fields):
            return int.from_bytes(n["value"], "big")
    return None


def _components(entity: dict, fields: dict[int, str]) -> list[dict]:
    """The entity's own serialized components (direct `Element` children)."""
    box = _child_by_field(entity, FIELD_COMPONENTS, fields)
    if box is None:
        return []
    return [c for c in box["children"] if is_field(c, FIELD_ELEMENT, fields)]


def _component_of(entity: dict, cls: str, classes, fields) -> dict | None:
    for comp in _components(entity, fields):
        if class_name(comp["type_id"], classes) == cls:
            return comp
    return None


def _struct_floats(node: dict, struct_cls: str, classes, fields) -> dict[str, float]:
    """Read the left/top/right/bottom floats of an Anchors/Offsets child."""
    sub = None
    for c in node["children"]:
        if class_name(c["type_id"], classes) == struct_cls:
            sub = c
            break
    if sub is None:
        return {}
    out: dict[str, float] = {}
    for leaf in _nodes(sub):
        if leaf["value"] is None or len(leaf["value"]) != 4:
            continue
        name = field_name(leaf["name_crc"], fields)
        if name and name.lower() in (FIELD_LEFT, FIELD_TOP, FIELD_RIGHT, FIELD_BOTTOM):
            out[name.lower()] = _F.unpack(leaf["value"])[0]
    return out


def _vec2(node: dict, name: str, fields) -> list[float] | None:
    raw = _direct_value(node, name, fields)
    return list(_V2.unpack(raw)) if raw is not None and len(raw) == 8 else None


def _float(node: dict, name: str, fields) -> float | None:
    raw = _direct_value(node, name, fields)
    return _F.unpack(raw)[0] if raw is not None and len(raw) == 4 else None


def _bool(node: dict, name: str, fields) -> bool | None:
    raw = _direct_value(node, name, fields)
    return (raw[0] != 0) if raw is not None and len(raw) >= 1 else None


def _string(node: dict, name: str, fields) -> str | None:
    raw = _direct_value(node, name, fields)
    return raw.decode("utf-8", "replace") if raw is not None else None


def _transform(comp: dict, classes, fields) -> dict | None:
    anchors = _struct_floats(comp, "LyShine::Anchors", classes, fields)
    offsets = _struct_floats(comp, "LyShine::Offsets", classes, fields)
    if not anchors and not offsets:
        return None
    return {
        "anchors": anchors,
        "offsets": offsets,
        "pivot": _vec2(comp, FIELD_PIVOT, fields),
        "rotation": _float(comp, FIELD_ROTATION, fields),
        "scale": _vec2(comp, FIELD_SCALE, fields),
        "scale_to_device": _bool(comp, FIELD_SCALE_TO_DEVICE, fields),
    }


def _children_ids(entity: dict, classes, fields) -> list[int]:
    """Child element entity ids, from the UiElementComponent children list."""
    uic = _component_of(entity, ELEMENT_CLASS, classes, fields)
    if uic is None:
        return []
    ids: list[int] = []
    for n in _nodes(uic):
        if is_field(n, FIELD_CHILD_ENTITY_ID, fields):
            child = _id_of(n, fields)
            if child is not None:
                ids.append(child)
    return ids


def _entity_text(entity: dict, classes, fields) -> dict:
    """Text/color/alpha/font size pulled from the entity's text or image component."""
    out: dict = {"text": None, "color": None, "alpha": None, "font_size": None}
    for comp in _components(entity, fields):
        for n in _nodes(comp):
            if n["value"] is None:
                continue
            name = field_name(n["name_crc"], fields)
            cls = class_name(n["type_id"], classes)
            low = (name or "").lower()
            if low == FIELD_TEXT and cls == "AZStd::string":
                out["text"] = n["value"].decode("utf-8", "replace")
            elif low == FIELD_COLOR:
                out["color"] = decode_leaf(name, cls, n["value"])
            elif low == FIELD_ALPHA and cls == "float" and len(n["value"]) == 4:
                out["alpha"] = _F.unpack(n["value"])[0]
            elif low == FIELD_FONT_SIZE and cls == "float" and len(n["value"]) == 4:
                out["font_size"] = _F.unpack(n["value"])[0]
    return out


def _component_model(comp: dict, classes, fields) -> dict:
    cls = class_name(comp["type_id"], classes)
    named: dict[str, object] = {}
    unknown_fields: list[str] = []
    for n in _nodes(comp):
        label = field_label(n["name_crc"], fields)
        if n["value"] is None or label is None:
            continue
        key = label
        if key.startswith("unknown "):
            unknown_fields.append(key)
        leaf_cls = class_name(n["type_id"], classes)
        named[key] = decode_leaf(field_name(n["name_crc"], fields), leaf_cls, n["value"])
    return {
        "class": cls,
        "type_id": str(comp["type_id"]),
        "unknown_class": cls is None,
        "fields": named,
        "unknown_fields": sorted(set(unknown_fields)),
    }


# --- sprites -----------------------------------------------------------------

def sprite_ref_path(value: bytes | None) -> str | None:
    """The texture path in a UiImageComponent sprite reference, or None.

    The blob is 16B asset GUID, 16B zeros, 16B constant sprite-type GUID, then a
    u64 BIG-ENDIAN path length and that many UTF-8 bytes (measured 2026-11-02). A
    zero length, a header shorter than 56 bytes, or a path the blob truncates all
    mean there is no path -- never guess one.
    """
    if value is None or len(value) < SPRITE_BLOB_HEADER:
        return None
    length = int.from_bytes(value[48:56], "big")
    if length == 0 or len(value) - SPRITE_BLOB_HEADER < length:
        return None
    raw = value[SPRITE_BLOB_HEADER:SPRITE_BLOB_HEADER + length]
    return raw.decode("utf-8", "replace")


def _entity_sprite(entity: dict, classes, fields) -> str | None:
    """The sprite path named by an entity's image or sequence component, if any."""
    for comp in _components(entity, fields):
        for n in _nodes(comp):
            if n["value"] is None:
                continue
            if n["name_crc"] == SPRITE_REF_CRC:
                path = sprite_ref_path(n["value"])
                if path:
                    return path
            elif n["name_crc"] == SEQUENCE_SPRITE_CRC:
                folder = n["value"].decode("utf-8", "replace").strip()
                if folder:
                    return folder
    return None


def sprite_entry(path: str, con) -> tuple[str, str] | None:
    """Resolve a sprite path to (pak, entry): exact entry, else first folder frame.

    An exact `path` wins; otherwise `path` is treated as a folder of frame `.dds`
    files and the FIRST frame in path order is taken.
    """
    row = con.execute("SELECT pak, path FROM entry WHERE path = ?", (path,)).fetchone()
    if row is not None:
        return (row[0], row[1])
    prefix = (path.rstrip("/").replace("\\", "\\\\")
              .replace("%", "\\%").replace("_", "\\_"))
    row = con.execute(
        "SELECT pak, path FROM entry WHERE path LIKE ? ESCAPE '\\' "
        "ORDER BY path LIMIT 1", (prefix + "/%",)).fetchone()
    return (row[0], row[1]) if row is not None else None


def sprite_data_uri(pak: str, entry: str, read) -> str | None:
    """Read one entry as a PNG data URI (`.png` passes through; else `dds`).

    Returns None when the bytes cannot be read or decoded, so a caller can skip
    the sprite instead of inventing one.
    """
    try:
        data = read(pak, entry)
        if entry.lower().endswith(".png"):
            png = data
        else:
            image = dds.decode(data)
            png = dds.png_bytes(image.width, image.height, image.pixels())
    except (ValueError, OSError):
        return None
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def load_sprites(model: dict, con, read) -> dict[str, str]:
    """Map each scene sprite path to its PNG data URI; skip unresolved/invalid."""
    sprites: dict[str, str] = {}
    for element in model["scene"]:
        path = element.get("sprite")
        if not path or path in sprites:
            continue
        resolved = sprite_entry(path, con)
        if resolved is None:
            continue
        uri = sprite_data_uri(resolved[0], resolved[1], read)
        if uri is not None:
            sprites[path] = uri
    return sprites


def element_model(e: dict, classes, fields) -> dict:
    """Recursively name one element; unknown class -> None (an honest placeholder)."""
    cls = class_name(e["type_id"], classes)
    return {
        "field": field_label(e["name_crc"], fields),
        "class": cls,
        "type_id": str(e["type_id"]),
        "version": e["version"],
        "unknown_class": cls is None,
        "value": decode_leaf(field_name(e["name_crc"], fields), cls, e["value"]),
        "children": [element_model(c, classes, fields) for c in e["children"]],
    }


# --- model -------------------------------------------------------------------

def compute_rect(transform: dict, parent: tuple[float, float, float, float]):
    """LyShine anchors/offsets/scale -> (x, y, w, h) in canvas pixels."""
    px, py, pw, ph = parent
    a = transform.get("anchors") or {}
    o = transform.get("offsets") or {}
    left = a.get(FIELD_LEFT, 0.0)
    top = a.get(FIELD_TOP, 0.0)
    right = a.get(FIELD_RIGHT, 1.0)
    bottom = a.get(FIELD_BOTTOM, 1.0)
    x1 = px + left * pw + o.get(FIELD_LEFT, 0.0)
    y1 = py + top * ph + o.get(FIELD_TOP, 0.0)
    x2 = px + right * pw + o.get(FIELD_RIGHT, 0.0)
    y2 = py + bottom * ph + o.get(FIELD_BOTTOM, 0.0)

    w0, h0 = x2 - x1, y2 - y1
    sx, sy = transform.get("scale") or (1.0, 1.0)
    pivot = transform.get("pivot") or (0.5, 0.5)
    # Scale about the pivot so the pivot point stays fixed.
    x1 = x1 + pivot[0] * w0 - pivot[0] * w0 * sx
    y1 = y1 + pivot[1] * h0 - pivot[1] * h0 * sy
    return x1, y1, w0 * sx, h0 * sy


def build_model(ir: dict, classes=None, fields=None) -> dict:
    """Name a canvas IR and resolve its positioned scene. JSON-safe."""
    if classes is None or fields is None:
        classes, fields = load_maps()

    # Every AZ::Entity, including the canvas holder and the wrapper entities.
    entities: list[dict] = []
    for n in _nodes(ir["root"]):
        if class_name(n["type_id"], classes) == ENTITY_CLASS:
            entities.append(n)

    records: list[dict] = []
    for e in entities:
        comps = [_component_model(c, classes, fields) for c in _components(e, fields)]
        record = {
            "id": _first_id_leaf(e, fields),
            "name": _string(e, FIELD_NAME, fields),
            "transform": None,
            "children_ids": _children_ids(e, classes, fields),
            "components": comps,
            "unknown_classes": sorted({c["type_id"] for c in comps if c["unknown_class"]}),
            "sprite": _entity_sprite(e, classes, fields),
        }
        record.update(_entity_text(e, classes, fields))
        transform_comp = _component_of(e, TRANSFORM_CLASS, classes, fields)
        if transform_comp is not None:
            record["transform"] = _transform(transform_comp, classes, fields)
        records.append(record)

    # Canvas viewport and root element, from the UiCanvasComponent holder.
    canvas = {"size": [1920.0, 1080.0], "root_entity_id": None, "canvas_entity_id": None}
    for e, record in zip(entities, records):
        comp = _component_of(e, CANVAS_CLASS, classes, fields)
        if comp is None:
            continue
        record["is_canvas"] = True
        canvas["canvas_entity_id"] = record["id"]
        size = _vec2(comp, FIELD_CANVAS_SIZE, fields)
        if size:
            canvas["size"] = size
        root_node = _child_by_field(comp, FIELD_ROOT_ELEMENT, fields)
        if root_node is not None:
            canvas["root_entity_id"] = _id_of(root_node, fields)
        break

    by_id = {r["id"]: r for r in records if r["id"] is not None}
    scene: list[dict] = []
    visited: set[int] = set()

    def emit(entity_id: int | None, parent: tuple, depth: int) -> None:
        record = by_id.get(entity_id)
        if record is None or entity_id in visited:
            return
        visited.add(entity_id)
        rect = parent
        if record["transform"] is not None:
            rect = compute_rect(record["transform"], parent)
        entry = {
            "id": entity_id,
            "name": record["name"],
            "depth": depth,
            "x": rect[0], "y": rect[1], "w": rect[2], "h": rect[3],
            "color": record["color"],
            "text": record["text"],
            "alpha": record["alpha"],
            "font_size": record["font_size"],
            "rotation": (record["transform"] or {}).get("rotation") or 0.0,
            "pivot": (record["transform"] or {}).get("pivot") or [0.5, 0.5],
            "unknown_classes": record["unknown_classes"],
            "sprite": record["sprite"],
        }
        scene.append(entry)
        for child in record["children_ids"]:
            emit(child, rect, depth + 1)

    emit(canvas["root_entity_id"], (0.0, 0.0, canvas["size"][0], canvas["size"][1]), 0)
    # Any transform-bearing element the root chain did not reach (unrooted data).
    for record in records:
        if record["transform"] is not None and record["id"] not in visited:
            emit(record["id"], (0.0, 0.0, canvas["size"][0], canvas["size"][1]), 0)

    unknown_classes: dict[str, int] = {}
    named_classes: dict[str, int] = {}
    unknown_fields: dict[str, int] = {}
    for n in _nodes(ir["root"]):
        cls = class_name(n["type_id"], classes)
        if cls is None:
            unknown_classes[str(n["type_id"])] = unknown_classes.get(str(n["type_id"]), 0) + 1
        else:
            named_classes[cls] = named_classes.get(cls, 0) + 1
        if n["name_crc"] is not None and field_name(n["name_crc"], fields) is None:
            key = f"{n['name_crc']:08x}"
            unknown_fields[key] = unknown_fields.get(key, 0) + 1

    named_entities = sum(1 for r in records if not r["unknown_classes"])
    return {
        "stream_version": ir["stream_version"],
        "canvas": canvas,
        "entities": records,
        "scene": scene,
        "tree": element_model(ir["root"], classes, fields),
        "classes": dict(sorted(named_classes.items(), key=lambda kv: (-kv[1], kv[0]))),
        "unknown_classes": dict(sorted(unknown_classes.items(), key=lambda kv: (-kv[1], kv[0]))),
        "unknown_fields": dict(sorted(unknown_fields.items(), key=lambda kv: (-kv[1], kv[0]))),
        "counts": {
            "entities": len(records),
            "named_entities": named_entities,
            "unknown_entities": len(records) - named_entities,
            "positioned": len(scene),
            "elements": uicanvas.count_elements(ir),
        },
    }


# --- editing -----------------------------------------------------------------

_NUM_SEP = re.compile(r"[,\s]+")


def _parse_floats(text: str, count: int) -> list[float]:
    parts = [p for p in _NUM_SEP.split(text.strip()) if p]
    if len(parts) != count:
        raise EditError(f"expected {count} number(s), got {len(parts)} in {text!r}")
    try:
        return [float(p) for p in parts]
    except ValueError as e:
        raise EditError(f"not a number: {text!r}") from e


def encode_leaf_value(text: str, leaf_class: str | None,
                      field: str | None, existing_len: int) -> bytes:
    """Encode a CLI value string as the leaf's typed bytes.

    The type comes from the leaf's class GUID (`lyshine-classes.json`); a
    `Color` leaf has no class entry, so its field name and stored length carry
    the type (N big-endian floats). Anything else is refused, never guessed.
    """
    cls = (leaf_class or "").lower()
    if cls == "float":
        return _F.pack(_parse_floats(text, 1)[0])
    if cls == "az::vector2":
        return _V2.pack(*_parse_floats(text, 2))
    if cls == "bool":
        low = text.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return b"\x01"
        if low in ("0", "false", "no", "off"):
            return b"\x00"
        raise EditError(f"not a bool: {text!r}")
    if cls == "azstd::string":
        return text.encode("utf-8")
    if cls in ("az::u64", "entityid"):
        return int(text, 0).to_bytes(8, "big")
    if cls == "az::u32":
        return int(text, 0).to_bytes(4, "big")
    if cls == "int":
        return int(text, 0).to_bytes(4, "big", signed=True)
    if (field or "").lower() == FIELD_COLOR and existing_len in (12, 16):
        return struct.pack(FLOAT_ORDER + "f" * (existing_len // 4),
                           *_parse_floats(text, existing_len // 4))
    raise EditError(
        f"cannot decode {text!r} as field {field or '?'} "
        f"(class {leaf_class or 'unknown'})")


def _field_candidates(ir: dict, field: str, classes, fields) -> list[dict]:
    """Every value-bearing element whose name CRC == CRC32(lower(field)).

    Each candidate carries the parent element's class name and the nearest
    enclosing `AZ::Entity` name, which is what `--where` selects on.
    """
    target = zlib.crc32(field.lower().encode("ascii")) & 0xFFFFFFFF
    out: list[dict] = []

    def walk(e: dict, parent: dict | None, entity_name: str | None) -> None:
        if e["value"] is not None and e["name_crc"] == target:
            out.append({
                "element": e,
                "parent_class": class_name(parent["type_id"], classes) if parent else None,
                "entity_name": entity_name,
            })
        next_entity = entity_name
        if class_name(e["type_id"], classes) == ENTITY_CLASS:
            next_entity = _string(e, FIELD_NAME, fields) or entity_name
        for c in e["children"]:
            walk(c, e, next_entity)

    walk(ir["root"], None, None)
    return out


def resolve_field(ir: dict, field: str, where: str | None = None,
                  classes=None, fields=None) -> dict:
    """Resolve `field` to exactly one element, or raise EditError (fail closed)."""
    if classes is None or fields is None:
        classes, fields = load_maps()
    candidates = _field_candidates(ir, field, classes, fields)
    if not candidates:
        raise EditError(f"field not found: {field!r}")
    if where:
        want = where.lower()
        candidates = [c for c in candidates
                      if (c["parent_class"] or "").lower() == want
                      or (c["entity_name"] or "").lower() == want]
        if not candidates:
            raise EditError(f"no {field!r} field under {where!r}")
    if len(candidates) > 1:
        scopes = sorted({c["parent_class"] or "?" for c in candidates}
                        | {c["entity_name"] or "?" for c in candidates})
        hint = "add --where" if not where else "--where did not narrow to one"
        raise EditError(
            f"field {field!r} is ambiguous ({hint}): matches {len(candidates)} "
            f"elements [{', '.join(scopes)}]")
    return candidates[0]["element"]


def apply_edit(ir: dict, field: str, value: str, where: str | None = None,
               classes=None, fields=None) -> dict:
    """Resolve the field and overwrite its typed value in place. Returns the leaf."""
    if classes is None or fields is None:
        classes, fields = load_maps()
    target = resolve_field(ir, field, where, classes, fields)
    leaf_class = class_name(target["type_id"], classes)
    name = field_name(target["name_crc"], fields)
    target["value"] = encode_leaf_value(value, leaf_class, name, len(target["value"] or b""))
    return target


def edit_canvas_bytes(data: bytes, field: str, value: str,
                      where: str | None = None) -> bytes:
    """Parse, apply one named-field edit, and re-serialize the canvas bytes."""
    classes, fields = load_maps()
    ir = uicanvas.parse(data)
    apply_edit(ir, field, value, where, classes, fields)
    return uicanvas.serialize(ir)


# --- HTML --------------------------------------------------------------------

def _css_color(color, alpha) -> str:
    if not isinstance(color, list) or len(color) < 3:
        return "rgba(255,255,255,0.10)"
    r, g, b = (max(0, min(255, int(round(v * 255)))) for v in color[:3])
    a = color[3] if len(color) >= 4 else (alpha if alpha is not None else 1.0)
    return f"rgba({r},{g},{b},{a:.3f})"


def _num(value: float) -> str:
    text = f"{value:.2f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def render_html(model: dict, title: str = "LyShine preview",
                sprites: dict[str, str] | None = None) -> str:
    """Render the named model to one self-contained static HTML document.

    `sprites` maps a scene element's sprite path to a PNG data URI; a path with a
    URI gets a `background-image` and a `data-sprite` attribute, and anything
    else is left out. With no map the layout renders with no images at all.
    """
    canvas = model["canvas"]
    cw, ch = canvas["size"]
    sprites = sprites or {}

    boxes: list[str] = []
    for el in model["scene"]:
        dashed = " lyshine-unknown-box" if el["unknown_classes"] else ""
        transform = ""
        if el["rotation"]:
            px, py = el["pivot"]
            transform = (f"transform:rotate({_num(el['rotation'])}rad);"
                         f"transform-origin:{_num(px * 100)}% {_num(py * 100)}%;")
        uri = sprites.get(el.get("sprite"))
        image = f"background-image:url({uri});" if uri else ""
        style = (
            f"position:absolute;left:{_num(el['x'])}px;top:{_num(el['y'])}px;"
            f"width:{_num(el['w'])}px;height:{_num(el['h'])}px;"
            f"background:{_css_color(el['color'], el['alpha'])};{transform}{image}"
        )
        if el["name"]:
            name = html.escape(el["name"])
        elif el["id"] is not None:
            name = f"entity {el['id']:016x}"
        else:
            name = "entity ?"
        label = f'<span class="lyshine-name">{name}</span>'
        text = (f'<span class="lyshine-text">{html.escape(el["text"])}</span>'
                if el["text"] else "")
        unknown = "".join(
            f'<span class="lyshine-unknown">unknown {html.escape(uid)}</span>'
            for uid in el["unknown_classes"]
        )
        sprite_attr = f' data-sprite="{html.escape(el["sprite"])}"' if uri else ""
        boxes.append(
            f'<div class="lyshine-el{dashed}" data-entity="{el["id"] if el["id"] is not None else ""}"'
            f'{sprite_attr} style="{style}">{label}{text}{unknown}</div>'
        )

    model_json = json.dumps(model, ensure_ascii=False).replace("<", "\\u003c")
    counts = model["counts"]

    unknown_section = ""
    if model["unknown_classes"] or model["unknown_fields"]:
        class_items = "".join(
            f'<li>unknown {html.escape(uid)} &times;{n}</li>'
            for uid, n in model["unknown_classes"].items()
        )
        field_items = "".join(
            f'<li>unknown {html.escape(c)} &times;{n}</li>'
            for c, n in model["unknown_fields"].items()
        )
        unknown_section = (
            '<details class="lyshine-unknowns"><summary>unknown inventory</summary>'
            '<h2>classes (uuid)</h2><ul>' + (class_items or "<li>none</li>") + "</ul>"
            '<h2>fields (crc)</h2><ul>' + (field_items or "<li>none</li>") + "</ul>"
            "</details>\n"
        )
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{html.escape(title)}</title>\n"
        "<style>\n"
        "  body{margin:0;background:#20222a;color:#dfe3ee;"
        "font:13px/1.4 system-ui,Segoe UI,Roboto,sans-serif}\n"
        "  header{padding:10px 14px;border-bottom:1px solid #333a49}\n"
        "  h1{margin:0;font-size:15px}\n"
        "  .lyshine-counts{opacity:.75;font-size:12px}\n"
        "  .lyshine-canvas{position:relative;margin:14px;overflow:hidden;"
        "background:#0d0f14;border:1px solid #333a49;box-shadow:0 0 0 1px #000 inset}\n"
        "  .lyshine-el{box-sizing:border-box;border:1px solid rgba(120,190,255,.55);"
        "overflow:hidden;color:#fff}\n"
        "  .lyshine-unknown-box{border:1px dashed #ff9d5c}\n"
        "  .lyshine-name{position:absolute;left:2px;top:1px;font-size:10px;opacity:.8;"
        "white-space:nowrap}\n"
        "  .lyshine-text{position:absolute;left:2px;bottom:1px;font-size:11px;"
        "white-space:nowrap;text-shadow:0 1px 2px #000}\n"
        "  .lyshine-unknown{position:absolute;right:2px;bottom:1px;font-size:10px;"
        "color:#ffb27a;border:1px dashed #ff9d5c;padding:0 3px;background:rgba(0,0,0,.5)}\n"
        "  .lyshine-unknowns{margin:0 14px 20px;padding:8px 12px;border:1px dashed #ff9d5c}"
        "\n  .lyshine-unknowns h2{font-size:12px;margin:8px 0 2px}\n"
        "  .lyshine-unknowns ul{margin:0;padding-left:18px;columns:3}\n"
        "</style>\n</head>\n<body>\n"
        "<header>\n"
        f"<h1>{html.escape(title)}</h1>\n"
        f'<div class="lyshine-counts">canvas {_num(cw)}x{_num(ch)} &middot; '
        f'{counts["positioned"]} positioned / {counts["entities"]} entities '
        f'({counts["unknown_entities"]} with unknown classes) &middot; '
        f'{len(model["unknown_classes"])} unknown class ids, '
        f'{len(model["unknown_fields"])} unknown field crcs</div>\n'
        "</header>\n"
        f'<div class="lyshine-canvas" style="width:{_num(cw)}px;height:{_num(ch)}px">\n'
        + "\n".join(boxes) + "\n</div>\n"
        + unknown_section
        + f'<script type="application/json" id="lyshine-model">{model_json}</script>\n'
        "</body>\n</html>\n"
    )


# --- commands ----------------------------------------------------------------

def _load_model(pak_rel: str, entry: str) -> dict:
    data, _meta = pakread.read_entry(pak_rel, entry)
    return build_model(uicanvas.parse(data))


def _render(pak_rel: str, entry: str, sprites: dict[str, str] | None = None) -> str:
    return render_html(_load_model(pak_rel, entry), title=f"{pak_rel}::{entry}",
                       sprites=sprites)


def _read_entry_bytes(pak: str, entry: str) -> bytes:
    """`pakread.read_entry` as the bytes-only `read` `load_sprites` expects."""
    data, _meta = pakread.read_entry(pak, entry)
    return data


def _load_sprites(model: dict) -> dict[str, str]:
    """Sprites from the read-only pak index; empty when the index is absent."""
    if not PAK_INDEX.exists():
        return {}
    con = sqlite3.connect(f"file:{PAK_INDEX}?mode=ro", uri=True)
    try:
        return load_sprites(model, con, _read_entry_bytes)
    finally:
        con.close()


def cmd_render(pak_rel: str, entry: str, out: str | None,
               no_sprites: bool = False) -> int:
    model = _load_model(pak_rel, entry)
    sprites = None if no_sprites else _load_sprites(model)
    document = render_html(model, title=f"{pak_rel}::{entry}", sprites=sprites)
    if out:
        target = Path(out)
    else:
        target = DEFAULT_OUT_DIR / (Path(entry).stem + ".html")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document, encoding="utf-8")
    print(f"wrote {target} ({len(document)} chars)")
    return 0


def cmd_set(pak_rel: str, entry: str, field: str, value: str,
            where: str | None, out: str | None) -> int:
    """Edit one named field and export the modified canvas (or fail closed)."""
    try:
        data, _meta = pakread.read_entry(pak_rel, entry)
        edited = edit_canvas_bytes(data, field, value, where)
    except (EditError, uicanvas.CanvasError, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    target = Path(out) if out else DEFAULT_OUT_DIR / (Path(entry).stem + ".edited.dynamicuicanvas")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(edited)
    print(f"wrote {target} ({len(edited)} bytes, {len(edited) - len(data):+d})")
    return 0


def _read_patch_entry(path: Path, entry: str) -> bytes:
    """Re-read one entry from a written patch pak through `pakread.decode`."""
    with zipfile.ZipFile(path) as z:
        info = z.getinfo(entry)
        with open(path, "rb") as f:
            f.seek(info.header_offset)
            lh = f.read(30)
            nlen, elen = struct.unpack("<HH", lh[26:30])
            f.seek(info.header_offset + 30 + nlen + elen)
            payload = f.read(info.compress_size)
    return pakread.decode(payload, info.compress_type, info.file_size, info.CRC,
                          f"{path}::{entry}")


def cmd_patch(pak_rel: str, entry: str, field: str, value: str,
              out: str, where: str | None = None) -> int:
    """Write the edited canvas as a one-entry patch pak and verify it."""
    out_path = Path(out)
    try:
        edited = pakwrite.make(
            pak_rel, entry, out_path,
            transform=lambda d: edit_canvas_bytes(d, field, value, where),
            method=8)
    except (EditError, uicanvas.CanvasError, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if _read_patch_entry(out_path, entry) != edited:
        print(f"error: patch pak {out_path} failed verification", file=sys.stderr)
        return 1
    print(f"patch pak written: {out_path} ({len(edited)} bytes, entry {entry}, method 8)")
    print("next (client-owned, not run here): copy it to <install>/Assets/ and add "
          f"'Assets/{out_path.name}' as the FIRST line of <install>/PaksList.lst")
    return 0


def _edit_opts(args: list[str]) -> dict | None:
    opts: dict[str, str | None] = {"field": None, "value": None, "where": None, "out": None}
    i = 0
    while i < len(args):
        if args[i] in ("--field", "--value", "--where", "--out") and i + 1 < len(args):
            opts[args[i][2:]] = args[i + 1]
            i += 2
        else:
            return None
    if not opts["field"] or opts["value"] is None:
        return None
    return opts


def selftest() -> int:
    pak_rel, entry = SELFTEST_CANVAS
    try:
        document = _render(pak_rel, entry)
    except FileNotFoundError:
        print(f"selftest: SKIP (install/PAK not present: {pak_rel})")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"selftest: FAIL ({e})")
        return 1
    checks = [
        ("HTML mentions a UiTransform2dComponent-derived element",
         "UiTransform2dComponent" in document),
        ("HTML contains a positioned element", '<div class="lyshine-el' in document),
        ("HTML embeds the named model", 'id="lyshine-model"' in document),
        ("HTML is self-contained (no external src/href)",
         "src=\"http" not in document and "href=\"http" not in document),
    ]
    ok = all(v for _, v in checks)
    for name, value in checks:
        print(f"{'PASS' if value else 'FAIL'} {name}")
    print(f"selftest: {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "selftest":
        return selftest()
    if cmd == "render" and len(argv) >= 3:
        out = argv[argv.index("--out") + 1] if "--out" in argv else None
        return cmd_render(argv[1], argv[2], out, no_sprites="--no-sprites" in argv)
    if cmd == "set" and len(argv) >= 3:
        opts = _edit_opts(argv[3:])
        if opts is None:
            print(__doc__)
            return 2
        return cmd_set(argv[1], argv[2], opts["field"], opts["value"],
                       opts["where"], opts["out"])
    if cmd == "patch" and len(argv) >= 3:
        opts = _edit_opts(argv[3:])
        if opts is None or opts["out"] is None:
            print(__doc__)
            return 2
        return cmd_patch(argv[1], argv[2], opts["field"], opts["value"],
                         opts["out"], opts["where"])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
