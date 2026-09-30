"""Fetch public CMS / channel JSON the client already requested."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "schemas" / "live"
URLS = {
    "channel": "https://d2c74t4zimux3r.cloudfront.net/STEAM_APP_ID.1063730.json",
    "motd": "https://d1hkbwzm1bktgo.cloudfront.net/motd/worlds_STEAM_APP_ID.1063730.json",
    "news": "https://d1hkbwzm1bktgo.cloudfront.net/newsstories/STEAM_APP_ID.1063730/metadata.json",
    "tiles": "https://d1hkbwzm1bktgo.cloudfront.net/marketingtiles/STEAM_APP_ID.1063730/metadata.json",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, url in URLS.items():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
                ctype = resp.headers.get("Content-Type")
            path = OUT / f"{name}.json"
            path.write_bytes(data)
            print(f"{name}: {len(data)} bytes ctype={ctype} -> {path}")
            try:
                obj = json.loads(data)
            except json.JSONDecodeError as exc:
                print(f"  not json: {exc}; head={data[:160]!r}")
                continue
            if isinstance(obj, dict):
                print(f"  dict keys={list(obj)[:24]}")
            elif isinstance(obj, list):
                print(f"  list len={len(obj)}")
                if obj and isinstance(obj[0], dict):
                    print(f"  first keys={list(obj[0])[:16]}")
            else:
                print(f"  type={type(obj).__name__}")
        except Exception as exc:  # noqa: BLE001
            print(f"{name}: FAIL {exc}")


if __name__ == "__main__":
    main()
