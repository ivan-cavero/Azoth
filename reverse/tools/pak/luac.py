#!/usr/bin/env python3
r"""Read and disassemble a New World LyShine UI `.luac` script.

WHY THIS EXISTS
===============
The LyShine UI pipeline (`odd/tasks/lyshine-ui.md`, task T7) keeps 1,100 compiled
Lua scripts under `lyshineui/` in `DataStrm*.pak` (measured by `uiassets`, T2).
They are the UI *behaviours* -- what a button click does, how a screen wires its
widgets -- so they cannot be read from the canvas layout alone. This is a
DISASSEMBLER, not a decompiler: it parses the bytecode to an IR and prints a
readable listing (prototypes, constants/strings, upvalues, instructions with
named opcodes and resolved operands), so a human can read what a script does.

MEASURED FORMAT (client 1.460.6033.6024067; do not re-derive)
============================================================
Every one of the 1,100 `.luac` payloads is a 2-byte prefix `04 00` followed by a
standard Lua 5.1 dump, LITTLE-ENDIAN. The prefix is constant across all 1,100 and
its meaning is unknown -- recorded, never interpreted. The 12-byte dump header is
`\x1bLua` + version 0x51 + format 0x00 + endianness 0x01 + sizeof(int)=4 +
sizeof(size_t)=8 + sizeof(Instruction)=4 + sizeof(lua_Number)=8 + integral=0.
Then `LoadFunction(5.1)`: source(string), linedefined/ lastlinedefined(int32),
nups/numparams/is_vararg/maxstacksize(u8), code (n x u32 Instruction), constants
(n x [type u8: 0=nil, 1=boolean+u8, 3=lua_Number f64, 4=string]), protos
(n x function), debug (lineinfo, locvars, upvalue names). A string is a u64
length; 0 is NULL; otherwise the length INCLUDES a trailing NUL byte that is
stripped. This reads UI behaviours only -- no game asset bytes are ever written
to the repo.

The Lua 5.1 instruction encoding below is from the public lopcodes.h:
iABC = op 6 bits, A 8, C 9, B 9 (bits 0-5 op, 6-13 A, 14-22 C, 23-31 B);
iABx = op, A, Bx 18 bits; iAsBx = same as ABx with sBx = Bx - 131071. BITRK =
1<<8 (256); ISK(x) = x & BITRK; INDEXK = x & ~BITRK. MAXARG_sBx = 131071.

Usage:
    python ef.py re luac read <pak> <entry>      # summary + string list
    python ef.py re luac dis <pak> <entry>       # listing
    python ef.py re luac strings <pak> <entry>   # unique strings only
    python ef.py re luac selftest
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # reverse/tools
sys.path.insert(0, str(Path(__file__).resolve().parent))       # reverse/tools/pak
import pakread  # noqa: E402

PREFIX = b"\x04\x00"
SIGNATURE = b"\x1bLua"
VERSION = 0x51
FORMAT = 0x00
ENDIANNESS = 0x01
SIZES = (4, 8, 4, 8)
INTEGRAL = 0

HEADER_BYTES = 12  # \x1bLua + version/format/endianness + five size bytes

# The 38 Lua 5.1 opcodes 0..37 and their instruction format (public lopcodes.h).
OPCODES: tuple[tuple[str, str], ...] = (
    ("MOVE", "iABC"), ("LOADK", "iABx"), ("LOADBOOL", "iABC"), ("LOADNIL", "iABC"),
    ("GETUPVAL", "iABC"), ("GETGLOBAL", "iABx"), ("GETTABLE", "iABC"),
    ("SETGLOBAL", "iABx"), ("SETUPVAL", "iABC"), ("SETTABLE", "iABC"),
    ("NEWTABLE", "iABC"), ("SELF", "iABC"), ("ADD", "iABC"), ("SUB", "iABC"),
    ("MUL", "iABC"), ("DIV", "iABC"), ("MOD", "iABC"), ("POW", "iABC"),
    ("UNM", "iABC"), ("NOT", "iABC"), ("LEN", "iABC"), ("CONCAT", "iABC"),
    ("JMP", "iAsBx"), ("EQ", "iABC"), ("LT", "iABC"), ("LE", "iABC"),
    ("TEST", "iABC"), ("TESTSET", "iABC"), ("CALL", "iABC"), ("TAILCALL", "iABC"),
    ("RETURN", "iABC"), ("FORLOOP", "iAsBx"), ("FORPREP", "iAsBx"),
    ("TFORLOOP", "iABC"), ("SETLIST", "iABC"), ("CLOSE", "iABC"),
    ("CLOSURE", "iABx"), ("VARARG", "iABC"),
)

BITRK = 1 << 8          # a constant operand instead of a register (lopcodes.h)
MAXARG_SBX = 131071


def ISK(x: int) -> bool:
    """True when operand `x` is a constant index, not a register (lopcodes.h)."""
    return bool(x & BITRK)


def INDEXK(x: int) -> int:
    """The constant index inside a BITRK-tagged operand (lopcodes.h)."""
    return x & ~BITRK


LFIELDS_PER_FLUSH = 50  # SETLIST blocks a next-instruction extra arg (lopcodes.h)

BINARY = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "MOD": "%", "POW": "^"}
UNARY = {"UNM": "-", "NOT": "not ", "LEN": "#"}
COMPARE = {"EQ": "==", "LT": "<", "LE": "<="}

SELFTEST_ENTRY = ("DataStrm-part3.pak", "lyshineui/_common/basescreen.luac")


class LuacError(ValueError):
    """A `.luac` payload is not the measured 2-byte prefix + Lua 5.1 dump."""


class _Reader:
    """A little-endian cursor over a dump; every short read fails closed."""

    __slots__ = ("data", "pos")

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read(self, count: int) -> bytes:
        end = self.pos + count
        if end > len(self.data):
            raise LuacError(
                f"truncated dump at {self.pos}: need {count} bytes, "
                f"{len(self.data) - self.pos} left")
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def u8(self) -> int:
        return self.read(1)[0]

    def u32(self) -> int:
        return int.from_bytes(self.read(4), "little")

    def i32(self) -> int:
        return int.from_bytes(self.read(4), "little", signed=True)

    def u64(self) -> int:
        return int.from_bytes(self.read(8), "little")


def _read_string(r: _Reader) -> str | None:
    """A dump string: u64 length; 0 is NULL, else strip the trailing NUL."""
    length = r.u64()
    if length == 0:
        return None
    raw = r.read(length)
    if raw.endswith(b"\x00"):
        raw = raw[:-1]
    return raw.decode("utf-8", "replace")


def _read_constant(r: _Reader) -> dict:
    tag = r.u8()
    if tag == 0:
        return {"kind": "nil", "value": None}
    if tag == 1:
        return {"kind": "boolean", "value": r.u8() != 0}
    if tag == 3:
        return {"kind": "number", "value": struct.unpack("<d", r.read(8))[0]}
    if tag == 4:
        return {"kind": "string", "value": _read_string(r)}
    raise LuacError(f"unknown constant type {tag} at {r.pos - 1}")


def _parse_function(r: _Reader) -> dict:
    source = _read_string(r)
    linedefined = r.i32()
    lastlinedefined = r.i32()
    nups, numparams, is_vararg, maxstacksize = (r.u8() for _ in range(4))
    code = [r.u32() for _ in range(r.u32())]
    constants = [_read_constant(r) for _ in range(r.u32())]
    protos = [_parse_function(r) for _ in range(r.u32())]
    lineinfo = [r.i32() for _ in range(r.u32())]
    locvars = [
        {"name": _read_string(r), "startpc": r.i32(), "endpc": r.i32()}
        for _ in range(r.u32())
    ]
    upvalues = [_read_string(r) for _ in range(r.u32())]
    return {
        "source": source,
        "linedefined": linedefined,
        "lastlinedefined": lastlinedefined,
        "nups": nups,
        "numparams": numparams,
        "is_vararg": is_vararg,
        "maxstacksize": maxstacksize,
        "code": code,
        "constants": constants,
        "protos": protos,
        "lineinfo": lineinfo,
        "locvars": locvars,
        "upvalues": upvalues,
    }


def parse(data: bytes) -> dict:
    """Parse a `.luac` payload into a tree of functions. Fails closed."""
    if len(data) < len(PREFIX) + HEADER_BYTES:
        raise LuacError(f"payload too short: {len(data)} bytes")
    if data[:len(PREFIX)] != PREFIX:
        raise LuacError(f"bad prefix {data[:len(PREFIX)].hex()}, expected 0400")
    header = data[len(PREFIX):len(PREFIX) + HEADER_BYTES]
    if header[:4] != SIGNATURE:
        raise LuacError(f"bad Lua signature {header[:4]!r}, expected {SIGNATURE!r}")
    version, fmt, endian, *sizes = header[4:]
    integral = sizes.pop()
    if version != VERSION:
        raise LuacError(f"unsupported Lua version {version:#x}, expected 0x51")
    if fmt != FORMAT:
        raise LuacError(f"unsupported dump format {fmt}, expected 0")
    if endian != ENDIANNESS:
        raise LuacError(f"unsupported endianness {endian}, expected little-endian 1")
    if tuple(sizes) != SIZES or integral != INTEGRAL:
        raise LuacError(f"unsupported type sizes {tuple(sizes)} integral={integral}")
    r = _Reader(data[len(PREFIX):])
    r.pos = HEADER_BYTES
    root = _parse_function(r)
    if r.pos != len(r.data):
        raise LuacError(f"{len(r.data) - r.pos} trailing bytes after the dump")
    return {
        "prefix": PREFIX.hex(),
        "header": {
            "signature": header[:4].decode("latin-1"),
            "version": version,
            "format": fmt,
            "endianness": endian,
            "sizeof_int": sizes[0],
            "sizeof_size_t": sizes[1],
            "sizeof_instruction": sizes[2],
            "sizeof_lua_number": sizes[3],
            "integral": integral,
        },
        "root": root,
    }


def decode_instruction(word: int) -> dict:
    """Decode one u32 Instruction per lopcodes.h; `name` is None past opcode 37."""
    op = word & 0x3F
    inst = {
        "word": word,
        "op": op,
        "name": OPCODES[op][0] if op < len(OPCODES) else None,
        "format": OPCODES[op][1] if op < len(OPCODES) else None,
        "A": (word >> 6) & 0xFF,
        "B": (word >> 23) & 0x1FF,
        "C": (word >> 14) & 0x1FF,
        "Bx": (word >> 14) & 0x3FFFF,
    }
    inst["sBx"] = inst["Bx"] - MAXARG_SBX
    return inst


def _number(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


def _const_repr(func: dict, index: int) -> str:
    if index >= len(func["constants"]):
        return "?"
    constant = func["constants"][index]
    kind = constant["kind"]
    if kind == "string":
        return f'"{constant["value"]}"'
    if kind == "number":
        return _number(constant["value"])
    if kind == "boolean":
        return "true" if constant["value"] else "false"
    return "nil"


def _rk(func: dict, x: int) -> str:
    """A register operand `R{n}`, or a constant `K{i}(value)` when BITRK is set."""
    if ISK(x):
        return f"K{INDEXK(x)}({_const_repr(func, INDEXK(x))})"
    return f"R{x}"


def _global(func: dict, bx: int) -> str:
    if bx < len(func["constants"]) and func["constants"][bx]["kind"] == "string":
        return func["constants"][bx]["value"]
    return f"K{bx}"


def _upvalue(func: dict, b: int) -> str:
    names = func["upvalues"]
    if b < len(names) and names[b]:
        return str(names[b])
    return f"U{b}"


def _register_range(a: int, b: int) -> str:
    return f"R{a}..R{b}" if b > a else f"R{a}"


def _operands(inst: dict, func: dict, pc: int) -> str:
    """A readable operand string for one instruction, resolving names."""
    name, a, b, c = inst["name"], inst["A"], inst["B"], inst["C"]
    bx, sbx = inst["Bx"], inst["sBx"]
    if name in BINARY:
        return f"R{a} := {_rk(func, b)} {BINARY[name]} {_rk(func, c)}"
    if name in UNARY:
        return f"R{a} := {UNARY[name]}{_rk(func, b)}"
    if name in COMPARE:
        return f"if ({_rk(func, b)} {COMPARE[name]} {_rk(func, c)}) == {a != 0} then pc++"
    if name == "MOVE":
        return f"R{a} := R{b}"
    if name == "LOADK":
        return f"R{a} := K{bx}({_const_repr(func, bx)})"
    if name == "LOADBOOL":
        return f"R{a} := {b != 0}" + ("; pc++" if c else "")
    if name == "LOADNIL":
        return f"{_register_range(a, b)} := nil"
    if name == "GETUPVAL":
        return f"R{a} := {_upvalue(func, b)}"
    if name == "GETGLOBAL":
        return f"R{a} := Gbl[{_global(func, bx)}]"
    if name == "GETTABLE":
        return f"R{a} := R{b}[{_rk(func, c)}]"
    if name == "SETGLOBAL":
        return f"Gbl[{_global(func, bx)}] := R{a}"
    if name == "SETUPVAL":
        return f"{_upvalue(func, b)} := R{a}"
    if name == "SETTABLE":
        return f"R{a}[{_rk(func, b)}] := {_rk(func, c)}"
    if name == "NEWTABLE":
        return f"R{a} := {{}} (array {b}, hash {c})"
    if name == "SELF":
        return f"R{a + 1} := R{b}; R{a} := R{b}[{_rk(func, c)}]"
    if name == "CONCAT":
        return f"R{a} := {_register_range(b, c)}"
    if name == "JMP":
        return f"pc += {sbx} ; -> {pc + 1 + sbx}"
    if name == "TEST":
        return f"if R{a} <=> {c != 0} then pc++"
    if name == "TESTSET":
        return (f"if R{b} <=> {c != 0} then R{a} := R{b} else pc++")
    if name == "CALL":
        args = "top" if b == 0 else f"R{a + 1}..R{a + b - 1}"
        results = "mult" if c == 0 else "none" if c == 1 else f"R{a}..R{a + c - 2}"
        return f"{results} := R{a}({args})"
    if name == "TAILCALL":
        args = "top" if b == 0 else f"R{a + 1}..R{a + b - 1}"
        return f"return R{a}({args})"
    if name == "RETURN":
        if b == 1:
            return "return"
        if b == 0:
            return f"return R{a}..top"
        return f"return {_register_range(a, a + b - 2)}"
    if name == "FORLOOP":
        return (f"R{a} += R{a + 2}; if R{a} <= R{a + 1} then pc += {sbx + 1}; "
                f"R{a + 3} := R{a}")
    if name == "FORPREP":
        return f"R{a} -= R{a + 2}; pc += {sbx}"
    if name == "TFORLOOP":
        return (f"if R{a + 1} ~= nil then R{a} := R{a + 1} else pc += {c + 1}")
    if name == "SETLIST":
        extra = " (extra arg from next instruction)" if c == 0 else ""
        return f"R{a}[{c * LFIELDS_PER_FLUSH}..] := R{a + 1}..R{a + b}{extra}"
    if name == "CLOSE":
        return f"close upvalues >= R{a}"
    if name == "CLOSURE":
        return f"R{a} := proto[{bx}]"
    if name == "VARARG":
        return f"{_register_range(a, a + b - 2)} := ..." if b else f"R{a}..top := ..."
    return f"op {inst['op']}"


def _header_line(func: dict, label: str) -> str:
    source = func["source"] or "?"
    return (f"; function {label}  source={source}  "
            f"lines {func['linedefined']}-{func['lastlinedefined']}  "
            f"params {func['numparams']}  vararg {func['is_vararg']}  "
            f"maxstack {func['maxstacksize']}  nups {func['nups']}")


def disassemble(func: dict, label: str = "0") -> list[str]:
    """One line per instruction, then a recursively labelled block per proto."""
    lines = [_header_line(func, label)]
    for pc, word in enumerate(func["code"]):
        inst = decode_instruction(word)
        if inst["name"] is None:
            lines.append(f"{pc:4}  ???        {word:#010x}")
        else:
            lines.append(f"{pc:4}  {inst['name']:<10} {_operands(inst, func, pc)}")
    for i, proto in enumerate(func["protos"]):
        lines.append("")
        lines.extend(disassemble(proto, f"{label}.{i}"))
    return lines


def _walk(func: dict):
    yield func
    for proto in func["protos"]:
        yield from _walk(proto)


def strings(ir: dict) -> list[str]:
    """Every distinct string constant in the dump, sorted."""
    found: set[str] = set()
    for func in _walk(ir["root"]):
        for constant in func["constants"]:
            if constant["kind"] == "string" and constant["value"] is not None:
                found.add(constant["value"])
    return sorted(found)


def summary(ir: dict) -> dict:
    """Function/instruction/constant counts plus the distinct string list."""
    funcs = list(_walk(ir["root"]))
    text = strings(ir)
    return {
        "function_count": len(funcs),
        "instruction_count": sum(len(f["code"]) for f in funcs),
        "constant_count": sum(len(f["constants"]) for f in funcs),
        "string_count": len(text),
        "strings": text,
    }


def _load(pak_rel: str, entry: str) -> dict:
    data, _meta = pakread.read_entry(pak_rel, entry)
    return parse(data)


def cmd_read(pak_rel: str, entry: str) -> int:
    try:
        ir = _load(pak_rel, entry)
    except (LuacError, ValueError, KeyError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"entry": entry, "prefix": ir["prefix"], **summary(ir)}, indent=1))
    return 0


def cmd_dis(pak_rel: str, entry: str) -> int:
    try:
        ir = _load(pak_rel, entry)
    except (LuacError, ValueError, KeyError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("\n".join(disassemble(ir["root"])))
    return 0


def cmd_strings(pak_rel: str, entry: str) -> int:
    try:
        ir = _load(pak_rel, entry)
    except (LuacError, ValueError, KeyError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for value in strings(ir):
        print(value)
    return 0


def selftest() -> int:
    checks: list[tuple[str, bool]] = []
    checks.append(("synthetic dump parses",
                   parse(_synthetic_dump())["root"]["source"] == "@selftest.lua"))
    checks.append(("disassembly names the opcode",
                   "MOVE" in disassemble(parse(_synthetic_dump())["root"])[1]))
    pak_rel, entry = SELFTEST_ENTRY
    try:
        ir = _load(pak_rel, entry)
    except FileNotFoundError:
        print(f"selftest: SKIP real read - install/PAK not present: {pak_rel}")
    except Exception as exc:  # noqa: BLE001
        print(f"  real read failed: {exc}")
        checks.append((f"real read {pak_rel}::{entry}", False))
    else:
        text = strings(ir)
        checks.append((f"real read {pak_rel}::{entry} parses "
                       f"({len(text)} strings)", bool(ir["root"]["code"])))
    ok = all(value for _, value in checks)
    for name, value in checks:
        print(f"{'PASS' if value else 'FAIL'} {name}")
    print(f"selftest: {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


def _synthetic_dump() -> bytes:
    """A minimal in-code Lua 5.1 dump: one function, one MOVE, one string."""
    def string(value: str | None) -> bytes:
        raw = b"" if value is None else value.encode("utf-8") + b"\x00"
        return len(raw).to_bytes(8, "little") + raw

    code = struct.pack("<I", 0)  # MOVE opcode 0
    body = string("@selftest.lua") + struct.pack("<ii", 1, 2) + bytes([0, 0, 0, 2])
    body += struct.pack("<I", 1) + code
    body += struct.pack("<I", 1) + b"\x04" + string("hi")
    body += struct.pack("<I", 0)  # protos
    body += struct.pack("<I", 0) * 3  # debug: lineinfo, locvars, upvalue names
    header = SIGNATURE + bytes([VERSION, FORMAT, ENDIANNESS, *SIZES, INTEGRAL])
    return PREFIX + header + body


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "selftest":
        return selftest()
    if cmd == "read" and len(argv) >= 3:
        return cmd_read(argv[1], argv[2])
    if cmd == "dis" and len(argv) >= 3:
        return cmd_dis(argv[1], argv[2])
    if cmd == "strings" and len(argv) >= 3:
        return cmd_strings(argv[1], argv[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
