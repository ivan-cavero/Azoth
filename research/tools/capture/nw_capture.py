#!/usr/bin/env python3
"""New World private-server capture worker.

Passive only: Game.log, netstat, DNS cache, file copies, EXE strings on disk.
Never OpenProcess with VM_READ, never inject, never attach a debugger.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

STEAM_APP_ID = "1063730"
CHANNEL_CONFIG_URL = (
    f"https://d2c74t4zimux3r.cloudfront.net/STEAM_APP_ID.{STEAM_APP_ID}.json"
)

PROCESS_NAMES = {
    "newworldlauncher.exe": "launcher",
    "newworld.exe": "client",
    "gamecrashuploader.exe": "crash-uploader",
    "easyanticheat_eos.exe": "eac-eos",
    "easyanticheat.exe": "eac",
    "start_protected_game.exe": "eac-start",
    "steam.exe": "steam",
}

INTERESTING_HOST_RE = re.compile(
    r"(cloudfront\.net|amazonaws\.com|amazongames\.com|amazon\.com|"
    r"newworld\.com|vivox\.com|steamcommunity\.com|steampowered\.com|"
    r"epicgames\.com|easyanticheat\.net)",
    re.I,
)
URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%\-]+")
IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?\b")
TS_RE = re.compile(
    r"^<(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)>\s*(?P<rest>.*)$"
)
STATE_RE = re.compile(r"Update state (?P<fr>\S+) to new state (?P<to>\S+)", re.I)
S3_RE = re.compile(r'S3 key:\s*"([^"]+)"')
TICKET_RE = re.compile(r"(steam\|[0-9a-fA-F]{16,})")
AWS_KEY_RE = re.compile(r"\b(ASIA[A-Z0-9]{16}|AKIA[A-Z0-9]{16})\b")

KNOWN_HOSTS = [
    "d2c74t4zimux3r.cloudfront.net",
    "d1w0bfy6smo4d1.cloudfront.net",
    "d2oeuvxi3kfsrw.cloudfront.net",
    "d3bj4csovi1fe8.cloudfront.net",
    "d1cjlmzk0xrm0z.cloudfront.net",
    "de4mfzk9wkelz.cloudfront.net",
    "d1hkbwzm1bktgo.cloudfront.net",
    "tokenservice.amazongames.com",
    "prod.newworld.com",
    "client.content-service.amazongames.com",
    "client.entitlementservice.amazongames.com",
    "client.catalogservice.amazongames.com",
    "client.agsprivacysettingsservice.amazongames.com",
    "ags-javelin-remote-config.s3.amazonaws.com",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def local_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_json(path: Path, obj: Any) -> None:
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def append_jsonl(path: Path, obj: Any) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def redact(text: str) -> str:
    text = TICKET_RE.sub(lambda m: f"steam|<redacted len={len(m.group(1))}>", text)
    text = AWS_KEY_RE.sub("ASIA<redacted>", text)
    return text


def log_line(session: Path, msg: str) -> None:
    line = f"{utc_now()} {msg}"
    print(line, flush=True)
    log_path = session / "logs" / "capture-runner.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Process snapshot via Toolhelp (no VM_READ)
# ---------------------------------------------------------------------------

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


def list_processes() -> list[dict[str, Any]]:
    kernel32 = ctypes.windll.kernel32
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return []
    try:
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        out: list[dict[str, Any]] = []
        if not kernel32.Process32FirstW(snap, ctypes.byref(pe)):
            return []
        while True:
            name = pe.szExeFile
            key = name.lower()
            if key in PROCESS_NAMES:
                out.append(
                    {
                        "name": name,
                        "role": PROCESS_NAMES[key],
                        "pid": int(pe.th32ProcessID),
                        "ppid": int(pe.th32ParentProcessID),
                        "threads": int(pe.cntThreads),
                    }
                )
            if not kernel32.Process32NextW(snap, ctypes.byref(pe)):
                break
        return out
    finally:
        kernel32.CloseHandle(snap)


def query_image_path(pid: int) -> str | None:
    """PROCESS_QUERY_LIMITED_INFORMATION only. No VM_READ."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_ulong(32768)
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        return buf.value if ok else None
    finally:
        kernel32.CloseHandle(handle)


# ---------------------------------------------------------------------------
# netstat / DNS (external commands, not injected)
# ---------------------------------------------------------------------------

NETSTAT_RE = re.compile(r"^\s*(TCP|UDP)\s+(\S+)\s+(\S+)(?:\s+(\S+))?\s+(\d+)\s*$", re.I)


def parse_netstat(pids: set[int]) -> list[dict[str, str]]:
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
        if proto.upper() == "UDP":
            state = state or ""
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


def dns_cache_snapshot() -> list[dict[str, str]]:
    try:
        raw = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-DnsClientCache | "
                "Select-Object Name,Data,Type,TimeToLive | ConvertTo-Json -Compress",
            ],
            creationflags=0x08000000,
            timeout=15,
        ).decode("utf-8", errors="replace")
    except Exception:
        return []
    raw = raw.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    out = []
    for row in data:
        name = str(row.get("Name") or "")
        if INTERESTING_HOST_RE.search(name) or any(
            name.endswith(h) or h in name for h in KNOWN_HOSTS
        ):
            out.append(
                {
                    "name": name,
                    "data": str(row.get("Data") or ""),
                    "type": str(row.get("Type") or ""),
                    "ttl": str(row.get("TimeToLive") or ""),
                }
            )
    return out


