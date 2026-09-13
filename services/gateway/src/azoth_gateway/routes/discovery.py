"""Discovery: dump unknown paths (best-effort, capped) and answer 404 JSON.

Purpose: when the client advances past channel/CMS (Omni -> queue -> REP),
we see the next JSON in the clear and can freeze a schema for it.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

MAX_FILES = 200


class DiscoveryLog:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._lock = threading.Lock()
        self._count = 0

    def dump(self, method: str, path: str, headers: dict[str, str], body: bytes = b"") -> int:
        with self._lock:
            self._count += 1
            n = self._count
        try:
            if n > MAX_FILES:
                return n
            self.directory.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            fp = self.directory / f"{ts}-{n:04d}.json"
            entry: dict = {"n": n, "ts": ts, "method": method, "path": path, "headers": headers}
            if body:
                try:
                    entry["body_json"] = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    entry["body_len"] = len(body)
                    entry["body_hex"] = body[:512].hex()
            fp.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass
        return n
