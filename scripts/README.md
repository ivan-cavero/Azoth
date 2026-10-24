# Scripts

Operator and research helpers. **Do not add new tools as a flat pile** — put
them under a kind folder and register them in `catalog.json`.

## Run

```text
python az.py run list                 # catalog by kind
python az.py run <stem> [args]        # e.g. private-run, measure-walk, doctor
python az.py setup | doctor | shot …  # first-class commands (also catalogued)
```

Stems resolve via `scripts/catalog.json`. Prefer `az.py run` over hard-coded
paths in docs and agents.

## Layout

| Folder | Owns |
| --- | --- |
| `toolchain/` | `bootstrap`, `doctor` (clone-anywhere) |
| `check/` | Doc/path CI gates |
| `test/` | Offline e2e stubs |
| `export/` | Capture → fixture exporters for Rust |
| `measure/` | Logs, ACK, walk, inventory grammar, parity checks |
| `patch/` | Disk patches for private client copies |
| `gui/` | Screenshots, keys, OCR, window focus |
| `session/` | Private runs, smokes, multi-client attempts |
| `wire/` | Decode / inject REP helpers |
| `re/` | Descriptor/codec helpers (heavy RE stays in `reverse/tools/`) |
| `ops/` | Caddy CA trust, OpenAPI gen |

## Adding a script

1. Choose a kind folder (or propose a new one in an ADR if none fits).
2. Add `scripts/<kind>/<name>.py` with a module docstring (first line = summary).
3. Register in `catalog.json` under `scripts.<stem>`.
4. Prefer a caller via `az.py` / skill / runbook — no orphan experiments.
5. `python az.py run list` should show it.

Regenerate catalog from disk after bulk moves:

```text
python scripts/toolchain/_reorg_layout.py   # layout map + catalog rewrite
```

## Retention

Keep a helper only while it has a caller, a measured operator use, or unique
reproduction value. Frida probes live under `reverse/probes/`; launcher patches
under `services/launcher/runtime-tools/`.