# ---------------------------------------------------------------------------
# Game.log parser
# ---------------------------------------------------------------------------


def classify_log_line(rest: str) -> dict[str, Any] | None:
    red = redact(rest)
    info: dict[str, Any] = {"kind": "log", "text": red}

    m = STATE_RE.search(rest)
    if m:
        return {
            "kind": "state",
            "from": m.group("fr"),
            "to": m.group("to"),
            "text": red,
        }

    if "Log Started at" in rest:
        return {"kind": "log_start", "text": red}
    if "FileVersion:" in rest or "ProductVersion:" in rest:
        return {"kind": "version", "text": red}
    if "Channel service uri:" in rest:
        um = URL_RE.search(rest)
        return {"kind": "channel_uri", "url": um.group(0) if um else "", "text": red}
    if "Found cluster data for cluster id:" in rest:
        return {
            "kind": "cluster",
            "id": rest.split("cluster id:")[-1].strip(),
            "text": red,
        }
    if "Auth Stack:" in rest or "Gateway Host:" in rest or "Gateway Stack:" in rest:
        return {"kind": "cluster_endpoint", "text": red}
    if "[SteamAuth]" in rest or "Initializing Steam Auth" in rest:
        return {"kind": "steam_auth", "text": red}
    if "[OmniAuthBackend]" in rest or "OmniSDK" in rest:
        return {"kind": "omni", "text": red}
    if "credentials/omni" in rest.lower():
        return {"kind": "credentials", "text": red}
    if "OnCampfireLoginComplete" in rest:
        return {"kind": "campfire", "text": red}
    if "ConfigureLogin" in rest or "Gateway Mode:" in rest:
        return {"kind": "gateway", "text": red}
    if "playerName =" in rest:
        name = rest.split("playerName =", 1)[-1].strip()
        return {"kind": "player", "name": name, "text": red}
    if "Persona ID:" in rest:
        return {
            "kind": "persona",
            "id": rest.split("Persona ID:")[-1].strip(),
            "text": red,
        }
    if "Character ID:" in rest:
        return {
            "kind": "character",
            "id": rest.split("Character ID:")[-1].strip(),
            "text": red,
        }
    if "World ID:" in rest:
        return {
            "kind": "world_id",
            "id": rest.split("World ID:")[-1].strip(),
            "text": red,
        }
    if "World Name:" in rest:
        return {
            "kind": "world_name",
            "name": rest.split("World Name:")[-1].strip(),
            "text": red,
        }
    if "REP Address:" in rest or "RepAddress =" in rest:
        return {"kind": "rep", "text": red, "endpoint": _extract_endpoint(rest)}
    if "REP socket connection established" in rest:
        return {"kind": "rep_socket", "text": red}
    if "registration response from REP" in rest:
        return {"kind": "registration", "text": red}
    if "Server version:" in rest:
        return {"kind": "server_version", "text": red}
    if (
        "player spawn succeeds" in rest
        or "InGame" in rest
        and "new state InGame" in rest
    ):
        return {"kind": "ingame", "text": red}
    if "Loading level" in rest:
        return {"kind": "level", "text": red}
    if "Login ticket" in rest or "login ticket" in rest:
        return {"kind": "login_ticket", "text": red}
    if "Queuing login" in rest:
        return {"kind": "queue", "text": red}
    if "[CMS]" in rest:
        return {"kind": "cms", "urls": URL_RE.findall(rest), "text": red}
    if "remoteCfg" in rest or S3_RE.search(rest):
        key = S3_RE.search(rest)
        return {"kind": "s3", "key": key.group(1) if key else "", "text": red}
    if "RMIDispatch" in rest or '"messageType":' in rest:
        return {"kind": "rmi", "text": red}
    if "[ERROR]" in rest or "Failure in" in rest:
        return {"kind": "error", "text": red}
    if "[Vivox]" in rest:
        return {"kind": "vivox", "text": red}
    if URL_RE.search(rest) and INTERESTING_HOST_RE.search(rest):
        return {"kind": "http", "urls": URL_RE.findall(rest), "text": red}

    # Keep only high-signal leftover lines, not the CPU dump.
    flags = (
        "Javelin",
        "GameConnection",
        "AuthManager",
        "Campfire",
        "Omni",
        "SteamAuth",
        "ActorContainer",
        "ClientContext",
        "EasyAntiCheat",
    )
    if any(f in rest for f in flags):
        return info
    return None


def _extract_endpoint(text: str) -> str:
    m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3}:\d{1,5})", text)
    if m:
        return m.group(1)
    m = re.search(r"RepAddress\s*=\s*(\S+)", text)
    return m.group(1) if m else ""


