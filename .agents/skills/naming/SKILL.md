---
name: naming
description: >-
  Everfall naming rules for files, functions, crates, and protocol ids.
  Use when adding a file, type, command, crate, or message name.
---

# Naming

One word for one thing. The project is Everfall. Azoth is the in-game resource and the name of the local tool directory `.azoth/`. The command is `python ef.py`. Do not rename the resource. Do not add a command called `az`.

## Forms

| Kind | Form | Example |
| --- | --- | --- |
| Python module, script, Astro file | kebab-case or snake_case to match the folder | `check-docs.py`, `live-panel.astro` |
| Python function | snake_case, verb | `load_registry` |
| Rust function | snake_case, verb | `apply_move` |
| Rust type, Astro component | PascalCase | `TerritoryId` |
| Rust crate | `everfall-` prefix, kebab | `everfall-sim` |
| Constant | SCREAMING_SNAKE | `CHUNK_PAYLOAD` |
| Boolean | is/has/can | `is_in_game` |
| Protocol id | dotted, from the meanings file | `flow.world-entry.rung.level-info` |

## Protocol names

Name the fact, not the byte width. `level_info` is a name. `bytes_106` is not. If the field is still unknown, its id says unknown and points at the row. Do not invent a gameplay noun to hide a capture.

## Do not

- Prefix new crates or packages with `azoth`.
- Reuse `worldd`, `channeld`, and `regiond` unless the process boundary is the same one documented in `everfall-server`.
- Abbreviate to `msg`, `buf`, `tmp` in new code. `payload` is allowed when the value really is an opaque payload inside the transformer.
