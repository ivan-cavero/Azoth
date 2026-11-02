"""LyShine UI `.luac` reader + disassembler tests (stdlib unittest).

The client ships 1,100 compiled UI Lua scripts (`lyshineui/**.luac`) inside
`DataStrm*.pak`. This tool parses each payload's measured format (a 2-byte prefix
`04 00` then a standard Lua 5.1 little-endian dump) to an IR and a readable
listing, so a human can read what a UI script does without the game. These tests
build a small synthetic Lua 5.1 dump in code -- the same way `test_uicanvas`
builds a synthetic stream -- so the parser, the instruction-field decode and the
disassembler are trusted without the 71 GB install. The CLI must fail closed on
a bad prefix/signature/truncated dump, and the selftest skips gracefully when the
PAK is absent.
"""

from __future__ import annotations

import contextlib
import io
import pathlib
import struct
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _kind in ("", "corpus", "pe", "type", "pak", "wire", "eac", "ops"):
    _p = str(ROOT if _kind == "" else ROOT / _kind)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import luac  # noqa: E402

PREFIX = b"\x04\x00"
HEADER = b"\x1bLua" + bytes([0x51, 0x00, 0x01, 0x04, 0x08, 0x04, 0x08, 0x00])

# Lua 5.1 opcodes used by the tests (see luac.OPCODES).
MOVE, LOADK, GETUPVAL, GETGLOBAL, GETTABLE, SETTABLE, ADD, JMP, EQ, RETURN = (
    0, 1, 4, 5, 6, 9, 12, 22, 23, 30,
)
CLOSURE, FORPREP, SETLIST = 36, 32, 34
BITRK = 256


def lua_string(value: str | None) -> bytes:
    """A Lua dump string: u64 length including a trailing NUL, 0 meaning NULL."""
    if value is None:
        return (0).to_bytes(8, "little")
    raw = value.encode("utf-8") + b"\x00"
    return len(raw).to_bytes(8, "little") + raw


def c_nil() -> bytes:
    return b"\x00"


def c_bool(value: bool) -> bytes:
    return b"\x01" + bytes([1 if value else 0])


def c_num(value: float) -> bytes:
    return b"\x03" + struct.pack("<d", value)


def c_str(value: str) -> bytes:
    return b"\x04" + lua_string(value)


def abc(op: int, a: int = 0, b: int = 0, c: int = 0) -> int:
    return (op & 0x3F) | ((a & 0xFF) << 6) | ((c & 0x1FF) << 14) | ((b & 0x1FF) << 23)


def abx(op: int, a: int = 0, bx: int = 0) -> int:
    return (op & 0x3F) | ((a & 0xFF) << 6) | ((bx & 0x3FFFF) << 14)


def asbx(op: int, a: int = 0, sbx: int = 0) -> int:
    return abx(op, a, sbx + 131071)


def lua_function(
    source: str | None = None,
    code: tuple[int, ...] = (),
    constants: tuple[bytes, ...] = (),
    protos: tuple[bytes, ...] = (),
    upnames: tuple[str | None, ...] = (),
    *,
    linedefined: int = 0,
    lastlinedefined: int = 0,
    nups: int = 0,
    numparams: int = 0,
    is_vararg: int = 0,
    maxstack: int = 2,
    lineinfo: tuple[int, ...] = (),
    locvars: tuple[tuple[str, int, int], ...] = (),
) -> bytes:
    out = bytearray()
    out += lua_string(source)
    out += struct.pack("<i", linedefined) + struct.pack("<i", lastlinedefined)
    out += bytes([nups, numparams, is_vararg, maxstack])
    out += struct.pack("<I", len(code))
    for word in code:
        out += struct.pack("<I", word)
    out += struct.pack("<I", len(constants)) + b"".join(constants)
    out += struct.pack("<I", len(protos)) + b"".join(protos)
    out += struct.pack("<I", len(lineinfo))
    for line in lineinfo:
        out += struct.pack("<i", line)
    out += struct.pack("<I", len(locvars))
    for name, start, end in locvars:
        out += lua_string(name) + struct.pack("<i", start) + struct.pack("<i", end)
    out += struct.pack("<I", len(upnames)) + b"".join(lua_string(n) for n in upnames)
    return bytes(out)