HIGHLIGHT_KINDS = {
    "log_start": "LOG",
    "version": "BUILD",
    "channel_uri": "CHANNEL",
    "cluster": "CLUSTER",
    "steam_auth": "STEAM",
    "omni": "OMNI",
    "credentials": "CREDS",
    "campfire": "LOGIN",
    "player": "PLAYER",
    "persona": "PERSONA",
    "character": "CHAR",
    "world_id": "WORLD",
    "world_name": "WORLD",
    "queue": "QUEUE",
    "login_ticket": "TICKET",
    "rep": "REP",
    "rep_socket": "REP",
    "registration": "V3",
    "ingame": "INGAME",
    "level": "LEVEL",
    "state": "STATE",
    "error": "ERROR",
}


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def default_paths() -> dict[str, Path]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    roaming = Path(os.environ.get("APPDATA", ""))
    pf86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    return {
        "game_log": local / "AGS" / "New World" / "Game.log",
        "ags_local": local / "AGS" / "New World",
        "ags_roaming": roaming / "AGS" / "New World",
        "eac_roaming": roaming / "EasyAntiCheat",
        "install": pf86 / "Steam" / "steamapps" / "common" / "New World",
        "steam_logs": pf86 / "Steam" / "logs",
        "exe": pf86
        / "Steam"
        / "steamapps"
        / "common"
        / "New World"
        / "Bin64"
        / "NewWorld.exe",
        "launcher": pf86
        / "Steam"
        / "steamapps"
        / "common"
        / "New World"
        / "NewWorldLauncher.exe",
    }


def copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists() or not src.is_file():
        return False
    ensure_dir(dst.parent)
    shutil.copy2(src, dst)
    return True


def file_version(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        raw = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-Item -LiteralPath '{path}').VersionInfo | "
                "Select-Object FileVersion,ProductVersion,FileDescription | ConvertTo-Json -Compress",
            ],
            creationflags=0x08000000,
            timeout=20,
        ).decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def sha256_file(path: Path, limit: int | None = None) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            n += len(chunk)
            if limit and n >= limit:
                break
    return h.hexdigest()


def fetch_channel_config(dst: Path) -> bool:
    try:
        with urlopen(CHANNEL_CONFIG_URL, timeout=20) as r:
            data = r.read()
        dst.write_bytes(data)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# pcapng stats
# ---------------------------------------------------------------------------


