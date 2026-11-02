"""LyShine UI namer + HTML preview tests (stdlib unittest).

The renderer sits on top of the ObjectStream reader (`uicanvas`): it names each
element's class (from `lyshine-classes.json`) and each field (by the CRC32 of its
lowercase name), decodes the typed leaves the layout needs, and emits one static
self-contained HTML preview. These tests build a small synthetic canvas in code
-- the same way `test_uicanvas` builds a synthetic stream -- so the namer and the
renderer are trusted without the 71 GB client install. One selftest-shaped test
confirms the CLI skips gracefully when the install is absent.
"""

from __future__ import annotations

import base64
import contextlib
import html as html_module
import io
import pathlib
import sqlite3
import struct
import sys
import tempfile
import unittest
import uuid
import zipfile
import zlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _kind in ("", "corpus", "pe", "type", "pak", "wire", "eac", "ops"):
    _p = str(ROOT if _kind == "" else ROOT / _kind)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lyshine  # noqa: E402
import uicanvas  # noqa: E402

# Class GUIDs from research/derived/lyshine-classes.json (public O3DE RTTI).
ENTITY = uuid.UUID("75651658-8663-478d-9090-2432dfcafa44")
CANVAS = uuid.UUID("50b8cf6c-b19a-4d86-afe9-96efb820d422")
TRANSFORM = uuid.UUID("2751a5a5-3291-4a4d-9fc0-9cb0eb8d1de6")
ELEMENT = uuid.UUID("4a97d63e-ce7a-45b6-aae4-102db4334688")
ANCHORS = uuid.UUID("65d4346c-fb16-4cb0-9bdc-1185b122c4a9")
OFFSETS = uuid.UUID("f681ba9d-245c-4630-b20e-05dd752fad57")
VEC2 = uuid.UUID("3d80f623-c85c-4741-90d0-e4e66164e6bf")
FLOAT = uuid.UUID("ea2c3e90-afbe-44d4-a90d-faaf79baf93d")
BOOL = uuid.UUID("a0ca880c-afe4-43cb-926c-59ac48496112")
U64 = uuid.UUID("d6597933-47cd-4fc8-b911-63f3e2b0993a")
U32 = uuid.UUID("43da906b-7def-4ca8-9790-854106d3f983")
STRING = uuid.UUID("03aaab3f-5c47-5a66-9ebc-d5fa4db353c9")
ENTITYID = uuid.UUID("6383f1d3-bb27-4e6b-a49a-6409b2059eaa")

UNKNOWN_CLASS = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
UNKNOWN_CONTAINER = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
UNKNOWN_FIELD = 0xDEADBEEF  # no seed entry -> must render as "unknown deadbeef"

ENTITY_ID = 0x0A
PANEL_ID = 0x0C
LABEL_ID = 0x0D


def crc(name: str) -> int:
    return zlib.crc32(name.lower().encode("ascii")) & 0xFFFFFFFF


def f32(*values: float) -> bytes:
    return struct.pack(">" + "f" * len(values), *values)


def el(type_id: uuid.UUID, name: str | None = None, value: bytes | None = None,
       children: tuple[bytes, ...] = (), version: int | None = None) -> bytes:
    """Serialize one ObjectStream element (header + body + its own close tag)."""
    flags = uicanvas.FLAG_ELEMENT_HEADER
    out = bytearray()
    if name is not None:
        flags |= uicanvas.FLAG_HAS_NAME
    if version is not None:
        flags |= uicanvas.FLAG_HAS_VERSION
    if value is not None:
        flags |= uicanvas.FLAG_HAS_VALUE
        if len(value) <= 7:
            flags |= len(value)
        else:
            width = 1 if len(value) < 0x100 else 2 if len(value) < 0x10000 else 4
            flags |= uicanvas.FLAG_EXTRA_SIZE_FIELD | width
    out.append(flags)
    if name is not None:
        out += crc(name).to_bytes(4, "big")
    if version is not None:
        out.append(version)
    out += type_id.bytes
    if value is not None:
        if len(value) > 7:
            width = 1 if len(value) < 0x100 else 2 if len(value) < 0x10000 else 4
            out += len(value).to_bytes(width, "big")
        out += value
    for child in children:
        out += child
    out.append(uicanvas.FLAG_ELEMENT_END)
    return bytes(out)


