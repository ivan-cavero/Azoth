---
name: python
description: >-
  Python rules for the Everfall lab, ef.py, and scripts/. Use when editing
  the command surface, gateway, world server, launcher, or a helper script.
paths:
  - "ef.py"
  - "lab/**/*.py"
  - "scripts/**/*.py"
  - "services/**/*.py"
---

# Python

The lab is the running server. Rust is not. Load `protocols` when a change sends or parses a client message, and `security` when it touches tickets, certs, or the private client.

Detail and the `ef.py` map: [reference.md](references/REFERENCE.md).

## Shape

- `python ef.py` is the only command. New operator behavior is a subcommand that calls a module, not another 80-line branch pasted into `ef.py`.
- Helpers live in `scripts/<kind>/` and `scripts/catalog.json`. A file under `scripts/` that is not in the catalog fails CI.
- Gateway code stays on the standard library. The world may use pyOpenSSL for DTLS.
- Type hints on new functions. Match the file's quote and import style.

## ef.py

`ef.py` is the console script. The work is in `lab/`. Do not add a command to `ef.py`.

`local_env` does not rewrite PATH for the Rust/MinGW toolchain. The Python world links DTLS through pyOpenSSL. `scripts/toolchain/rust_openssl_env.py` stays on disk for the day a crate exists, and nothing in the lab calls it.

## Lab behavior

A captured blob may stay only while `research/atlas/meanings.md` calls it unknown. Say that in the change. Do not add a permanent game rule that exists only in Python.

## Before you finish

- [ ] `python ef.py gateway test` or `python ef.py world test` when that service changed
- [ ] No new machine-specific home path
- [ ] The script catalog check still passes if you added a helper