def pcapng_stats(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    ip_bytes: Counter[str] = Counter()
    ip_pkts: Counter[str] = Counter()
    ports: Counter[str] = Counter()
    proto_c: Counter[str] = Counter()
    udp_endpoints: Counter[str] = Counter()
    n = 0
    try:
        data = path.read_bytes()
    except Exception:
        return {}
    off = 0
    total = len(data)
    while off + 8 <= total:
        try:
            btype, blen = struct.unpack_from("<II", data, off)
        except struct.error:
            break
        if blen < 12 or off + blen > total:
            break
        if btype == 0x00000006 and blen >= 32:  # Enhanced Packet Block
            caplen = struct.unpack_from("<I", data, off + 20)[0]
            pkt_off = off + 28
            pkt = data[pkt_off : pkt_off + caplen]
            n += 1
            _acc_packet(pkt, ip_bytes, ip_pkts, ports, proto_c, udp_endpoints)
        off += blen
        if blen == 0:
            break
    top_ip = ip_pkts.most_common(30)
    return {
        "packets": n,
        "top_ips": [{"ip": ip, "pkts": c, "bytes": ip_bytes[ip]} for ip, c in top_ip],
        "top_udp_endpoints": [
            {"endpoint": e, "pkts": c} for e, c in udp_endpoints.most_common(20)
        ],
        "l4": dict(proto_c),
        "top_ports": [{"port": p, "pkts": c} for p, c in ports.most_common(20)],
    }


def _acc_packet(
    pkt: bytes,
    ip_bytes: Counter,
    ip_pkts: Counter,
    ports: Counter,
    proto_c: Counter,
    udp_endpoints: Counter,
) -> None:
    ip_off = None
    for i in range(min(len(pkt) - 20, 80)):
        if (pkt[i] & 0xF0) != 0x40:
            continue
        ihl = (pkt[i] & 0x0F) * 4
        if ihl < 20 or i + ihl + 4 > len(pkt):
            continue
        if pkt[i + 9] not in (1, 6, 17):
            continue
        ip_off = i
        break
    if ip_off is None:
        return
    ihl = (pkt[ip_off] & 0x0F) * 4
    proto = pkt[ip_off + 9]
    src = socket.inet_ntoa(pkt[ip_off + 12 : ip_off + 16])
    dst = socket.inet_ntoa(pkt[ip_off + 16 : ip_off + 20])
    plen = len(pkt) - ip_off
    ip = ip_off
    for addr in (src, dst):
        ip_bytes[addr] += plen
        ip_pkts[addr] += 1
    l4 = ip + ihl
    if proto == 6:
        proto_c["TCP"] += 1
        if l4 + 4 <= len(pkt):
            sp, dp = struct.unpack_from("!HH", pkt, l4)
            ports[f"TCP/{sp}"] += 1
            ports[f"TCP/{dp}"] += 1
    elif proto == 17:
        proto_c["UDP"] += 1
        if l4 + 4 <= len(pkt):
            sp, dp = struct.unpack_from("!HH", pkt, l4)
            ports[f"UDP/{sp}"] += 1
            ports[f"UDP/{dp}"] += 1
            udp_endpoints[f"{src}:{sp}->{dst}:{dp}"] += 1


# ---------------------------------------------------------------------------
# Static EXE strings (file read, not process memory)
# ---------------------------------------------------------------------------


def extract_exe_strings(exe: Path, out_dir: Path, min_len: int = 8) -> dict[str, int]:
    ensure_dir(out_dir)
    urls: set[str] = set()
    hosts: set[str] = set()
    interesting: list[str] = []
    needles = (
        "https://",
        "http://",
        "cloudfront",
        "amazonaws",
        "amazongames",
        "Omni",
        "Javelin",
        "GridMate",
        "AuthManager",
        "GameConnection",
        "WaitingForREP",
        "credentials/omni",
        "tokenservice",
        "DTLS",
        "EasyAntiCheat",
        "Campfire",
        "Slayer",
        "Coatlicue",
        "Vivox",
        "STEAM_APP",
        "execute-api",
    )
    buf = bytearray()
    n_strings = 0
    try:
        with exe.open("rb") as f:
            while True:
                chunk = f.read(8 * 1024 * 1024)
                if not chunk:
                    break
                for b in chunk:
                    if 32 <= b < 127:
                        buf.append(b)
                    else:
                        if len(buf) >= min_len:
                            s = buf.decode("ascii")
                            n_strings += 1
                            if any(n in s for n in needles):
                                interesting.append(s)
                                for u in URL_RE.findall(s):
                                    urls.add(u)
                                if INTERESTING_HOST_RE.search(s):
                                    hosts.add(s[:300])
                        buf.clear()
    except OSError as e:
        write_json(out_dir / "error.json", {"error": str(e)})
        return {"strings": 0}
    uniq = sorted(set(interesting))
    (out_dir / "interesting_strings.txt").write_text(
        "\n".join(uniq) + "\n", encoding="utf-8"
    )
    (out_dir / "urls.txt").write_text("\n".join(sorted(urls)) + "\n", encoding="utf-8")
    (out_dir / "hosts_raw.txt").write_text(
        "\n".join(sorted(hosts)) + "\n", encoding="utf-8"
    )
    write_json(
        out_dir / "summary.json",
        {
            "exe": str(exe),
            "size": exe.stat().st_size if exe.exists() else 0,
            "ascii_strings_ge_min": n_strings,
            "interesting": len(uniq),
            "urls": len(urls),
        },
    )
    return {"strings": n_strings, "interesting": len(uniq), "urls": len(urls)}


# ---------------------------------------------------------------------------
# Watch loop
# ---------------------------------------------------------------------------


class Watcher:
    def __init__(self, session: Path, parent_pid: int | None) -> None:
        self.session = session
        self.parent_pid = parent_pid
        self.paths = default_paths()
        self.stop_file = session / "STOP"
        self.seen_pids: dict[int, dict[str, Any]] = {}
        self.conn_key: set[str] = set()
        self.log_fh = None
        self.log_offset = 0
        self.log_inode = None
        self.reached_ingame = False
        self.identities: dict[str, Any] = {"history": []}
        self.states: list[dict[str, str]] = []
        self.urls: set[str] = set()
        self.hosts: set[str] = set()
        self.rep_endpoints: set[str] = set()
        self.kinds: Counter[str] = Counter()
        self.last_dns = 0.0
        self.last_status = 0.0
        self.last_file_snap = 0.0
        self.live_log_started = False
        self.t0 = time.time()
        self.metrics: dict[str, Any] = {
            "started_utc": utc_now(),
            "log_lines": 0,
            "events": 0,
            "process_starts": 0,
            "conn_opens": 0,
            "tick_errors": 0,
            "dns_snapshots": 0,
        }

    def run(self) -> None:
        import traceback

        ensure_dir(self.session / "logs")
        ensure_dir(self.session / "network")
        ensure_dir(self.session / "process")
        ensure_dir(self.session / "files")
        ensure_dir(self.session / "extracted")
        log_line(self.session, "watcher start — waiting for launcher/client")
        log_line(self.session, "passive mode: no VM_READ, no inject")
        (self.session / "WATCHING").write_text(str(os.getpid()), encoding="utf-8")

        try:
            while not self.stop_file.exists():
                if self.parent_pid and not _pid_alive(self.parent_pid):
                    log_line(self.session, "parent process gone — stopping watcher")
                    break
                now = time.time()
                try:
                    self._tick_processes()
                    self._tick_log()
                    self._tick_connections()
                    if now - self.last_dns > 15:
                        self._tick_dns()
                        self.last_dns = now
                    if now - self.last_file_snap > 30:
                        self._tick_files()
                        self.last_file_snap = now
                    if now - self.last_status > 2:
                        self._write_status()
                        self.last_status = now
                except Exception:
                    self.metrics["tick_errors"] = (
                        int(self.metrics.get("tick_errors") or 0) + 1
                    )
                    log_line(self.session, "tick error:\n" + traceback.format_exc())
                    time.sleep(1)
                time.sleep(0.35)
        except Exception:
            log_line(self.session, "watcher crash:\n" + traceback.format_exc())
            raise
        finally:
            try:
                self._tick_files(final=True)
                self._write_status()
            except Exception:
                pass
            self.close_log()
            try:
                (self.session / "WATCHING").unlink(missing_ok=True)
            except Exception:
                pass
            self._write_metrics(final=True)
            log_line(self.session, "watcher stop")

    def close_log(self) -> None:
        if self.log_fh:
            try:
                self.log_fh.close()
            except Exception:
                pass
            self.log_fh = None

    def _tick_processes(self) -> None:
        procs = list_processes()
        current = {p["pid"]: p for p in procs}
        for pid, p in current.items():
            if pid not in self.seen_pids:
                image = query_image_path(pid)
                rec = {**p, "image": image, "ts": utc_now(), "event": "start"}
                self.seen_pids[pid] = rec
                append_jsonl(self.session / "process" / "processes.jsonl", rec)
                self.metrics["process_starts"] = (
                    int(self.metrics.get("process_starts") or 0) + 1
                )
                log_line(
                    self.session,
                    f"proc+ {p['role']} pid={pid} {p['name']}"
                    + (f" {image}" if image else ""),
                )
        for pid in list(self.seen_pids):
            if pid not in current and self.seen_pids[pid].get("event") != "stop":
                rec = {**self.seen_pids[pid], "ts": utc_now(), "event": "stop"}
                self.seen_pids[pid] = rec
                append_jsonl(self.session / "process" / "processes.jsonl", rec)
                log_line(self.session, f"proc- {rec.get('role')} pid={pid}")

    def _open_log(self) -> None:
        path = self.paths["game_log"]
        if not path.exists():
            return
        self.close_log()
        self.log_fh = path.open("r", encoding="utf-8", errors="replace")
        self.log_offset = 0

    def _tick_log(self) -> None:
        path = self.paths["game_log"]
        if not path.exists():
            return
        size = path.stat().st_size
        if self.log_fh is None:
            self._open_log()
            if self.log_fh is None:
                return
            # If client not running yet, skip old content until a new log starts.
            client_live = any(
                v.get("role") == "client" and v.get("event") != "stop"
                for v in self.seen_pids.values()
            )
            if not client_live:
                self.log_fh.seek(0, os.SEEK_END)
                self.log_offset = self.log_fh.tell()
                return
        if size < self.log_offset:
            log_line(self.session, "Game.log truncated — new client session")
            self._open_log()
            self.live_log_started = True
        if self.log_fh is None:
            return
        while True:
            pos = self.log_fh.tell()
            line = self.log_fh.readline()
            if not line:
                self.log_fh.seek(pos)
                break
            self.log_offset = self.log_fh.tell()
            self._on_log_line(line.rstrip("\n"))

    def _on_log_line(self, line: str) -> None:
        raw_path = self.session / "logs" / "Game.log.raw"
        red_path = self.session / "logs" / "Game.log.redacted"
        self.metrics["log_lines"] = int(self.metrics.get("log_lines") or 0) + 1
        with raw_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        with red_path.open("a", encoding="utf-8") as f:
            f.write(redact(line) + "\n")

        m = TS_RE.match(line)
        rest = m.group("rest") if m else line
        ts = m.group("ts") if m else ""
        ev = classify_log_line(rest)
        if not ev:
            return
        ev["ts"] = ts
        ev["utc"] = utc_now()
        self.kinds[ev["kind"]] += 1
        self.metrics["events"] = int(self.metrics.get("events") or 0) + 1
        append_jsonl(self.session / "logs" / "events.jsonl", ev)

        for u in ev.get("urls") or []:
            self.urls.add(u)
            h = u.split("/")[2] if "://" in u else ""
            if h:
                self.hosts.add(h)
        if ev["kind"] == "channel_uri" and ev.get("url"):
            self.urls.add(ev["url"])
        if ev["kind"] == "http":
            pass
        if ev["kind"] == "state":
            self.states.append({"ts": ts, "from": ev["from"], "to": ev["to"]})
            append_jsonl(
                self.session / "extracted" / "state_machine.jsonl",
                {"ts": ts, "from": ev["from"], "to": ev["to"]},
            )
        if ev["kind"] in ("player", "persona", "character", "world_id", "world_name"):
            key = ev["kind"]
            self.identities[key] = ev.get("name") or ev.get("id")
            self._record_identity_entry(ts)
        if ev["kind"] == "rep" and ev.get("endpoint"):
            self.rep_endpoints.add(ev["endpoint"])
            self.identities["rep"] = ev["endpoint"]
            self._record_identity_entry(ts)
        if ev["kind"] in ("ingame",) or (
            ev["kind"] == "state" and ev.get("to") == "InGame"
        ):
            self.reached_ingame = True

        tag = HIGHLIGHT_KINDS.get(ev["kind"])
        if tag:
            brief = redact(rest)
            if len(brief) > 180:
                brief = brief[:177] + "..."
            log_line(self.session, f"{tag:8} {brief}")

        if ev["kind"] in (
            "player",
            "persona",
            "character",
            "world_id",
            "world_name",
            "rep",
        ):
            write_json(self.session / "extracted" / "identities.json", self.identities)

    def _record_identity_entry(self, ts: str) -> None:
        entry = {
            "ts": ts,
            "player": self.identities.get("player"),
            "character": self.identities.get("character"),
            "rep": self.identities.get("rep"),
        }
        hist: list[dict[str, Any]] = self.identities.setdefault("history", [])
        if (
            hist
            and hist[-1].get("player") == entry["player"]
            and hist[-1].get("character") == entry["character"]
        ):
            hist[-1]["rep"] = entry["rep"] or hist[-1].get("rep")
            hist[-1]["ts"] = ts
            return
        if entry["player"] or entry["character"]:
            hist.append(entry)

    def _tick_connections(self) -> None:
        live = {
            pid
            for pid, rec in self.seen_pids.items()
            if rec.get("event") != "stop"
            and rec.get("role") in ("client", "launcher", "eac-eos", "eac")
        }
        rows = parse_netstat(live)
        now_keys = set()
        for r in rows:
            key = f"{r['pid']}|{r['proto']}|{r['local']}|{r['remote']}|{r['state']}"
            now_keys.add(key)
            if key not in self.conn_key:
                rec = {**r, "ts": utc_now(), "event": "open"}
                append_jsonl(self.session / "network" / "connections.jsonl", rec)
                self.metrics["conn_opens"] = (
                    int(self.metrics.get("conn_opens") or 0) + 1
                )
                remote = r["remote"]
                if remote and remote not in ("*:*", "0.0.0.0:0", "[::]:0"):
                    log_line(
                        self.session,
                        f"net {r['proto']} {r['local']} -> {r['remote']} pid={r['pid']} {r['state']}",
                    )
                # REP address comes from Game.log, not from every TCP/443 peer.
        for old in self.conn_key - now_keys:
            parts = old.split("|")
            append_jsonl(
                self.session / "network" / "connections.jsonl",
                {
                    "ts": utc_now(),
                    "event": "close",
                    "pid": parts[0] if parts else "",
                    "proto": parts[1] if len(parts) > 1 else "",
                    "local": parts[2] if len(parts) > 2 else "",
                    "remote": parts[3] if len(parts) > 3 else "",
                },
            )
        self.conn_key = now_keys

    def _tick_dns(self) -> None:
        rows = dns_cache_snapshot()
        if not rows:
            return
        self.metrics["dns_snapshots"] = int(self.metrics.get("dns_snapshots") or 0) + 1
        append_jsonl(
            self.session / "network" / "dns.jsonl",
            {"ts": utc_now(), "entries": rows},
        )
        for r in rows:
            if r.get("name"):
                self.hosts.add(r["name"])

    def _tick_files(self, final: bool = False) -> None:
        dest = self.session / "files"
        mapping = {
            "user_preload_settings.cfg": self.paths["ags_roaming"]
            / "user_preload_settings.cfg",
            "analytics_uuid.txt": self.paths["ags_roaming"] / "analytics_uuid.txt",
            "bootstrap.cfg": self.paths["install"] / "bootstrap.cfg",
            "engine.json": self.paths["install"] / "engine.json",
            "EasyAntiCheat_Settings.json": self.paths["install"]
            / "EasyAntiCheat"
            / "Settings.json",
            "steam_runprocess_log.txt": self.paths["steam_logs"] / "runprocess_log.txt",
        }
        eac_root = self.paths["eac_roaming"]
        if eac_root.exists():
            mapping["eac_service.log"] = eac_root / "service.log"
            for p in eac_root.rglob("anticheatlauncher.log"):
                mapping["eac_anticheatlauncher.log"] = p
                break
        suffix = ".final" if final else ""
        for name, src in mapping.items():
            copy_if_exists(src, dest / f"{name}{suffix}")
        ch = dest / "channel_config.json"
        if not ch.exists():
            if fetch_channel_config(ch):
                log_line(self.session, "fetched channel_config.json")

    def _write_status(self) -> None:
        live = [v for v in self.seen_pids.values() if v.get("event") != "stop"]
        status = {
            "utc": utc_now(),
            "reached_ingame": self.reached_ingame,
            "processes": live,
            "identities": self.identities,
            "rep_endpoints": sorted(self.rep_endpoints),
            "states": self.states[-20:],
            "event_counts": dict(self.kinds),
            "urls": len(self.urls),
        }
        write_json(self.session / "status.json", status)
        self._write_metrics(final=False)
        live_s = ", ".join(f"{p['role']}:{p['pid']}" for p in live) or "(none)"
        last = self.states[-1] if self.states else None
        current = last["to"] if last else "-"
        trans = f"{last['from']} -> {last['to']} @ {last['ts']}" if last else "-"
        lines = [
            f"utc             {status['utc']}",
            f"ingame          {self.reached_ingame}",
            f"current_state   {current}",
            f"last_transition {trans}",
            f"processes       {live_s}",
            f"rep             {', '.join(sorted(self.rep_endpoints)) or '(none yet)'}",
            f"player          {self.identities.get('player', '')}",
            f"world           {self.identities.get('world_name', '')} {self.identities.get('world_id', '')}",
            f"events          {self.metrics.get('events', 0)}  log_lines={self.metrics.get('log_lines', 0)}",
        ]
        (self.session / "STATUS.txt").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
        urls = sorted(self.urls)
        (self.session / "extracted" / "urls.txt").write_text(
            "\n".join(urls) + "\n", encoding="utf-8"
        )
        (self.session / "extracted" / "hosts.txt").write_text(
            "\n".join(sorted(self.hosts)) + "\n", encoding="utf-8"
        )
        write_json(
            self.session / "extracted" / "rep_endpoints.json",
            {"endpoints": sorted(self.rep_endpoints)},
        )

    def _write_metrics(self, final: bool) -> None:
        m = dict(self.metrics)
        m["updated_utc"] = utc_now()
        m["elapsed_sec"] = round(time.time() - self.t0, 2)
        m["final"] = final
        m["reached_ingame"] = self.reached_ingame
        m["event_counts"] = dict(self.kinds)
        m["unique_urls"] = len(self.urls)
        m["unique_hosts"] = len(self.hosts)
        m["rep_endpoints"] = sorted(self.rep_endpoints)
        write_json(self.session / "metrics.json", m)


def _pid_alive(pid: int) -> bool:
    if not pid:
        return True
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    # Fallback: Toolhelp snapshot (no VM_READ).
    kernel32 = ctypes.windll.kernel32
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return True
    try:
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not kernel32.Process32FirstW(snap, ctypes.byref(pe)):
            return False
        while True:
            if int(pe.th32ProcessID) == pid:
                return True
            if not kernel32.Process32NextW(snap, ctypes.byref(pe)):
                return False
    finally:
        kernel32.CloseHandle(snap)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def build_report(session: Path) -> None:
    events_path = session / "logs" / "events.jsonl"
    events: list[dict[str, Any]] = []
    if events_path.exists():
        for line in events_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    identities = {}
    idp = session / "extracted" / "identities.json"
    if idp.exists():
        identities = json.loads(idp.read_text(encoding="utf-8"))
    pcap = session / "network" / "pktmon.pcapng"
    net_stats = pcapng_stats(pcap) if pcap.exists() else {}
    status = {}
    if (session / "status.json").exists():
        status = json.loads((session / "status.json").read_text(encoding="utf-8"))

    kinds = Counter(e.get("kind") for e in events)
    states = [e for e in events if e.get("kind") == "state"]
    errors = [e for e in events if e.get("kind") == "error"]
    http = [
        e
        for e in events
        if e.get("kind") in ("http", "cms", "channel_uri", "credentials")
    ]
    rmi = [e for e in events if e.get("kind") == "rmi"]

    missing = []
    need = [
        ("log_start", "Game.log this session"),
        ("steam_auth", "Steam auth"),
        ("omni", "OmniSDK"),
        ("campfire", "Campfire login"),
        ("queue", "Login queue"),
        ("rep", "REP address"),
        ("rep_socket", "REP socket"),
        ("registration", "V3 registration"),
        ("ingame", "InGame"),
    ]
    have = set(kinds)
    # also InGame via state
    if any(e.get("to") == "InGame" for e in states):
        have.add("ingame")
    for key, label in need:
        if key not in have:
            missing.append(label)

    metrics = {}
    mp = session / "metrics.json"
    if mp.exists():
        try:
            metrics = json.loads(mp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            metrics = {}

    lines = [
        f"# New World capture — {session.name}",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Metrics",
        "",
        f"- elapsed_sec: `{metrics.get('elapsed_sec', '')}`",
        f"- log_lines: `{metrics.get('log_lines', 0)}`",
        f"- events: `{metrics.get('events', 0)}`",
        f"- process_starts: `{metrics.get('process_starts', 0)}`",
        f"- conn_opens: `{metrics.get('conn_opens', 0)}`",
        f"- tick_errors: `{metrics.get('tick_errors', 0)}`",
        f"- unique_urls: `{metrics.get('unique_urls', 0)}`",
        f"- pcap_packets: `{net_stats.get('packets', 0) if net_stats else 0}`",
        "",
        "## Identity",
        "",
        f"- Player: `{identities.get('player', '')}`",
        f"- Persona: `{identities.get('persona', '')}`",
        f"- Character: `{identities.get('character', '')}`",
        f"- World: `{identities.get('world_name', '')}` `{identities.get('world_id', '')}`",
        f"- REP: `{identities.get('rep', '')}`",
        f"- InGame: **{status.get('reached_ingame', False)}**",
        "",
        "## Session checklist",
        "",
    ]
    for key, label in need:
        mark = "x" if key in have else " "
        lines.append(f"- [{mark}] {label}")
    if missing:
        lines += ["", f"Missing: {', '.join(missing)}", ""]
    else:
        lines += ["", "Full ladder: launcher -> InGame.", ""]

    lines += ["## GameConnection states", ""]
    if states:
        lines.append("```")
        for e in states:
            lines.append(f"{e.get('ts', ''):26}  {e.get('from')} -> {e.get('to')}")
        lines.append("```")
    else:
        lines.append("_No GameConnection transitions. Did the client start?_")

    lines += ["", "## Events by kind", "", "| kind | count |", "|---|---|"]
    for k, c in kinds.most_common():
        lines.append(f"| `{k}` | {c} |")

    lines += ["", "## HTTP / CMS (from Game.log)", ""]
    urls = []
    up = session / "extracted" / "urls.txt"
    if up.exists():
        urls = [u for u in up.read_text(encoding="utf-8").splitlines() if u.strip()]
    if urls:
        lines.append("```")
        lines.extend(urls[:80])
        lines.append("```")
    else:
        lines.append("_No URLs extracted._")

    lines += ["", "## Network (pcapng)", ""]
    if net_stats:
        lines.append(f"- packets: **{net_stats.get('packets', 0)}**")
        lines.append(f"- L4: `{net_stats.get('l4', {})}`")
        lines += ["", "Top IPs:", "", "| ip | pkts | bytes |", "|---|---|---|"]
        for row in net_stats.get("top_ips", [])[:15]:
            lines.append(f"| `{row['ip']}` | {row['pkts']} | {row['bytes']} |")
        if net_stats.get("top_udp_endpoints"):
            lines += ["", "UDP endpoints (REP candidates):", ""]
            for row in net_stats["top_udp_endpoints"][:10]:
                lines.append(f"- `{row['endpoint']}` ({row['pkts']} pkts)")
        write_json(session / "network" / "pcap_stats.json", net_stats)
    else:
        lines.append("_No pcapng. Need admin pktmon, or etl2pcap failed._")

    lines += ["", "## Client errors", ""]
    if errors:
        lines.append("```")
        for e in errors[:40]:
            lines.append(f"{e.get('ts', '')} {e.get('text', '')[:300]}")
        lines.append("```")
    else:
        lines.append("_No [ERROR] lines in parsed log._")

    lines += ["", "## RMI / facets (live protocol names)", ""]
    if rmi:
        types = Counter()
        for e in rmi:
            mt = re.search(r'"messageType":"([^"]+)"', e.get("text") or "")
            if mt:
                types[mt.group(1)] += 1
        if types:
            lines += ["| messageType | count |", "|---|---|"]
            for k, c in types.most_common(40):
                lines.append(f"| `{k}` | {c} |")
        else:
            lines.append(f"{len(rmi)} RMI lines without parseable messageType.")
    else:
        lines.append("_No RMI. Normal if you never spawned._")

    lines += [
        "",
        "## Session files",
        "",
        "```",
        "metrics.json                 counters for this run",
        "logs/Game.log.raw            full log (Steam tickets — do not share)",
        "logs/Game.log.redacted       same log, tickets stripped",
        "logs/events.jsonl            structured events",
        "network/pktmon.pcapng        NIC UDP/HTTPS",
        "network/connections.jsonl    netstat for game PIDs",
        "extracted/                   urls, hosts, states, identities",
        "```",
        "",
        "## Next use",
        "",
        "1. `extracted/identities.json` + `rep_endpoints.json` feed the auth mock (RepAddress).",
        "2. `events.jsonl` is the HTTP sequence the gateway must answer.",
        "3. `pktmon.pcapng` is DTLS/UDP timing (ciphertext: IP/port/sizes/handshake).",
        "4. Do not read process memory while EAC talks to Amazon.",
        "",
    ]
    (session / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_init(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    session = ensure_dir(
        Path(args.session) if args.session else repo / "sessions" / local_stamp()
    )
    for sub in ("logs", "network", "process", "files", "extracted", "static"):
        ensure_dir(session / sub)
    paths = default_paths()
    meta = {
        "created": utc_now(),
        "repo": str(repo),
        "session": str(session),
        "steam_app_id": STEAM_APP_ID,
        "install": str(paths["install"]),
        "exe": str(paths["exe"]),
        "exe_exists": paths["exe"].exists(),
        "exe_version": file_version(paths["exe"]),
        "launcher_version": file_version(paths["launcher"]),
        "mode": "passive-safe",
        "notes": "No process memory reads. No injection. pktmon on NIC + Game.log + netstat + DNS.",
    }
    if paths["exe"].exists() and args.hash_exe:
        log_line(session, "Calculando SHA-256 del exe (archivo en disco)...")
        meta["exe_sha256"] = sha256_file(paths["exe"])
    write_json(session / "session.json", meta)
    print(str(session))
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    session = Path(args.session).resolve()
    ensure_dir(session / "logs")
    w = Watcher(session, args.parent_pid)
    try:
        w.run()
    except KeyboardInterrupt:
        try:
            w.stop_file.write_text("interrupt\n", encoding="utf-8")
        except Exception:
            pass
        log_line(session, "Ctrl+C — cerrando watcher.")
        w.close_log()
        w._tick_files(final=True)
        w._write_status()
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    session = Path(args.session).resolve()
    build_report(session)
    print(session / "REPORT.md")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Parse an existing Game.log into a session folder (no live watch)."""
    repo = Path(args.repo).resolve() if args.repo else Path.cwd()
    log_path = Path(args.log).resolve()
    session = (
        Path(args.session).resolve()
        if args.session
        else repo / "sessions" / (local_stamp() + "_ingest")
    )
    for sub in ("logs", "network", "process", "files", "extracted"):
        ensure_dir(session / sub)
    write_json(
        session / "session.json",
        {
            "created": utc_now(),
            "mode": "ingest-log",
            "source_log": str(log_path),
        },
    )
    w = Watcher(session, 0)
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        w._on_log_line(line)
    w._write_status()
    w._write_metrics(final=True)
    shutil.copy2(log_path, session / "logs" / "Game.log.source")
    build_report(session)
    print(str(session))
    return 0


def cmd_static(args: argparse.Namespace) -> int:
    exe = Path(args.exe) if args.exe else default_paths()["exe"]
    out = Path(args.out).resolve() if args.out else Path(args.session) / "static"
    log_msg_session = Path(args.session) if args.session else out
    ensure_dir(out)
    print(f"extracting strings {exe} -> {out}")
    stats = extract_exe_strings(exe, out)
    print(json.dumps(stats))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="New World passive capture")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.add_argument("--repo", required=True)
    s.add_argument("--session")
    s.add_argument("--hash-exe", action="store_true")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("watch")
    s.add_argument("--session", required=True)
    s.add_argument("--parent-pid", type=int, default=0)
    s.set_defaults(func=cmd_watch)

    s = sub.add_parser("report")
    s.add_argument("--session", required=True)
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("ingest")
    s.add_argument("--log", required=True)
    s.add_argument("--repo")
    s.add_argument("--session")
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("static")
    s.add_argument("--session")
    s.add_argument("--exe")
    s.add_argument("--out")
    s.set_defaults(func=cmd_static)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
