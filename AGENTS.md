# AGENTS.md — Azoth

Reglas duras para agentes que trabajan en este repo.

## Capturas de pantalla: NUNCA leer el PNG crudo

`orca computer get-app-state` devuelve PNGs de ~700KB. Leerlos directo
rompe la request con `413 "request body too large"`. **Antes de todo
`read` sobre una imagen, pasarla por el script:**

```bash
python scripts/shrink-image.py <captura.png>
```

Imprime el path a leer. Si pesa <= 100KB devuelve el mismo path sin
tocarlo; si no, escribe un `.small.jpg` de ~30KB (768px, q55).

Regla: **ninguna imagen entra a `read` sin haber pasado por ese script.**
Si igual da 413, bajar a 640px:

```bash
python scripts/shrink-image.py <captura.png> "" 640
```

Los `.small.jpg` son descartables: no se commitean (ver `.gitignore`).

## Resto

- El estado del proyecto y la frontera actual viven en `STATUS.md`.
- Docs en `docs/` (índice en `docs/INDEX.md`), análisis en `research/`.
- Tests del gateway: `python emulator/apps/gateway/tests/test_gateway.py`.
