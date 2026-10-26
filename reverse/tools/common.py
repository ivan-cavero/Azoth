"""Shared paths and constants. Never opens the game process."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parents[1]

# Scripts live in kind folders (`pe/`, `corpus/`, `type/`, ...) and import across
# them: `corpus/decomp.py` uses `peutil`, `pe/*.py` and `type/*.py` use `catalog`.
# Appended, never inserted, so a kind folder cannot shadow the standard library.
for _kind in sorted(TOOLS.iterdir()):
    if _kind.is_dir() and not _kind.name.startswith(("_", ".")):
        if str(_kind) not in sys.path:
            sys.path.append(str(_kind))

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
    r"epicgames\.com|easyanticheat\.net|eac-cdn\.com)",
    re.I,
)
URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%\-]+")
TICKET_RE = re.compile(r"(steam\|[0-9a-fA-F]{16,})")
AWS_KEY_RE = re.compile(r"\b(ASIA[A-Z0-9]{16}|AKIA[A-Z0-9]{16})\b")

ENDPOINT_ROLES = {
    "d2c74t4zimux3r.cloudfront.net": "channel-config",
    "tokenservice.amazongames.com": "omni-tokens",
    "prod.newworld.com": "nw-token-legacy",
    "d1w0bfy6smo4d1.cloudfront.net": "gateway-cf-eu",
    "d2oeuvxi3kfsrw.cloudfront.net": "gateway-cf-us-east",
    "d3bj4csovi1fe8.cloudfront.net": "gateway-cf-us-west",
    "d1cjlmzk0xrm0z.cloudfront.net": "gateway-cf-sa-east",
    "de4mfzk9wkelz.cloudfront.net": "gateway-cf-ap-se",
    "d1hkbwzm1bktgo.cloudfront.net": "cms",
    "client.content-service.amazongames.com": "cms-images",
    "client.entitlementservice.amazongames.com": "entitlements",
    "client.catalogservice.amazongames.com": "catalog",
    "client.agsprivacysettingsservice.amazongames.com": "privacy",
    "ags-javelin-remote-config.s3.amazonaws.com": "remote-config-s3",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_json(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def append_jsonl(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def redact(text: str) -> str:
    text = TICKET_RE.sub(lambda m: f"steam|<redacted len={len(m.group(1))}>", text)
    text = AWS_KEY_RE.sub("ASIA<redacted>", text)
    return text


def default_paths() -> dict[str, Path]:
    pf86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    repo = Path(__file__).resolve().parents[2]
    private = repo / "private-client"
    local = private / "profile" / "Local"
    roaming = private / "profile" / "Roaming"
    configured_install = os.environ.get("AZOTH_GAME_INSTALL")
    install = Path(configured_install) if configured_install else None
    manifest = private / "state" / "client-source.json"
    if install is None:
        try:
            candidate = Path(json.loads(manifest.read_text(encoding="utf-8"))["install"])
            if (candidate / "Bin64" / "NewWorld.exe").is_file():
                install = candidate
        except (OSError, KeyError, json.JSONDecodeError, TypeError):
            pass
    if install is None:
        install = pf86 / "Steam" / "steamapps" / "common" / "New World"
    return {
        "game_log": local / "AGS" / "New World" / "Game.log",
        "ags_local": local / "AGS" / "New World",
        "ags_roaming": roaming / "AGS" / "New World",
        "eac_roaming": roaming / "EasyAntiCheat",
        "install": install,
        "exe": install / "Bin64" / "NewWorld.exe",
        "launcher": install / "NewWorldLauncher.exe",
        "eac_dir": install / "EasyAntiCheat",
        "steam_logs": pf86 / "Steam" / "logs",
        "repo": repo,
        "research": repo / "research",
        "private_client": private,
        "state": repo / ".azoth",
    }


def decomp_work(exe: Path | None = None) -> Path:
    """Return the local workspace for one exact client build."""
    root = Path(__file__).resolve().parents[2] / "reverse" / "builds"
    if exe is not None and exe.is_file():
        return root / sha256_file(exe)
    return root


@lru_cache(maxsize=8)
def _sha256_file_cached(
    path: str, size: int, mtime_ns: int, ctime_ns: int, file_id: int
) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    stat = path.stat()
    return _sha256_file_cached(
        str(path.resolve()),
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
        stat.st_ino,
    )


def decomp_corpus_dir(exe: Path) -> Path:
    """Return the corpus directory keyed to the exact executable build."""
    return decomp_work(exe) / "corpus"


def decode_l3(pkt: bytes):
    """Locate IPv4 in a frame (Ethernet, SNAP, or pktmon metadata prefix)."""
    import socket

    if len(pkt) < 20:
        return None
    ip_off = None
    for i in range(min(len(pkt) - 20, 80)):
        vi = pkt[i]
        if (vi & 0xF0) != 0x40:
            continue
        ihl = (vi & 0x0F) * 4
        if ihl < 20 or i + ihl + 4 > len(pkt):
            continue
        proto = pkt[i + 9]
        if proto not in (1, 6, 17):
            continue
        ip_off = i
        break
    if ip_off is None:
        return None
    ihl = (pkt[ip_off] & 0x0F) * 4
    proto = pkt[ip_off + 9]
    src = socket.inet_ntoa(pkt[ip_off + 12 : ip_off + 16])
    dst = socket.inet_ntoa(pkt[ip_off + 16 : ip_off + 20])
    return proto, src, dst, pkt[ip_off + ihl :]


def role_for_host(host: str) -> str:
    host = host.lower().split(":")[0]
    if host in ENDPOINT_ROLES:
        return ENDPOINT_ROLES[host]
    if "execute-api" in host and "amazonaws.com" in host:
        return "api-gateway"
    if "cloudfront.net" in host:
        return "cloudfront-unknown"
    if "vivox.com" in host:
        return "voice-vivox"
    if "steampowered.com" in host or "steamcommunity.com" in host:
        return "steam"
    if "easyanticheat" in host or "eac-cdn" in host:
        return "eac-backend"
    return "unknown"