def el_with_crc(type_id: uuid.UUID, name_crc: int, value: bytes) -> bytes:
    """A leaf whose name CRC has no seed entry (the honest 'unknown' case)."""
    flags = uicanvas.FLAG_ELEMENT_HEADER | uicanvas.FLAG_HAS_NAME | uicanvas.FLAG_HAS_VALUE | len(value)
    return (bytes([flags]) + name_crc.to_bytes(4, "big") + type_id.bytes
            + value + bytes([uicanvas.FLAG_ELEMENT_END]))


def entity_id_node(name: str, value: int) -> bytes:
    return el(ENTITYID, name, None, (el(U64, "Id", value.to_bytes(8, "big")),))


def transform(an: tuple, off: tuple, extra: tuple[bytes, ...] = ()) -> bytes:
    left, top, right, bottom = an
    ol, ot, orr, ob = off
    return el(TRANSFORM, "Element", None, (
        el(ANCHORS, "Anchors", None, (
            el(FLOAT, "Left", f32(left)), el(FLOAT, "Top", f32(top)),
            el(FLOAT, "Right", f32(right)), el(FLOAT, "Bottom", f32(bottom)),
        )),
        el(OFFSETS, "Offsets", None, (
            el(FLOAT, "Left", f32(ol)), el(FLOAT, "Top", f32(ot)),
            el(FLOAT, "Right", f32(orr)), el(FLOAT, "Bottom", f32(ob)),
        )),
        el(VEC2, "Scale", f32(1.0, 1.0)),
        *extra,
    ))


def synthetic_stream() -> bytes:
    """A valid ObjectStream: a canvas entity, a panel entity and a label."""
    panel = el(ENTITY, None, None, (
        entity_id_node("Id", PANEL_ID),
        el(STRING, "Name", b"Panel"),
        el(ELEMENT, "Components", None, (
            transform(
                (0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 200.0, 100.0),
                extra=(el_with_crc(BOOL, UNKNOWN_FIELD, b"\x01"),),
            ),
            el(ELEMENT, "Element", None, (
                el(U32, "Id", (1).to_bytes(4, "big")),
                el(UNKNOWN_CONTAINER, None, None, (
                    entity_id_node("ChildEntityId", LABEL_ID),
                    el(U64, None, (0).to_bytes(8, "big")),
                )),
            )),
            el(ELEMENT, "Element", None, (
                el(STRING, "Text", b"Hello"),
                el(UNKNOWN_CLASS, "Color", f32(1.0, 0.0, 0.0, 1.0)),
                el(FLOAT, "Alpha", f32(1.0)),
            )),
            # A component whose class is not in the map: must render as a dashed box.
            el(UNKNOWN_CLASS, "Element", None, ()),
        )),
    ))
    label = el(ENTITY, None, None, (
        entity_id_node("Id", LABEL_ID),
        el(STRING, "Name", b"Label"),
        el(ELEMENT, "Components", None, (
            transform((0.0, 0.0, 0.0, 0.0), (10.0, 10.0, 50.0, 30.0)),
            el(ELEMENT, "Element", None, (el(STRING, "Text", b"World"),)),
        )),
    ))
    root = el(ENTITY, None, None, (
        entity_id_node("Id", ENTITY_ID),
        el(STRING, "Name", b"Canvas"),
        el(ELEMENT, "Components", None, (
            el(CANVAS, "Element", None, (
                el(VEC2, "CanvasSize", f32(800.0, 600.0)),
                entity_id_node("RootElement", PANEL_ID),
            )),
            label,
            panel,
        )),
    ), version=2)
    return (bytes([uicanvas.STREAM_TAG]) + (3).to_bytes(4, "big") + root
            + bytes([uicanvas.FLAG_ELEMENT_END]))


