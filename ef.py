#!/usr/bin/env python3
"""One command surface for the local Everfall lab.

  python ef.py setup [--core|--re|--all|--purge]  # local toolchain (core = default)
  python ef.py doctor             # checklist: Python and Caddy
  python ef.py test e2e entry     # offline entry stub
  python ef.py migrate            # move existing AppData state into this checkout
  python ef.py dev                # gateway, world and Caddy in the background

  python ef.py dev stop           # stop the server stack
  python ef.py game               # launch the private client without a console
  python ef.py game restart       # cleanly replace the private client
  python ef.py status             # inspect managed processes
  python ef.py stop               # stop all Everfall-managed processes
  python ef.py gateway test       # run gateway checks
  python ef.py world test         # run world checks
  python ef.py mode status        # show official/private routing
  python ef.py re list            # list maintained RE workflows
  python ef.py re decompile ...   # focused native analysis
  python ef.py re corpus ...      # full build-specific pseudocode pass
  python ef.py re campaign ...    # incremental phase-scoped decompilation
  python ef.py probe <name>       # run a client reverse-engineering probe
  python ef.py run list|<stem> …  # helpers under scripts/<kind>/ (catalog.json)
  python ef.py cargo <args…>      # refused until a meaning card allows Rust

Runtime files, PIDs and logs live under .azoth/ (gitignored). See
docs/runbooks/contributor-loop.md and scripts/README.md.
"""

from __future__ import annotations

import sys

from lab.cli import main

if __name__ == "__main__":
    raise SystemExit(main(__doc__))
