"""azoth_world — the Azoth Javelin REP server (world/game server stub).

Entry: python -m azoth_world --port 9000  (RepAddress in the queue ticket).
DTLS needs pyOpenSSL (the one deliberate non-stdlib dependency in this
service — stdlib ssl has no DTLS; documented in services/docs/WORLD.md).
"""

from .rep import serve, run_forever

__all__ = ["serve", "run_forever"]