def synthetic_ir() -> dict:
    return uicanvas.parse(synthetic_stream())


TEXT_COMPONENT = uuid.UUID("5b3fb2a7-5dc4-4033-a970-001cec85b6c4")
IMAGE_COMPONENT = uuid.UUID("bdbefd23-dbb4-4726-a32d-4feac24e51f6")
SEQUENCE_COMPONENT = uuid.UUID("bfac7909-3a56-4980-af7c-261a99d6371b")

# The image component's sprite reference is a named-blob leaf with no seed entry;
# the sequence component stores a folder path in a plain string leaf. Both CRCs are
# measured from the real canvases (see `sprite_ref_path`).
SPRITE_REF_CRC = 0x8DF2FDBE
SEQUENCE_SPRITE_CRC = 0xCEE077ED
SPRITE_TYPE_GUID = bytes.fromhex("59d5e20b34db4d8eb867d33cc2556355")


def leaf_crc(type_id: uuid.UUID, name_crc: int, value: bytes) -> bytes:
    """A leaf with an arbitrary name CRC and a value of any length."""
    flags = uicanvas.FLAG_ELEMENT_HEADER | uicanvas.FLAG_HAS_NAME | uicanvas.FLAG_HAS_VALUE
    width = 0
    if len(value) > 7:
        width = 1 if len(value) < 0x100 else 2 if len(value) < 0x10000 else 4
        flags |= uicanvas.FLAG_EXTRA_SIZE_FIELD | width
    else:
        flags |= len(value)
    out = bytearray([flags])
    out += name_crc.to_bytes(4, "big")
    out += type_id.bytes
    if width:
        out += len(value).to_bytes(width, "big")
    out += value
    out.append(uicanvas.FLAG_ELEMENT_END)
    return bytes(out)


def sprite_blob(path: str) -> bytes:
    """A UiImageComponent sprite reference: 16B id, 16B zeros, 16B type id, len, path."""
    head = bytes(16) + bytes(16) + SPRITE_TYPE_GUID
    assert len(head) == 48
    raw = path.encode("utf-8")
    return head + len(raw).to_bytes(8, "big") + raw


def sprite_stream(sprite: str | None = None, sequence: str | None = None) -> bytes:
    """A canvas whose one widget carries an image and/or a sequence component."""
    comps: list[bytes] = [transform((0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 200.0, 100.0))]
    if sprite is not None:
        comps.append(el(IMAGE_COMPONENT, "Element", None, (
            leaf_crc(UNKNOWN_CLASS, SPRITE_REF_CRC, sprite_blob(sprite)),
        )))
    if sequence is not None:
        comps.append(el(SEQUENCE_COMPONENT, "Element", None, (
            leaf_crc(STRING, SEQUENCE_SPRITE_CRC, sequence.encode("utf-8")),
        )))
    widget = el(ENTITY, None, None, (
        entity_id_node("Id", 0x31),
        el(STRING, "Name", b"Widget"),
        el(ELEMENT, "Components", None, tuple(comps)),
    ))
    root = el(ENTITY, None, None, (
        entity_id_node("Id", ENTITY_ID),
        el(STRING, "Name", b"Canvas"),
        el(ELEMENT, "Components", None, (
            el(CANVAS, "Element", None, (
                el(VEC2, "CanvasSize", f32(800.0, 600.0)),
                entity_id_node("RootElement", 0x31),
            )),
            widget,
        )),
    ), version=2)
    return (bytes([uicanvas.STREAM_TAG]) + (3).to_bytes(4, "big") + root
            + bytes([uicanvas.FLAG_ELEMENT_END]))