def lua_dump(root: bytes) -> bytes:
    return PREFIX + HEADER + root


def sample_dump() -> bytes:
    """A small but complete dump: two functions, constants of all four kinds."""
    inner = lua_function(source="@inner.lua", code=(abc(RETURN, 0, 1),))
    root = lua_function(
        source="@test.lua",
        code=(
            abx(LOADK, 2, 0),
            abx(GETGLOBAL, 3, 1),
            asbx(JMP, 0, 2),
            abx(CLOSURE, 4, 0),
            abc(RETURN, 0, 1),
        ),
        constants=(c_str("hello"), c_str("print"), c_num(3.5), c_bool(True), c_nil()),
        protos=(inner,),
        upnames=("_ENV",),
        linedefined=1,
        lastlinedefined=9,
        numparams=2,
        is_vararg=1,
        maxstack=5,
        lineinfo=(1, 1, 2, 2, 3),
        locvars=(("x", 0, 3),),
    )
    return lua_dump(root)


class ParseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ir = luac.parse(sample_dump())

    def test_prefix_and_header_recorded(self) -> None:
        self.assertEqual(self.ir["prefix"], "0400")
        self.assertEqual(self.ir["header"]["version"], 0x51)
        self.assertEqual(self.ir["header"]["endianness"], 1)

    def test_function_fields_round_trip(self) -> None:
        root = self.ir["root"]
        self.assertEqual(root["source"], "@test.lua")
        self.assertEqual((root["linedefined"], root["lastlinedefined"]), (1, 9))
        self.assertEqual(root["numparams"], 2)
        self.assertEqual(root["is_vararg"], 1)
        self.assertEqual(root["maxstacksize"], 5)
        self.assertEqual(root["code"], [
            abx(LOADK, 2, 0), abx(GETGLOBAL, 3, 1), asbx(JMP, 0, 2),
            abx(CLOSURE, 4, 0), abc(RETURN, 0, 1),
        ])
        self.assertEqual(root["lineinfo"], [1, 1, 2, 2, 3])
        self.assertEqual(root["locvars"], [{"name": "x", "startpc": 0, "endpc": 3}])
        self.assertEqual(root["upvalues"], ["_ENV"])

    def test_constants_of_all_four_kinds(self) -> None:
        kinds = [(c["kind"], c["value"]) for c in self.ir["root"]["constants"]]
        self.assertEqual(kinds, [
            ("string", "hello"), ("string", "print"), ("number", 3.5),
            ("boolean", True), ("nil", None),
        ])

    def test_protos_nest(self) -> None:
        protos = self.ir["root"]["protos"]
        self.assertEqual(len(protos), 1)
        self.assertEqual(protos[0]["source"], "@inner.lua")
        self.assertEqual(protos[0]["code"], [abc(RETURN, 0, 1)])

    def test_summary_counts_functions_and_strings(self) -> None:
        summary = luac.summary(self.ir)
        self.assertEqual(summary["function_count"], 2)
        self.assertEqual(summary["instruction_count"], 6)
        self.assertEqual(summary["constant_count"], 5)
        self.assertEqual(summary["strings"], ["hello", "print"])


class DecodeTest(unittest.TestCase):
    def test_iabc_fields(self) -> None:
        inst = luac.decode_instruction(abc(MOVE, 2, 3, 5))
        self.assertEqual((inst["op"], inst["name"], inst["format"]), (0, "MOVE", "iABC"))
        self.assertEqual((inst["A"], inst["B"], inst["C"]), (2, 3, 5))

    def test_iabx_and_isbx_fields(self) -> None:
        inst = luac.decode_instruction(abx(LOADK, 1, 300))
        self.assertEqual((inst["A"], inst["Bx"]), (1, 300))
        self.assertEqual(inst["format"], "iABx")
        jump = luac.decode_instruction(asbx(JMP, 0, -3))
        self.assertEqual(jump["sBx"], -3)
        self.assertEqual(jump["format"], "iAsBx")

    def test_bitrk_and_indexk(self) -> None:
        self.assertEqual(luac.ISK(BITRK), True)
        self.assertEqual(luac.ISK(2), False)
        self.assertEqual(luac.INDEXK(BITRK | 2), 2)
        # GETTABLE with C = BITRK|1 resolves the constant operand, not a register.
        func = luac.parse(lua_dump(lua_function(
            code=(abc(GETTABLE, 0, 1, BITRK | 1),),
            constants=(c_nil(), c_str("key")),
        )))["root"]
        line = luac.disassemble(func)[1]
        self.assertIn('K1("key")', line)


