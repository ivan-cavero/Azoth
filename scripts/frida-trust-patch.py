#!/usr/bin/env python3
"""DTLS verify-bypass: patch the game's cert pinning in memory (Frida).

The client's DTLS layer enforces OpenSSL validation against an EMBEDDED
self-signed `CN=New World` cert, so no CA we control can ever validate the
REP handshake. The verify path is selected by one conditional jump; forcing
it unconditionally selects the permissive callback (always-trust).

Site (VERIFIED byte-identical on build 1.400.6031.6004151 — see
research/docs/REP-PROTOCOL.md and `bytepat.py dtls-verify`):

    0x145dce8ad: 48 83 BF 88 02 00 00 00   CMP qword ptr [RDI+0x288], 0
    0x145dce8b5: 0F 84 19 01 00 00         JZ  0x145dce9d4   <- patch here
    patched:     E9 19 01 00 00 90         JMP 0x145dce9d4 (same target)

Re-derive with `python research/tools/reversing/bytepat.py dtls-verify`
before trusting the VA on a newer client. This patch is IN-MEMORY ONLY (no
on-disk modification), against OUR private runtime (no EAC — see
research/docs/EAC.md for why this is forbidden on the official process).

Usage:
  python scripts/frida-trust-patch.py            # attach to running NewWorld.exe
  python scripts/frida-trust-patch.py --spawn    # spawn the private exe under Frida
  python scripts/frida-trust-patch.py --revert   # restore original bytes
"""

from __future__ import annotations

import argparse
import ctypes
import struct
import sys
from pathlib import Path

IMAGE_BASE = 0x140000000
PATCH_VA = 0x145DCE8B5  # the JZ itself (CMP starts at ...8AD)
ORIGINAL = bytes.fromhex("0F8419010000")  # JZ rel32 -> 0x145dce9d4
# NOTE: the externally archived patch bytes (E9 19 01 00 00 90) are off by
# one: a 5-byte JMP at the 6-byte JZ slot has its next-instruction at
# site+5, so rel32 must be 0x11A, not the JZ's 0x119. We NEVER trust
# archived displacements — rel32_jmp() recomputes from the verified target.

FRIDA_JS = """
const base = Module.getBaseAddress('NewWorld.exe');
const patchVa = base.add(OFFSET_FROM_IMAGE_BASE);
const size = 6;
console.log('[azoth] NewWorld.exe base =', base);
console.log('[azoth] patch site =', patchVa);

const before = Memory.readByteArray(patchVa, size);
console.log('[azoth] before:', Array.from(new Uint8Array(before))
    .map(b => b.toString(16).padStart(2, '0')).join(' '));

Memory.patchCode(patchVa, size, function (code) {
    const bytes = new Uint8Array(PATCH_BYTES);
    for (let i = 0; i < size; i++) code.add(i).writeU8(bytes[i]);
});

const after = Memory.readByteArray(patchVa, size);
console.log('[azoth] after:', Array.from(new Uint8Array(after))
    .map(b => b.toString(16).padStart(2, '0')).join(' '));
console.log('[azoth] DTLS verify bypass ACTIVE');
"""


def image_base_of_pid(pid: int) -> int:
    """Module base of NewWorld.exe for an already-running process."""
    import frida

    session = frida.attach(pid)
    script = session.create_script(
        "send(Module.getBaseAddress('NewWorld.exe').toString(16));"
    )
    result: list[str] = []
    script.on("message", lambda msg, _data: result.append(msg["payload"]))
    script.load()
    session.detach()
    if not result:
        raise SystemExit("could not read module base — is this NewWorld.exe?")
    return int(result[0], 16)


def find_game_pid() -> int:
    import frida

    for proc in frida.enumerate_processes():
        if proc.name.lower() == "newworld.exe":
            return proc.pid
    raise SystemExit("NewWorld.exe not running (or use --spawn)")


def find_private_exe() -> Path:
    """Our private runtime exe (no EAC), never the Steam install."""
    local = Path(__file__).resolve().parents[1]
    for base in (
        Path(__import__("os").environ["LOCALAPPDATA"]) / "Azoth" / "game" / "Bin64",
        local / "private-client" / "Bin64",
    ):
        exe = base / "NewWorld.exe"
        if exe.exists():
            return exe
    raise SystemExit(
        "private runtime exe not found — run services/launcher/src/Start-NwPrivate.ps1 first"
    )


def rel32_jmp(site_va: int, target_va: int) -> bytes:
    """E9 rel32 from site_va (6-byte form: E9 + rel32 + NOP pad)."""
    rel = target_va - (site_va + 5)
    return b"\xe9" + struct.pack("<i", rel) + b"\x90"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spawn", action="store_true", help="spawn the private exe under Frida")
    ap.add_argument("--revert", action="store_true", help="restore original JZ bytes")
    args = ap.parse_args()

    import frida

    if args.spawn:
        exe = find_private_exe()
        print(f"[azoth] spawning {exe}")
        pid = frida.spawn([str(exe)])
        session = frida.attach(pid)
        frida.resume(pid)
    else:
        pid = find_game_pid()
        session = frida.attach(pid)
    print(f"[azoth] attached to pid {pid}")

    base = image_base_of_pid(pid)
    offset = PATCH_VA - IMAGE_BASE
    # Recompute the jump from OUR build's disassembly — never trust the
    # archived rel32 blindly (it was off by one; see NOTE above).
    target_va = PATCH_VA + 6 + struct.unpack("<i", ORIGINAL[2:6])[0]
    patch_bytes = ORIGINAL if args.revert else rel32_jmp(PATCH_VA, target_va)
    print(f"[azoth] base={hex(base)} site={hex(base + offset)} bytes={patch_bytes.hex()}")

    script = session.create_script(
        FRIDA_JS.replace("OFFSET_FROM_IMAGE_BASE", str(offset)).replace(
            "PATCH_BYTES",
            "[" + ", ".join(str(b) for b in patch_bytes) + "]",
        )
    )
    script.on("message", lambda msg, _data: print(f"[frida] {msg}"))
    script.load()
    if args.spawn:
        print("[azoth] spawned under Frida — Ctrl+C detaches (game keeps running)")
        try:
            while True:
                import time

                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        session.detach()  # patch persists for the process lifetime
        print("[azoth] detached; patch stays until the process exits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
