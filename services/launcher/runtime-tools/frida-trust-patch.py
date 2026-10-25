#!/usr/bin/env python3
"""DTLS verify-bypass: patch the game's cert pinning in memory (Frida).

The client's DTLS layer enforces OpenSSL validation against an EMBEDDED
self-signed `CN=New World` cert, so no CA we control can ever validate the
REP handshake. The verify path is selected by one conditional jump; forcing
it unconditionally selects the permissive callback (always-trust).

Site (VERIFIED byte-identical on build 1.400.6031.6004151 — see
research/docs/REP-PROTOCOL.md and `bytepat.py dtls-verify`):

    1.400  0x145dce8ad: 48 83 BF 88 02 00 00 00   CMP qword ptr [RDI+0x288], 0
    1.400  0x145dce8b5: 0F 84 19 01 00 00         JZ  0x145dce9d4   <- patch here
    1.460  0x145dcf9ed: 48 83 BF 88 02 00 00 00   CMP (same bytes)
    1.460  0x145dcf9f5: 0F 84 19 01 00 00         JZ  (same bytes, moved +0x1140)
    patched:           E9 1A 01 00 00 90         JMP (identical on both builds)

The instruction did not change between builds; only its address moved. The 1.460
site was re-derived with `python reverse/tools/bytepat.py dtls-verify`, which
keys on the stable CMP that precedes the JZ, and then read back.

If the private exe already carries the patch ON DISK
(`scripts/patch-dtls-disk.py apply`), this script exits without attaching: there
is nothing left to do in memory, and the probe-free path is the one that reaches
InGame. Re-derive with `python reverse/tools/bytepat.py dtls-verify` before
trusting the VA on a newer client.

Usage:
  python services/launcher/runtime-tools/frida-trust-patch.py          # attach
  python services/launcher/runtime-tools/frida-trust-patch.py --spawn  # spawn private exe
  python services/launcher/runtime-tools/frida-trust-patch.py --revert # restore bytes
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import time
from pathlib import Path

IMAGE_BASE = 0x140000000
PATCH_VA = 0x145DCF9F5  # build 1.460 JZ (1.400 was 0x145DCE8B5)
ORIGINAL = bytes.fromhex("0F8419010000")  # JZ rel32 -> permissive branch
# NOTE: the externally archived patch bytes (E9 19 01 00 00 90) are off by
# one: a 5-byte JMP at the 6-byte JZ slot has its next-instruction at
# site+5, so rel32 must be 0x11A, not the JZ's 0x119. We NEVER trust
# archived displacements — rel32_jmp() recomputes from the verified target.

FRIDA_JS = """
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send(''); } else {
  const base = mod.base;
  const patchVa = base.add(%OFFSET%);
  console.log('[azoth] NewWorld.exe base =', base);
  console.log('[azoth] patch site =', patchVa);
  console.log('[azoth] before:', hexdump(patchVa, {length: 6, header: false}));
  if (%REVERT%) {
    Memory.patchCode(patchVa, 6, function (code) {
      const bytes = new Uint8Array(%ORIGINAL%);
      for (let i = 0; i < 6; i++) code.add(i).writeU8(bytes[i]);
    });
    console.log('[azoth] ORIGINAL bytes restored');
  } else {
    Memory.patchCode(patchVa, 6, function (code) {
      const bytes = new Uint8Array(%PATCHED%);
      for (let i = 0; i < 6; i++) code.add(i).writeU8(bytes[i]);
    });
    console.log('[azoth] DTLS verify bypass ACTIVE');
  }
  console.log('[azoth] after:', hexdump(patchVa, {length: 6, header: false}));
  send(base.toString(16));
}
"""


def rel32_jmp(site_va: int, target_va: int) -> bytes:
    """E9 rel32 from site_va (5 bytes) + NOP pad to the 6-byte JZ slot."""
    rel = target_va - (site_va + 5)
    return b"\xe9" + struct.pack("<i", rel) + b"\x90"


def find_private_exe() -> Path:
    """Our private runtime exe (no EAC), never the Steam install."""
    repo = Path(__file__).resolve().parents[3]
    exe = repo / "private-client" / "runtime" / "Bin64" / "NewWorld.exe"
    if exe.is_file():
        return exe
    raise SystemExit(
        "private runtime exe not found — run services/launcher/src/Start-NwPrivate.ps1 first"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spawn", action="store_true", help="spawn the private exe under Frida")
    ap.add_argument("--revert", action="store_true", help="restore original JZ bytes")
    args = ap.parse_args()

    target_va = PATCH_VA + 6 + struct.unpack("<i", ORIGINAL[2:6])[0]
    patched = rel32_jmp(PATCH_VA, target_va)

    # If the on-disk copy already carries the patch there is nothing left to do in
    # memory, and attaching only adds a failure mode. The probe-free path is the
    # one that reaches InGame.
    if not args.revert:
        try:
            exe = find_private_exe()
            sys.path.insert(0, str(exe.parents[3] / "reverse" / "tools" / "corpus"))
            from catalog import PE  # noqa: E402

            pe = PE(exe)
            off = pe.va_to_foff(PATCH_VA)
            with exe.open("rb") as f:
                f.seek(off)
                if f.read(len(patched)) == patched:
                    print(f"disk copy already patched at {PATCH_VA:#x}; no memory patch needed")
                    return 0
        except Exception as exc:  # noqa: BLE001 - never block the run on this check
            print(f"disk-patch check skipped: {exc}")

    import frida
    js = (
        FRIDA_JS.replace("%OFFSET%", str(PATCH_VA - IMAGE_BASE))
        .replace("%ORIGINAL%", "[" + ", ".join(map(str, ORIGINAL)) + "]")
        .replace("%PATCHED%", "[" + ", ".join(map(str, patched)) + "]")
        .replace("%REVERT%", "true" if args.revert else "false")
    )

    if args.spawn:
        exe = find_private_exe()
        print(f"[azoth] spawning {exe}")
        pid = frida.spawn([str(exe)])
    else:
        device = frida.get_local_device()
        matches = [p for p in device.enumerate_processes() if p.name.lower() == "newworld.exe"]
        if not matches:
            raise SystemExit("NewWorld.exe not running (or use --spawn)")
        pid = matches[0].pid
    print(f"[azoth] attaching to pid {pid}")
    session = frida.attach(pid)

    base: int | None = None

    def make() -> "frida.core.Script":
        s = session.create_script(js)
        s.on(
            "message",
            lambda msg, _data: (
                base_result.append(msg.get("payload") or "")
                if msg.get("type") == "send"
                else print(f"[frida:{msg.get('type')}] {msg.get('description') or msg}"),
            ),
        )
        return s

    base_result: list[str] = []
    script = make()
    script.load()
    # Post-spawn the exe may still be mapping: retry until the module exists.
    for _ in range(30):
        if base_result:
            base = int(base_result[0], 16)
            break
        time.sleep(1)
        script.unload()
        script = make()
        script.load()
    if base is None:
        raise SystemExit("NewWorld.exe module never appeared (game still loading?)")

    print(f"[azoth] done. image base {hex(base)}")

    if args.spawn:
        frida.resume(pid)
        print("[azoth] resumed under Frida — Ctrl+C exits (patch stays while alive)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("[azoth] exiting (game keeps running; patch persists per-session)")
    else:
        session.detach()
        print("[azoth] detached; patch stays until the process exits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
