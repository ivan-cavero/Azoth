# reverse/tools

Static analysis CLIs for the New World client. Prefer:

```text
python ef.py re list
python ef.py re <workflow> …
```

Layout is by kind (`corpus/`, `pe/`, `type/`, `pak/`, `wire/`, `eac/`, `ops/`).
Shared helpers live in `common.py`. Workflows are declared in `catalog.json`.

Do not commit build output; write under `reverse/builds/<sha256>/`.
