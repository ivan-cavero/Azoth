"""Health + metrics (tiny, no deps)."""

from __future__ import annotations

import json
import threading


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests = 0
        self.by_route: dict[str, int] = {}
        self.unknown_paths = 0

    def hit(self, route: str) -> None:
        with self._lock:
            self.requests += 1
            self.by_route[route] = self.by_route.get(route, 0) + 1
            if route == "discovery":
                self.unknown_paths += 1

    def snapshot(self) -> bytes:
        with self._lock:
            return (
                json.dumps(
                    {
                        "ok": True,
                        "requests": self.requests,
                        "by_route": dict(self.by_route),
                        "unknown_paths": self.unknown_paths,
                        "cms_missing_etag": 0,
                    }
                )
                + "\n"
            ).encode()