def fake_index(rows: list[tuple[str, str]]) -> sqlite3.Connection:
    """An in-memory pak index with the columns `sprite_entry` reads."""
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE entry (path TEXT, pak TEXT, ext TEXT, csize INT, "
                "usize INT, crc INT, method INT)")
    con.executemany("INSERT INTO entry VALUES (?, ?, '', 0, 0, 0, 15)", rows)
    return con


def tiny_rgba8_dds(width: int = 2, height: int = 2) -> bytes:
    """A minimal uncompressed RGBA8 DDS the decoder accepts."""
    header = bytearray(128)
    header[0:4] = b"DDS "
    struct.pack_into("<7I", header, 4, 124, 0x1007, height, width, 0, 0, 1)
    struct.pack_into("<4I", header, 76, 32, 0x41, 0, 32)
    struct.pack_into("<4I", header, 92, 0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000)
    pixels = bytes([0, 0, 255, 255]) * (width * height)
    return bytes(header) + pixels


def unique_stream() -> bytes:
    """A canvas whose editable fields each appear exactly once (no --where)."""
    widget = el(ENTITY, None, None, (
        entity_id_node("Id", 0x21),
        el(STRING, "Name", b"Widget"),
        el(ELEMENT, "Components", None, (
            transform((0.0, 0.0, 1.0, 1.0), (0.0, 0.0, 0.0, 0.0), extra=(
                el(FLOAT, "Rotation", f32(0.0)),
                el(VEC2, "Pivot", f32(0.5, 0.5)),
                el(BOOL, "ScaleToDevice", b"\x01"),
            )),
            el(TEXT_COMPONENT, "Element", None, (
                el(STRING, "Text", b"Hello"),
                el(UNKNOWN_CLASS, "Color", f32(1.0, 1.0, 1.0, 1.0)),
            )),
        )),
    ), version=2)
    return (bytes([uicanvas.STREAM_TAG]) + (3).to_bytes(4, "big") + widget
            + bytes([uicanvas.FLAG_ELEMENT_END]))


def leaf_values(ir: dict) -> list:
    """Every (name_crc, value) leaf in traversal order (for change isolation)."""
    out: list = []

    def walk(e: dict) -> None:
        if e["value"] is not None:
            out.append((e["name_crc"], e["value"]))
        for c in e["children"]:
            walk(c)

    walk(ir["root"])
    return out


def _find_leaf(ir: dict, name: str) -> dict:
    target = crc(name)

    def walk(e: dict):
        if e["name_crc"] == target:
            return e
        for c in e["children"]:
            found = walk(c)
            if found is not None:
                return found
        return None

    return walk(ir["root"])


class NamingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.classes, self.fields = lyshine.load_maps()

    def test_class_named_from_the_map(self) -> None:
        self.assertEqual(lyshine.class_name(str(TRANSFORM), self.classes),
                         "LyShine::UiTransform2dComponent")
        self.assertEqual(lyshine.class_name(str(VEC2), self.classes), "AZ::Vector2")

    def test_unknown_class_is_not_invented(self) -> None:
        self.assertIsNone(lyshine.class_name(str(UNKNOWN_CLASS), self.classes))

    def test_field_named_by_crc(self) -> None:
        self.assertEqual(lyshine.field_label(crc("Left"), self.fields), "Left")
        self.assertEqual(lyshine.field_label(crc("CanvasSize"), self.fields), "CanvasSize")
        self.assertEqual(lyshine.field_label(crc("ChildEntityId"), self.fields), "ChildEntityId")

    def test_unknown_field_renders_as_placeholder(self) -> None:
        self.assertEqual(lyshine.field_label(UNKNOWN_FIELD, self.fields),
                         f"unknown {UNKNOWN_FIELD:08x}")
        self.assertIsNone(lyshine.field_name(UNKNOWN_FIELD, self.fields))


