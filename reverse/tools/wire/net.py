#!/usr/bin/env python3
"""Network: live netstat+DNS, and pcapng analysis (TLS SNI, DTLS, UDP flows).

Does not open the game process. pktmon is started from Start-NwCapture.ps1 (admin).
"""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import (  # noqa: E402
    PROCESS_NAMES,
    decode_l3,
    default_paths,
    ensure_dir,
    role_for_host,
    utc_now,
    write_json,
)

NETSTAT_RE = __import__("re").compile(
    r"^\s*(TCP|UDP)\s+(\S+)\s+(\S+)(?:\s+(\S+))?\s+(\d+)\s*$",
    __import__("re").I,
)


def list_game_pids() -> dict[int, str]:
    import ctypes

    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    k = ctypes.windll.kernel32
    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return {}
    out = {}
    try:
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not k.Process32FirstW(snap, ctypes.byref(pe)):
            return {}
        while True:
            name = pe.szExeFile
            role = PROCESS_NAMES.get(name.lower())
            if role:
                out[int(pe.th32ProcessID)] = role
            if not k.Process32NextW(snap, ctypes.byref(pe)):
                break
        return out
    finally:
        k.CloseHandle(snap)


def netstat_rows(pids: set[int]) -> list[dict]:
    if not pids:
        return []
    try:
        raw = subprocess.check_output(
            ["netstat", "-ano"], creationflags=0x08000000
        ).decode("utf-8", errors="replace")
    except Exception:
        return []
    rows = []
    for line in raw.splitlines():
        m = NETSTAT_RE.match(line)
        if not m:
            continue
        proto, local, remote, state, pid_s = m.groups()
        try:
            pid = int(pid_s)
        except ValueError:
            continue
        if pid not in pids:
            continue
        rows.append(
            {
                "proto": proto.upper(),
                "local": local,
                "remote": remote,
                "state": state or "",
                "pid": pid,
            }
        )
    return rows


def dns_interesting() -> list[dict]:
    try:
        raw = (
            subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-DnsClientCache | Select-Object Name,Data,Type | ConvertTo-Json -Compress",
                ],
                creationflags=0x08000000,
                timeout=15,
            )
            .decode("utf-8", errors="replace")
            .strip()
        )
    except Exception:
        return []
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    from common import INTERESTING_HOST_RE

    out = []
    for row in data:
        name = str(row.get("Name") or "")
        if INTERESTING_HOST_RE.search(name):
            out.append(
                {
                    "name": name,
                    "data": str(row.get("Data") or ""),
                    "type": str(row.get("Type") or ""),
                    "role": role_for_host(name),
                }
            )
    return out


def watch(out: Path, seconds: int) -> None:
    ensure_dir(out)
    print(f"Watching netstat+DNS for {seconds}s -> {out}")
    print("Launch the game in another window. Ctrl+C to stop early.")
    seen = set()
    end = time.time() + seconds
    conn_path = out / "connections.jsonl"
    dns_path = out / "dns.jsonl"
    try:
        while time.time() < end:
            pids = list_game_pids()
            if pids:
                print(f"  pids {pids}")
            for r in netstat_rows(set(pids)):
                key = f"{r['pid']}|{r['proto']}|{r['local']}|{r['remote']}"
                if key not in seen:
                    seen.add(key)
                    rec = {**r, "ts": utc_now(), "role": pids.get(r["pid"])}
                    with conn_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(rec) + "\n")
                    print(f"  NET {r['proto']} {r['local']} -> {r['remote']}")
            entries = dns_interesting()
            if entries:
                with dns_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": utc_now(), "entries": entries}) + "\n")
            time.sleep(2)
    except KeyboardInterrupt:
        print("stop")
    print("OK network watch")


# ----- pcapng -----


def _iter_pcapng_packets(data: bytes):
    off = 0
    total = len(data)
    while off + 8 <= total:
        btype, blen = struct.unpack_from("<II", data, off)
        if blen < 12 or off + blen > total:
            break
        if btype == 0x00000006 and blen >= 32:
            caplen = struct.unpack_from("<I", data, off + 20)[0]
            pkt = data[off + 28 : off + 28 + caplen]
            yield pkt
        off += blen
        if blen == 0:
            break


def _l3(pkt: bytes):
    return decode_l3(pkt)


def extract_sni(payload: bytes) -> str | None:
    """ClientHello TLS en un solo segmento (el caso comun)."""
    if len(payload) < 40:
        return None
    # record: type=0x16 handshake, version 03 01 / 03 03
    rec = payload
    if rec[0] != 0x16 or rec[1] != 0x03:
        # a veces hay header TCP options already stripped; search
        idx = rec.find(b"\x16\x03")
        if idx < 0 or idx + 40 > len(rec):
            return None
        rec = rec[idx:]
    if len(rec) < 9 or rec[5] != 0x01:  # handshake ClientHello
        # handshake type is after 5-byte record header
        pass
    # Hunt the SNI extension. Its layout is
    #   [00 00][ext_len][list_len][name_type][name_len][hostname]
    # so the lengths start after the extension header, not inside it: reading
    # name_len two bytes early yields a value in the tens of thousands and the
    # guard below then rejects every real ClientHello.
    i = 0
    while i + 9 < len(rec):
        if rec[i : i + 2] == b"\x00\x00" and rec[i + 6] == 0x00:
            ext_len = struct.unpack_from("!H", rec, i + 2)[0]
            list_len = struct.unpack_from("!H", rec, i + 4)[0]
            name_len = struct.unpack_from("!H", rec, i + 7)[0]
            # ext_len counts the list length field plus the list itself.
            if (
                ext_len == list_len + 2
                and 3 < name_len < 253
                and list_len >= name_len + 3
                and i + 9 + name_len <= len(rec)
            ):
                host = rec[i + 9 : i + 9 + name_len]
                try:
                    s = host.decode("ascii")
                except UnicodeDecodeError:
                    i += 1
                    continue
                if "." in s and all(32 < c < 127 for c in host):
                    return s
        i += 1
    return None


