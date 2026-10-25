# Python reference

## Package

`ef.py` parses nothing itself. `lab/cli.py` switches on the first argument and calls a function.

| Module | Owns |
| --- | --- |
| `lab/paths.py` | Checkout paths |
| `lab/env.py` | Child environment. No Rust toolchain PATH |
| `lab/catalog.py` | `scripts/catalog.json` and RE workflows |
| `lab/procs.py` | Pid files, start, stop |
| `lab/services.py` | Gateway, world, Caddy, static site, `dev` |
| `lab/game.py` | Private client |
| `lab/host.py` | `deploy/switch-mode.ps1` |
| `lab/migrate.py` | One-time AppData move |
| `lab/tools.py` | `run`, `probe`, `re`, the cargo refusal |

A new command is a function in the module that owns that job, plus a branch in `lab/cli.py`. It is not more code in `ef.py`.

## Style in this repo

Functions and modules, not a class per concept. Mutation of dicts and lists is normal for process records and packet buffers.

Prefer early returns over nested conditionals. A helper used once stays inline unless the block has a side effect that deserves a name.

Exceptions: catch `OSError` at the process edge and print a line the operator can act on. Do not swallow it.

Subprocess environment goes through `local_env` so temp files stay in `.azoth/tmp`.

## Scripts

Register the stem in `scripts/catalog.json`. The first line of the module docstring is the summary `python ef.py run list` can show. Do not leave a second copy of a script at `scripts/*.py` outside a kind folder.

Helpers that used to write `server/` must exit if `server/Cargo.toml` is absent. They must not recreate that tree.

## Tests

`python ef.py gateway test` and `python ef.py world test`. A new test locks a behavior you can describe. A test that only compares a captured blob does not close a meaning row.