class DecodeTest(unittest.TestCase):
    def test_vector2_decodes_two_floats_big_endian(self) -> None:
        self.assertEqual(lyshine.decode_leaf("CanvasSize", "AZ::Vector2", f32(800.0, 600.0)),
                         [800.0, 600.0])

    def test_float_and_bool_and_string(self) -> None:
        self.assertAlmostEqual(lyshine.decode_leaf("Alpha", "float", f32(0.5)), 0.5)
        self.assertIs(lyshine.decode_leaf("ScaleToDevice", "bool", b"\x01"), True)
        self.assertEqual(lyshine.decode_leaf("Text", "AZStd::string", b"Hello"), "Hello")

    def test_unknown_leaf_keeps_bytes_without_guessing(self) -> None:
        self.assertEqual(lyshine.decode_leaf(None, None, b"\x01\x02"),
                         {"bytes": 2, "hex": "0102"})


class ModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.model = lyshine.build_model(synthetic_ir())

    def test_canvas_size_and_root_resolve(self) -> None:
        self.assertEqual(self.model["canvas"]["size"], [800.0, 600.0])
        self.assertEqual(self.model["canvas"]["root_entity_id"], PANEL_ID)

    def test_positioned_element_per_decoded_entity(self) -> None:
        # The canvas holder carries no transform; the panel and the label do.
        self.assertEqual(self.model["counts"]["entities"], 3)
        self.assertEqual(len(self.model["scene"]), 2)
        by_name = {s["name"]: s for s in self.model["scene"]}
        self.assertEqual((by_name["Panel"]["x"], by_name["Panel"]["w"]), (0.0, 200.0))
        self.assertEqual((by_name["Label"]["x"], by_name["Label"]["w"]), (10.0, 40.0))

    def test_scene_keeps_text_and_color(self) -> None:
        by_name = {s["name"]: s for s in self.model["scene"]}
        self.assertEqual(by_name["Panel"]["text"], "Hello")
        self.assertEqual(by_name["Panel"]["color"], [1.0, 0.0, 0.0, 1.0])
        self.assertEqual(by_name["Label"]["text"], "World")

    def test_unknown_field_and_class_are_reported(self) -> None:
        self.assertIn(f"{UNKNOWN_FIELD:08x}", self.model["unknown_fields"])
        self.assertIn(str(UNKNOWN_CLASS), self.model["unknown_classes"])


class RenderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.model = lyshine.build_model(synthetic_ir())
        self.document = lyshine.render_html(self.model, title="synthetic")

    def test_one_positioned_box_per_scene_entity(self) -> None:
        self.assertEqual(self.document.count('class="lyshine-el'), len(self.model["scene"]))
        self.assertIn("position:absolute;left:0px;top:0px;width:200px;height:100px", self.document)

    def test_mentions_transform_component_and_is_self_contained(self) -> None:
        self.assertIn("UiTransform2dComponent", self.document)
        self.assertIn('id="lyshine-model"', self.document)
        self.assertNotIn("http://", self.document.split("lyshine-model")[0])

    def test_unknown_inventory_renders(self) -> None:
        # The panel carries an unknown component class -> its box is dashed and
        # labelled, and the unknown field is listed honestly.
        self.assertEqual(self.document.count('class="lyshine-el lyshine-unknown-box"'), 1)
        self.assertIn(f'unknown {UNKNOWN_CLASS}', self.document)
        self.assertIn(f"unknown {UNKNOWN_FIELD:08x}", self.document)
        self.assertIn(str(UNKNOWN_CONTAINER), self.document)

    def test_html_escapes_text(self) -> None:
        model = lyshine.build_model(synthetic_ir())
        model["scene"][0]["text"] = "<script>alert(1)</script>"
        document = lyshine.render_html(model)
        self.assertIn(html_module.escape("<script>alert(1)</script>"), document)