def is_dtls_hello(payload: bytes) -> bool:
    # DTLS 1.0 FE FF, 1.2 FE FD, record type 16 handshake
    if len(payload) < 13:
        return False
    return payload[0] == 0x16 and payload[1] == 0xFE and payload[2] in (0xFF, 0xFD)


def analyze_pcap(pcap: Path, out: Path) -> dict:
    data = pcap.read_bytes()
    flows = defaultdict(
        lambda: {"pkts": 0, "bytes": 0, "sni": set(), "dtls": 0, "proto": ""}
    )
    sni_hits: Counter[str] = Counter()
    udp_dtls = Counter()
    n = 0
    for pkt in _iter_pcapng_packets(data):
        parsed = _l3(pkt)
        if not parsed:
            continue
        proto, src, dst, l4 = parsed
        n += 1
        if proto == 6 and len(l4) >= 20:  # TCP
            sp, dp = struct.unpack_from("!HH", l4, 0)
            hdr_len = ((l4[12] >> 4) * 4) if len(l4) > 12 else 20
            payload = l4[hdr_len:]
            key = tuple(sorted([(src, sp), (dst, dp)])) + ("TCP",)
            rec = flows[key]
            rec["pkts"] += 1
            rec["bytes"] += len(pkt)
            rec["proto"] = "TCP"
            rec["a"] = f"{src}:{sp}"
            rec["b"] = f"{dst}:{dp}"
            sni = extract_sni(payload)
            if sni:
                rec["sni"].add(sni)
                sni_hits[sni] += 1
        elif proto == 17 and len(l4) >= 8:
            sp, dp = struct.unpack_from("!HH", l4, 0)
            payload = l4[8:]
            key = tuple(sorted([(src, sp), (dst, dp)])) + ("UDP",)
            rec = flows[key]
            rec["pkts"] += 1
            rec["bytes"] += len(pkt)
            rec["proto"] = "UDP"
            rec["a"] = f"{src}:{sp}"
            rec["b"] = f"{dst}:{dp}"
            if is_dtls_hello(payload) or (
                payload[:1] == b"\x16" and len(payload) > 13 and payload[1] == 0xFE
            ):
                rec["dtls"] += 1
                udp_dtls[f"{src}:{sp}->{dst}:{dp}"] += 1
            rec["dtls_records"] = rec.get("dtls_records", 0) + int(
                len(payload) > 13
                and payload[0] in (0x14, 0x15, 0x16, 0x17)
                and payload[1] == 0xFE
            )

    flow_list = []
    for _k, v in flows.items():
        item = {
            "proto": v["proto"],
            "a": v.get("a"),
            "b": v.get("b"),
            "pkts": v["pkts"],
            "bytes": v["bytes"],
            "sni": sorted(v["sni"]),
            "roles": [role_for_host(s) for s in v["sni"]],
            "dtls_hellos": v.get("dtls", 0),
            "dtls_records": v.get("dtls_records", 0),
        }
        flow_list.append(item)
    flow_list.sort(key=lambda x: -x["pkts"])

    # REP candidates: UDP with DTLS, not port 53, not 443
    reps = [
        f
        for f in flow_list
        if f["proto"] == "UDP"
        and (f["dtls_hellos"] or f["dtls_records"])
        and f["pkts"] >= 3
    ]

    result = {
        "pcap": str(pcap),
        "packets": n,
        "sni": [
            {"host": h, "hellos": c, "role": role_for_host(h)}
            for h, c in sni_hits.most_common()
        ],
        "rep_candidates": reps[:20],
        "top_flows": flow_list[:40],
        "udp_dtls_sample": udp_dtls.most_common(15),
    }
    write_json(out, result)
    return result


def cmd_analyze(pcap: Path, out: Path | None) -> None:
    dest = out or pcap.with_suffix(".analysis.json")
    r = analyze_pcap(pcap, dest)
    print(f"packets {r['packets']}")
    print("SNI (HTTPS hosts the client named in the TLS handshake):")
    for row in r["sni"][:25]:
        print(f"  {row['role']:22} {row['host']}  hellos={row['hellos']}")
    print("REP candidates (UDP+DTLS):")
    for f in r["rep_candidates"][:10]:
        print(f"  {f['a']}  <->  {f['b']}  pkts={f['pkts']} bytes={f['bytes']}")
    print(f"wrote {dest}")


def main() -> int:
    ap = argparse.ArgumentParser(description="New World network (passive)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("watch", help="netstat+DNS while you play (no pktmon)")
    w.add_argument("--out")
    w.add_argument("--seconds", type=int, default=3600)
    a = sub.add_parser("analyze", help="analyze a pktmon pcapng")
    a.add_argument("pcap")
    a.add_argument("--out")
    args = ap.parse_args()
    p = default_paths()
    if args.cmd == "watch":
        out = Path(args.out) if args.out else p["research"] / "sessions" / "net_watch"
        watch(out, args.seconds)
    else:
        cmd_analyze(Path(args.pcap), Path(args.out) if args.out else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
