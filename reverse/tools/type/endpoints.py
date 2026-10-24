#!/usr/bin/env python3
"""Merge channel-config + Game.log + DNS + pcap SNI into an endpoint catalog.

This is the host map the private gateway must implement.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import (  # noqa: E402
    CHANNEL_CONFIG_URL,
    URL_RE,
    default_paths,
    role_for_host,
    utc_now,
    write_json,
)

PATH_ROLES = [
    (re.compile(r"credentials/omni", re.I), "auth-credentials-omni"),
    (re.compile(r"/prod/game/getlogininfo", re.I), "game-getlogininfo"),
    (re.compile(r"/prod/game/login/queue", re.I), "game-login-queue"),
    (re.compile(r"/characters/validator", re.I), "character-validate"),
    (re.compile(r"/characters", re.I), "character-create"),
    (re.compile(r"/entitlements/sync", re.I), "entitlements-sync"),
    (re.compile(r"/entitlements", re.I), "entitlements-list"),
    (re.compile(r"/games/new-world/tokens", re.I), "omni-tokens"),
    (re.compile(r"jwks\.json", re.I), "omni-jwks"),
    (re.compile(r"openid-configuration", re.I), "omni-oidc"),
    (re.compile(r"/motd/", re.I), "cms-motd"),
    (re.compile(r"/newsstories/", re.I), "cms-news"),
    (re.compile(r"/marketingtiles/", re.I), "cms-marketing"),
    (re.compile(r"configuration-sets", re.I), "remote-config"),
    (re.compile(r"STEAM_APP_ID\.1063730\.json", re.I), "channel-config"),
]


def path_role(path: str) -> str:
    for rx, role in PATH_ROLES:
        if rx.search(path):
            return role
    return "unknown"


def load_channel() -> dict:
    p = default_paths()
    local = p["research"] / "_re" / "channel_config.json"
    if local.exists():
        return json.loads(local.read_text(encoding="utf-8"))
    try:
        with urlopen(CHANNEL_CONFIG_URL, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return {}


def urls_from_session(session: Path) -> list[str]:
    urls = []
    ufile = session / "extracted" / "urls.txt"
    if ufile.exists():
        urls.extend(
            [
                l.strip()
                for l in ufile.read_text(encoding="utf-8").splitlines()
                if l.strip()
            ]
        )
    raw = session / "logs" / "Game.log.redacted"
    if not raw.exists():
        raw = session / "logs" / "Game.log.raw"
    if raw.exists():
        for m in URL_RE.findall(raw.read_text(encoding="utf-8", errors="replace")):
            urls.append(m)
    return sorted(set(urls))


def merge(session: Path | None, extra_pcap_analysis: Path | None) -> dict:
    ch = load_channel()
    hosts: dict[str, dict] = defaultdict(
        lambda: {"roles": set(), "paths": set(), "sources": set(), "ips": set()}
    )

    def add(host: str, role: str, source: str, path: str = "", ip: str = ""):
        host = host.lower().split(":")[0]
        if not host:
            return
        rec = hosts[host]
        rec["roles"].add(role or role_for_host(host))
        rec["sources"].add(source)
        if path:
            rec["paths"].add(path)
        if ip:
            rec["ips"].add(ip)

    # channel config
    for key, val in ch.items():
        if key == "platformMetadata" and isinstance(val, dict):
            omni = val.get("OMNI.STEAM_APP_ID.1063730") or {}
            for field, url in omni.items():
                if isinstance(url, str) and url.startswith("http"):
                    u = urlparse(url)
                    add(u.netloc, "omni-meta", "channel_config", u.path)
            continue
        if isinstance(val, dict) and "publicApis" in val:
            add_cluster = key
            for api in val["publicApis"]:
                ep = api.get("apiEndpoint") or ""
                tag = api.get("clientTag") or ""
                add(ep, tag or "api", "channel_config", "")
                hosts[ep.lower()]["cluster"] = add_cluster
                hosts[ep.lower()]["awsRegion"] = api.get("awsRegion")

    if session:
        for url in urls_from_session(session):
            u = urlparse(url)
            add(
                u.netloc,
                path_role(u.path) or role_for_host(u.netloc),
                "gamelog",
                u.path,
            )
        dns = session / "network" / "dns.jsonl"
        if dns.exists():
            for line in dns.read_text(encoding="utf-8").splitlines():
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for e in obj.get("entries") or []:
                    add(
                        e.get("name") or "",
                        e.get("role") or "",
                        "dns",
                        ip=e.get("data") or "",
                    )
        analysis = extra_pcap_analysis or (session / "network" / "pktmon.analysis.json")
        if analysis.exists():
            an = json.loads(analysis.read_text(encoding="utf-8"))
            for row in an.get("sni") or []:
                add(row.get("host") or "", row.get("role") or "", "tls-sni")
            for f in an.get("rep_candidates") or []:
                for side in (f.get("a"), f.get("b")):
                    if (
                        side
                        and not side.startswith("192.168.")
                        and not side.startswith("10.")
                    ):
                        ip = side.rsplit(":", 1)[0]
                        add(ip, "rep-udp-dtls", "pcap-dtls")

    catalog = []
    for host, rec in sorted(hosts.items()):
        catalog.append(
            {
                "host": host,
                "roles": sorted(rec["roles"]),
                "paths": sorted(rec["paths"])[:40],
                "sources": sorted(rec["sources"]),
                "ips": sorted(rec["ips"]),
                "cluster": rec.get("cluster"),
                "awsRegion": rec.get("awsRegion"),
                "protocol": "UDP/DTLS"
                if "rep-udp-dtls" in rec["roles"]
                else "HTTPS/TLS",
            }
        )
    return {
        "utc": utc_now(),
        "channelName": ch.get("channelName"),
        "count": len(catalog),
        "endpoints": catalog,
        "notes": [
            "HTTPS: mock these hosts (hosts file + CA) for private login.",
            "UDP/DTLS: the queue ticket RepAddress must point at OUR socket.",
            "Omni CreateSession still wants a local Steam ticket; Steam open, Amazon not.",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", help="sessions/XXXX directory")
    ap.add_argument("--out")
    args = ap.parse_args()
    p = default_paths()
    session = Path(args.session) if args.session else None
    if session is None:
        # last known session pointer from the watcher
        last = p["research"] / "tools" / "capture" / ".last-session"
        ingest = p["research"] / "sessions" / "20260906_existing_gamelog"
        if last.exists():
            session = Path(last.read_text(encoding="utf-8").strip())
        elif ingest.exists():
            session = ingest
    cat = merge(session, None)
    out = (
        Path(args.out)
        if args.out
        else (
            session / "extracted" / "endpoints_catalog.json"
            if session
            else p["research"] / "sessions" / "endpoints_catalog.json"
        )
    )
    write_json(out, cat)
    print(f"{cat['count']} endpoints -> {out}")
    for e in cat["endpoints"]:
        print(f"  {e['protocol']:10} {','.join(e['roles'])[:28]:28} {e['host']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