class EditTest(unittest.TestCase):
    """Named-field edits: typed values, minimal byte churn, fail-closed guards."""

    def setUp(self) -> None:
        self.data = unique_stream()

    def _apply(self, field: str, value: str, where: str | None = None) -> bytes:
        return lyshine.edit_canvas_bytes(self.data, field, value, where)

    def _only_change(self, after: bytes):
        before_leaves = leaf_values(uicanvas.parse(self.data))
        after_leaves = leaf_values(uicanvas.parse(after))
        self.assertEqual(len(before_leaves), len(after_leaves))
        changed = [i for i, (x, y) in enumerate(zip(before_leaves, after_leaves)) if x != y]
        return changed, after_leaves

    def test_unedited_canvas_stays_byte_exact(self) -> None:
        self.assertEqual(uicanvas.serialize(uicanvas.parse(self.data)), self.data)

    def test_float_edit_changes_only_that_value(self) -> None:
        after = self._apply("Rotation", "1.5")
        self.assertEqual(len(after), len(self.data))
        changed, leaves = self._only_change(after)
        self.assertEqual(len(changed), 1)
        name_crc, value = leaves[changed[0]]
        self.assertEqual(name_crc, crc("Rotation"))
        self.assertEqual(value, f32(1.5))

    def test_vector2_edit_changes_only_that_value(self) -> None:
        after = self._apply("Pivot", "0.25,0.75")
        self.assertEqual(len(after), len(self.data))
        changed, leaves = self._only_change(after)
        self.assertEqual(len(changed), 1)
        name_crc, value = leaves[changed[0]]
        self.assertEqual(name_crc, crc("Pivot"))
        self.assertEqual(value, f32(0.25, 0.75))

    def test_bool_edit_changes_only_that_value(self) -> None:
        after = self._apply("ScaleToDevice", "false")
        self.assertEqual(len(after), len(self.data))
        changed, leaves = self._only_change(after)
        self.assertEqual(len(changed), 1)
        name_crc, value = leaves[changed[0]]
        self.assertEqual(name_crc, crc("ScaleToDevice"))
        self.assertEqual(value, b"\x00")

    def test_same_length_string_edit_changes_only_that_value(self) -> None:
        after = self._apply("Text", "Hola!")
        self.assertEqual(len(after), len(self.data))
        changed, leaves = self._only_change(after)
        self.assertEqual(len(changed), 1)
        name_crc, value = leaves[changed[0]]
        self.assertEqual(name_crc, crc("Text"))
        self.assertEqual(value, b"Hola!")

    def test_color_edit_uses_the_field_name_type(self) -> None:
        after = self._apply("Color", "0.5,0.25,0.1,1.0")
        self.assertEqual(len(after), len(self.data))
        changed, leaves = self._only_change(after)
        self.assertEqual(len(changed), 1)
        self.assertEqual(leaves[changed[0]][1], f32(0.5, 0.25, 0.1, 1.0))

    def test_length_changing_string_edit_re_encodes_size(self) -> None:
        after = self._apply("Text", "Hello world!")
        # 5 inline bytes -> 1 size byte + 12 value bytes
        self.assertEqual(len(after), len(self.data) + 8)
        node = _find_leaf(uicanvas.parse(after), "Text")
        self.assertEqual(node["value"], b"Hello world!")
        self.assertTrue(node["flags"] & uicanvas.FLAG_EXTRA_SIZE_FIELD)
        self.assertEqual(node["flags"] & uicanvas.VALUE_SIZE_MASK, 1)

    def test_missing_field_is_refused(self) -> None:
        with self.assertRaises(lyshine.EditError):
            self._apply("NoSuchField", "1")

    def test_undecodable_value_is_refused(self) -> None:
        with self.assertRaises(lyshine.EditError):
            self._apply("Rotation", "not-a-number")

    def test_ambiguous_field_without_where_is_refused(self) -> None:
        with self.assertRaises(lyshine.EditError):
            lyshine.edit_canvas_bytes(synthetic_stream(), "Name", "Renamed")

    def test_where_disambiguates_by_entity_name(self) -> None:
        after = lyshine.edit_canvas_bytes(synthetic_stream(), "Name", "Panel2", where="Panel")
        names = [v for n, v in leaf_values(uicanvas.parse(after)) if n == crc("Name")]
        self.assertIn(b"Panel2", names)
        self.assertIn(b"Label", names)  # the other entity is untouched

    def test_where_disambiguates_by_class_name(self) -> None:
        # `Text` appears only under UiTextComponent in the unique stream, but the
        # class selector must also work to narrow a field.
        after = self._apply("Text", "World", where="LyShine::UiTextComponent")
        self.assertEqual(_find_leaf(uicanvas.parse(after), "Text")["value"], b"World")