class StringTest(unittest.TestCase):
    def test_null_string_is_none(self) -> None:
        func = luac.parse(lua_dump(lua_function(source=None)))["root"]
        self.assertIsNone(func["source"])

    def test_length_includes_and_strips_the_trailing_nul(self) -> None:
        func = luac.parse(lua_dump(lua_function(
            source=None, constants=(c_str("RequireScript"),),
            upnames=(None, "up"),
        )))["root"]
        self.assertEqual(func["constants"][0]["value"], "RequireScript")
        self.assertEqual(func["upvalues"], [None, "up"])


class DisassembleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ir = luac.parse(sample_dump())
        self.lines = luac.disassemble(self.ir["root"])

    def test_one_line_per_instruction_with_opcode_names(self) -> None:
        body = [line for line in self.lines if line and not line.startswith(";")]
        self.assertEqual(len(body), 6)  # 5 root + 1 inner
        self.assertTrue(any("LOADK" in line for line in body))
        self.assertTrue(any('R2 := K0("hello")' in line for line in body))
        self.assertTrue(any("Gbl[print]" in line for line in body))

    def test_nested_function_is_labelled(self) -> None:
        headers = [line for line in self.lines if line.startswith(";")]
        self.assertEqual(len(headers), 2)
        self.assertTrue(any("0.0" in line for line in headers))

    def test_upvalue_name_is_resolved(self) -> None:
        func = luac.parse(lua_dump(lua_function(
            code=(abc(GETUPVAL, 0, 0),), upnames=("self",),
        )))["root"]
        self.assertIn("R0 := self", luac.disassemble(func)[1])

    def test_register_constant_and_jump_render(self) -> None:
        self.assertTrue(any("pc +=" in line for line in self.lines))
        func = luac.parse(lua_dump(lua_function(
            code=(abc(ADD, 3, 1, 2),), constants=(),
        )))["root"]
        self.assertIn("R3 := R1 + R2", luac.disassemble(func)[1])


class FailureTest(unittest.TestCase):
    def test_bad_prefix_raises(self) -> None:
        with self.assertRaises(luac.LuacError):
            luac.parse(b"\x03\x00" + HEADER + lua_function())

    def test_bad_signature_raises(self) -> None:
        with self.assertRaises(luac.LuacError):
            luac.parse(PREFIX + b"\x1bLux" + HEADER[4:] + lua_function())

    def test_truncated_dump_raises(self) -> None:
        with self.assertRaises(luac.LuacError):
            luac.parse(sample_dump()[:-4])

    def test_cli_read_fails_closed_on_bad_dump(self) -> None:
        import pakread
        original = pakread.read_entry
        pakread.read_entry = lambda pak, entry: (b"\x04\x00nope", {})
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                rc = luac.cmd_read("P.pak", "bad.luac")
        finally:
            pakread.read_entry = original
        self.assertNotEqual(rc, 0)

    def test_cli_main_reports_usage(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(luac.main([]), 2)


class SelftestTest(unittest.TestCase):
    def test_absent_pak_skips_gracefully(self) -> None:
        original = luac.SELFTEST_ENTRY
        luac.SELFTEST_ENTRY = ("definitely-absent-part99.pak", "lyshineui/x.luac")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(luac.selftest(), 0)
        finally:
            luac.SELFTEST_ENTRY = original


if __name__ == "__main__":
    unittest.main()
