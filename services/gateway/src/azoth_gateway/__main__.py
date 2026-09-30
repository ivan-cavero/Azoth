"""python -m azoth_gateway [--host 127.0.0.1] [--port 8080] (run with src/ on PYTHONPATH)."""

from __future__ import annotations

from .app import run_forever
from .config import parse_args


def main() -> None:
    run_forever(parse_args())


if __name__ == "__main__":
    main()