class CliTest(unittest.TestCase):
    """`set`/`patch` commands fail closed and re-read the written pak."""

    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def _patch_read_entry(self, fake) -> None:
        import pakread
        import pakwrite
        self._orig = (pakread.read_entry, pakwrite.read_entry)
        pakread.read_entry = fake
        pakwrite.read_entry = fake

    def _restore(self) -> None:
        import pakread
        import pakwrite
        pakread.read_entry, pakwrite.read_entry = self._orig

    def test_set_missing_field_exits_nonzero_and_writes_no_file(self) -> None:
        self._patch_read_entry(lambda p, e: (unique_stream(), {"pak": p, "path": e}))
        out = self.tmp / "edited.dynamicuicanvas"
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = lyshine.cmd_set("X.pak", "e", "NoSuchField", "1", None, str(out))
        finally:
            self._restore()
        self.assertNotEqual(rc, 0)
        self.assertFalse(out.exists())

    def test_set_writes_the_edited_canvas(self) -> None:
        self._patch_read_entry(lambda p, e: (unique_stream(), {"pak": p, "path": e}))
        out = self.tmp / "edited.dynamicuicanvas"
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = lyshine.cmd_set("X.pak", "e", "Rotation", "1.5", None, str(out))
        finally:
            self._restore()
        self.assertEqual(rc, 0)
        self.assertEqual(out.read_bytes(), lyshine.edit_canvas_bytes(unique_stream(), "Rotation", "1.5"))

    def test_patch_pak_re_reads_to_the_edited_bytes(self) -> None:
        self._patch_read_entry(lambda p, e: (unique_stream(), {"pak": p, "path": e}))
        out = self.tmp / "patch.pak"
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = lyshine.cmd_patch("X.pak", "e", "Text", "Hello world!", str(out))
        finally:
            self._restore()
        self.assertEqual(rc, 0)
        with zipfile.ZipFile(out) as z:
            self.assertEqual(z.read("e"),
                             lyshine.edit_canvas_bytes(unique_stream(), "Text", "Hello world!"))


class SpriteTest(unittest.TestCase):
    """The image/sequence sprite reference, read from the canvas (T6)."""

    def test_sprite_ref_path_reads_the_embedded_path(self) -> None:
        self.assertEqual(lyshine.sprite_ref_path(sprite_blob("lyshineui/a/b.dds")),
                         "lyshineui/a/b.dds")

    def test_sprite_ref_path_none_for_empty_or_truncated(self) -> None:
        self.assertIsNone(lyshine.sprite_ref_path(None))
        self.assertIsNone(lyshine.sprite_ref_path(bytes(56)))       # length 0 -> no path
        blob = sprite_blob("lyshineui/a/b.dds")
        self.assertIsNone(lyshine.sprite_ref_path(blob[:-3]))       # path truncated
        self.assertIsNone(lyshine.sprite_ref_path(blob[:40]))       # header truncated

    def test_model_carries_the_image_sprite_path(self) -> None:
        model = lyshine.build_model(uicanvas.parse(sprite_stream(sprite="lyshineui/a/b.dds")))
        self.assertEqual([e["sprite"] for e in model["scene"] if e["sprite"]],
                         ["lyshineui/a/b.dds"])

    def test_model_carries_the_sequence_folder(self) -> None:
        model = lyshine.build_model(uicanvas.parse(sprite_stream(sequence="lyshineui/images/seq")))
        self.assertEqual([e["sprite"] for e in model["scene"] if e["sprite"]],
                         ["lyshineui/images/seq"])

    def test_model_sprite_is_none_without_a_sprite_component(self) -> None:
        model = lyshine.build_model(synthetic_ir())
        self.assertTrue(all(e["sprite"] is None for e in model["scene"]))

    def test_render_embeds_a_data_uri(self) -> None:
        model = lyshine.build_model(uicanvas.parse(sprite_stream(sprite="lyshineui/a/b.dds")))
        uri = "data:image/png;base64,AAAA"
        document = lyshine.render_html(model, sprites={"lyshineui/a/b.dds": uri})
        self.assertIn(f"background-image:url({uri})", document)
        self.assertIn('data-sprite="lyshineui/a/b.dds"', document)

    def test_render_without_a_sprite_map_has_no_image(self) -> None:
        model = lyshine.build_model(uicanvas.parse(sprite_stream(sprite="lyshineui/a/b.dds")))
        self.assertNotIn("background-image", lyshine.render_html(model))

    def test_unresolved_sprite_is_not_invented(self) -> None:
        model = lyshine.build_model(uicanvas.parse(sprite_stream(sprite="lyshineui/a/b.dds")))
        document = lyshine.render_html(
            model, sprites={"other/path.dds": "data:image/png;base64,AAAA"})
        self.assertNotIn("background-image", document)


