#!/usr/bin/env python3
"""Patch the ClientSDK anticheat gate (Frida, OUR runtime).

The client disconnects with `Errors::connection_server_requires_anticheat`
immediately after the V3 handshake. Interceptor.attach/replace on these
sites did NOT fire (2026-09-18 live: error still 6ms after socket up
with the hooks loaded). Byte-patch like frida-trust-patch.py: the
patched opcodes persist after detach.

Ten sites. Each is listed with the ORIGINAL bytes that must be there before the
write; a site whose bytes do not match is reported as `mismatch` and the tool
exits non-zero instead of claiming success (it used to print "applied" with all
ten sites mismatched).

  1-2. ClientSDK vtable anticheat getters (build 1.400 → 1.460, both moved
       +0x1130):
       FUN_145A8DDD0 → FUN_145A8EF00  entry `40 53 48`
           OmniSDK session status, then [obj+0x25c]; returns 1 when the SDK is
           up AND [obj+0x25c]==0. Patched to `mov al,1; ret`.
           Corpus 145a8ef00-145a8ef2a confirms both reads.
       FUN_145A8DE00 → FUN_145A8EF30  entry `48 8B 89` (mov rcx,[rcx+0x228])
           thunk: if [obj+0x228] jmp [[obj+0x228]]+0x90, else al=1.
           Patched to `mov al,1; ret`. The 1.460 bytes are the documented 1.400
           shape verbatim (offset 0x90 decoded from the bytes).
  3.  OmniSDK session status, build 1.400 FUN_1479B61E0 → FUN_1479B7820,
      entry `48 89 5C 24 08`. Returns 100 ("SDK not initialized." /
      session.cpp) when the SDK is down, else a session state. Patched to
      `xor eax,eax; ret` = "fine". Corpus 1479b7820-1479b79d7.
      Confirmed by the preserved caller: the 1.460 getter above calls
      0x1479B7820, exactly as the 1.400 getter called the session status.
  4-9. FUN_146193620 → FUN_1461948e0: six `sete [rbp+0x6f]` after
      `cmp ecx, 0x102`. Each stores 1 whenever the JSON value is a bool
      (type 0x102), including JSON `false`. Force every stored byte to 0.
      The 1.460 function is the one that reads the `enable-anticheat` key
      (strings at 0x1484CC640 / 0x1484CC658), and the six sites keep their
      1.400 relative spacing exactly (0xE1, 0x1C4, 0x1BD, 0x4DA, 0xDD).
  10. FUN_1444F5700 → FUN_1444F6840: official skip is `this[0x130]=1; ret` when
      the global+0x244/245/246 flags are set. That path means "EOS is not
      running". Combined with enable-anticheat stored 0, ClientSDK
      must not demand an anticheat session. Without the S3/store fix
      this is the SAME encoding as the resolve-fail path and still
      raises @mm_csdkerr_server_requires_anticheat.
      Corpus 1444f6840-1444f6972 shows the three global flag reads and the
      `this[0x130] = 1; return` in the same order as 1.400.

All sites were re-derived on 2026-10-22 for build 30fe6461 with the named
anchors in `reverse/tools/bytepat.py` (anticheat-impl, anticheat-thunk,
omnisdk-session-status, anticheat-json-bool, eos-skip-entry) and confirmed in
the corpus, never from the old addresses: `0x145A8DDD0`, `0x1479B61E0`,
`0x1461936E3` and `0x1444F5700` all land inside different instructions in 1.460.

Usage:
  python services/launcher/runtime-tools/frida-anticheat-patch.py          # attach, patch, detach
  python services/launcher/runtime-tools/frida-anticheat-patch.py --check  # static, no game
  python services/launcher/runtime-tools/frida-anticheat-patch.py --stay   # keep the session open
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_sites  # noqa: E402
from build_sites import BUILD_1_400, BUILD_1_460, Site  # noqa: E402

TAG = "anticheat"

SDK_BYTES = bytes.fromhex("B0 01 C3")  # mov al,1; ret
SESSION_BYTES = bytes.fromhex("31 C0 C3")  # xor eax,eax; ret
JSON_TRUE = bytes.fromhex("0F 94 45 6F")  # sete byte ptr [rbp+0x6f]
JSON_ZERO = bytes.fromhex("C6 45 6F 00")  # mov byte ptr [rbp+0x6f], 0
EOS_SKIP = bytes.fromhex("C6 81 30 01 00 00 01 B0 01 C3")  # this[0x130]=1; mov al,1; ret

_1_400 = (
    Site(0x145A8DDD0, bytes.fromhex("40 53 48"), SDK_BYTES, "ClientSDK anticheat getter impl"),
    Site(0x145A8DE00, bytes.fromhex("48 8B 89"), SDK_BYTES, "ClientSDK anticheat getter thunk"),
    Site(0x1479B61E0, bytes.fromhex("48 89 5C"), SESSION_BYTES, "OmniSDK session status"),
    Site(0x1461936E3, JSON_TRUE, JSON_ZERO, "enable-anticheat JSON bool 1"),
    Site(0x1461937C4, JSON_TRUE, JSON_ZERO, "enable-anticheat JSON bool 2"),
    Site(0x146193988, JSON_TRUE, JSON_ZERO, "enable-anticheat JSON bool 3"),
    Site(0x146193B45, JSON_TRUE, JSON_ZERO, "enable-anticheat JSON bool 4"),
    Site(0x14619401F, JSON_TRUE, JSON_ZERO, "enable-anticheat JSON bool 5"),
    Site(0x1461940FC, JSON_TRUE, JSON_ZERO, "enable-anticheat JSON bool 6"),
    # 1.400 documented only the 5-byte prologue; the patch itself is 10 bytes.
    Site(0x1444F5700, bytes.fromhex("48 89 5C 24 08"), EOS_SKIP, "EOS skip (ClientSDK init)"),
)

_1_460 = (
    Site(0x145A8EF00, bytes.fromhex("40 53 48"), SDK_BYTES, "ClientSDK anticheat getter impl"),
    Site(0x145A8EF30, bytes.fromhex("48 8B 89"), SDK_BYTES, "ClientSDK anticheat getter thunk"),
    Site(0x1479B7820, bytes.fromhex("48 89 5C"), SESSION_BYTES, "OmniSDK session status"),
    Site(0x1461949A3, JSON_TRUE, JSON_ZERO, "enable-anticheat JSON bool 1"),
    Site(0x146194A84, JSON_TRUE, JSON_ZERO, "enable-anticheat JSON bool 2"),
    Site(0x146194C48, JSON_TRUE, JSON_ZERO, "enable-anticheat JSON bool 3"),
    Site(0x146194E05, JSON_TRUE, JSON_ZERO, "enable-anticheat JSON bool 4"),
    Site(0x1461952DF, JSON_TRUE, JSON_ZERO, "enable-anticheat JSON bool 5"),
    Site(0x1461953BC, JSON_TRUE, JSON_ZERO, "enable-anticheat JSON bool 6"),
    # The 10 bytes this patch overwrites are the prologue and are identical to
    # 1.400's, so the check covers the whole write, not just its first 5 bytes.
    Site(
        0x1444F6840,
        bytes.fromhex("48 89 5C 24 08 57 48 83 EC 20"),
        EOS_SKIP,
        "EOS skip (ClientSDK init)",
    ),
)

SITES: dict[str, tuple[Site, ...]] = {BUILD_1_400: _1_400, BUILD_1_460: _1_460}

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ok: false, err: 'no-module'}); } else {
  const base = mod.base;
  const patches = %PATCHES%;
  const report = [];
  let bad = 0;
  for (const p of patches) {
    const addr = base.add(p.off);
    const n = p.want.length;
    const m = Math.max(n, p.orig.length);
    const before = new Uint8Array(addr.readByteArray(m));
    let orig = true;
    for (let i = 0; i < p.orig.length; i++) if (before[i] !== p.orig[i]) orig = false;
    let already = true;
    for (let i = 0; i < n; i++) if (before[i] !== p.want[i]) already = false;
    if (already) {
      report.push({va: p.va, state: 'already', label: p.label});
      continue;
    }
    if (!orig) {
      bad += 1;
      report.push({va: p.va, state: 'mismatch', label: p.label,
                   want: p.orig, before: Array.from(before).slice(0, p.orig.length)});
      continue;
    }
    try {
      Memory.patchCode(addr, n, function (code) {
        for (let i = 0; i < n; i++) code.add(i).writeU8(p.want[i]);
      });
      report.push({va: p.va, state: 'patched', label: p.label});
    } catch (e) {
      bad += 1;
      report.push({va: p.va, state: 'error', label: p.label, err: String(e)});
    }
  }
  send({ok: bad === 0, base: base.toString(16), bad: bad, report: report});
}
"""


