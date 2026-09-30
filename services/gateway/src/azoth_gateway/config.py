"""Runtime config (args/env). Login path only — keep it boring and fast."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve()
# src/azoth_gateway/config.py -> gateway root = parents[2] (apps/gateway/)
GATEWAY_ROOT = HERE.parents[2]
# services/gateway/src/azoth_gateway/config.py -> repo root = parents[4]
DEFAULT_SCHEMAS = HERE.parents[4] / "research" / "schemas" / "live"


@dataclass(frozen=True)
class Config:
    host: str = "127.0.0.1"
    port: int = 8080
    schemas: Path = DEFAULT_SCHEMAS
    discovery_dir: Path = GATEWAY_ROOT / "mock_discovery"


def parse_args(argv: list[str] | None = None) -> Config:
    ap = argparse.ArgumentParser(description="Azoth gateway minimo (channel + CMS)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--schemas", type=Path, default=DEFAULT_SCHEMAS)
    ap.add_argument("--discovery-dir", type=Path, default=GATEWAY_ROOT / "mock_discovery")
    ns = ap.parse_args(argv)
    return Config(host=ns.host, port=ns.port, schemas=ns.schemas, discovery_dir=ns.discovery_dir)