class SpriteLoadTest(unittest.TestCase):
    """Resolve a canvas sprite path to PNG bytes through the pak index (T6)."""

    def test_entry_exact_file(self) -> None:
        con = fake_index([("lyshineui/a/b.dds", "DataStrm-part3.pak")])
        self.assertEqual(lyshine.sprite_entry("lyshineui/a/b.dds", con),
                         ("DataStrm-part3.pak", "lyshineui/a/b.dds"))

    def test_entry_sequence_folder_takes_the_first_frame(self) -> None:
        con = fake_index([("lyshineui/images/seq/blue_01.dds", "P.pak"),
                          ("lyshineui/images/seq/blue_00.dds", "P.pak")])
        self.assertEqual(lyshine.sprite_entry("lyshineui/images/seq", con),
                         ("P.pak", "lyshineui/images/seq/blue_00.dds"))

    def test_entry_missing_returns_none(self) -> None:
        self.assertIsNone(lyshine.sprite_entry("nope/none.dds", fake_index([])))

    def test_data_uri_png_passthrough(self) -> None:
        png = b"\x89PNG\r\n\x1a\nhello"
        uri = lyshine.sprite_data_uri("P.pak", "a/b.png", lambda pak, e: png)
        self.assertEqual(uri, "data:image/png;base64," + base64.b64encode(png).decode())

    def test_data_uri_decodes_a_dds(self) -> None:
        uri = lyshine.sprite_data_uri("P.pak", "a/b.dds", lambda pak, e: tiny_rgba8_dds())
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        raw = base64.b64decode(uri.split(",", 1)[1])
        self.assertTrue(raw.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_load_sprites_skips_unresolved_paths(self) -> None:
        model = lyshine.build_model(uicanvas.parse(sprite_stream(sprite="lyshineui/a/b.png")))
        con = fake_index([("lyshineui/a/b.png", "P.pak")])
        sprites = lyshine.load_sprites(model, con, lambda pak, e: b"\x89PNG\r\n\x1a\nx")
        self.assertEqual(set(sprites), {"lyshineui/a/b.png"})


class SelftestTest(unittest.TestCase):
    def test_absent_install_skips_gracefully(self) -> None:
        original = lyshine.SELFTEST_CANVAS
        lyshine.SELFTEST_CANVAS = ("definitely-absent-part99.pak",
                                   "lyshineui/benchmark/fpsscreen.dynamicuicanvas")
        try:
            # selftest prints; keep the suite output clean and deterministic.
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(lyshine.selftest(), 0)
        finally:
            lyshine.SELFTEST_CANVAS = original


if __name__ == "__main__":
    unittest.main()