def js_literal(sites: tuple[Site, ...]) -> str:
    items = []
    for site in sites:
        if len(site.orig) > len(site.want):
            raise SystemExit(f"site {site.va:#x}: orig longer than want, check would read past")
        items.append(
            "{va:%d,off:%d,orig:[%s],want:[%s],label:%s}"
            % (
                site.va,
                site.va - build_sites.IMAGE_BASE,
                ",".join(str(b) for b in site.orig),
                ",".join(str(b) for b in site.want),
                '"' + site.label.replace('"', "'") + '"',
            )
        )
    return "[" + ",".join(items) + "]"


def report(result: dict, sites: tuple[Site, ...]) -> bool:
    """Print the per-site outcome; True only when nothing is wrong."""
    by_va = {site.va: site for site in sites}
    entries = result.get("report") or []
    ok = bool(entries) and len(entries) == len(sites) and not result.get("bad")
    for entry in entries:
        va = int(entry.get("va") or 0)
        site = by_va.get(va)
        label = entry.get("label") or (site.label if site else "?")
        state = entry.get("state")
        want = site.orig.hex() if site else "?"
        if state == "mismatch":
            before = bytes(entry.get("before") or b"").hex()
            print(f"[{TAG}] MISMATCH {va:#x} ({label}) current={before} expected={want}")
        elif state == "error":
            print(f"[{TAG}] ERROR {va:#x} ({label}) {entry.get('err')}")
        else:
            print(f"[{TAG}] {state:8} {va:#x} ({label}) expected={want}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stay", action="store_true", help="keep attached (not required for byte patches)")
    ap.add_argument("--check", action="store_true", help="static site report from disk; never attaches")
    args = ap.parse_args()

    if args.check:
        return build_sites.report_check(SITES, TAG)

    build, _exe, note = build_sites.identify(SITES)
    sites = SITES[build]
    print(f"[{TAG}] build sha256={build}")
    print(f"[{TAG}] {note}")

    import frida  # slow import; keep --check usable without a Frida session

    js = JS.replace("%PATCHES%", js_literal(sites))
    try:
        session = frida.attach("NewWorld.exe")
    except frida.ProcessNotFoundError:
        print("NewWorld.exe not running")
        return 1

    result: list[dict] = []

    def on_msg(msg, _data):
        if msg.get("type") == "send":
            result.append(msg.get("payload") or {})
        else:
            print(f"[frida:{msg.get('type')}] {msg.get('description') or msg}")

    script = session.create_script(js)
    script.on("message", on_msg)
    script.load()
    for _ in range(10):
        if result:
            break
        time.sleep(0.2)
    if not result or not result[0].get("base"):
        print(f"[{TAG}] FAILED: {result}")
        session.detach()
        return 1
    ok = report(result[0], sites)
    if not ok:
        print(f"[{TAG}] FAILED: {result[0].get('bad')} of {len(sites)} site(s) not applied")
        session.detach()
        return 1
    print(f"[{TAG}] all {len(sites)} site(s) applied")
    if args.stay:
        print("[azoth] staying attached (Ctrl+C)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    session.detach()
    print("[azoth] detached; patches persist until the process exits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
