# Azoth landing

Landing pública del proyecto: estado en vivo, timeline de entregables, roadmap,
stack, verificación y ritmo. Generada con Astro + Tailwind v4, estilo Linear
(midnight, acento acid-lime).

## Comandos

```bash
npm install
npm run dev      # desarrollo en localhost:4321
npm run build    # genera dist/
npm run preview  # sirve dist/
```

## Actualizar datos

Todo el contenido editble vive en `src/data/project.ts`:

- `ganttTasks` — timeline de entregables (fechas ISO, estado, progreso).
- `roadmap` — fases y puntos con estado real.
- `stack` — lenguajes ahora / transición / futuro.
- `docs` — qué está verificado, parcial o abierto.
- `weeklyCommits`, `stats`, `versions`, `helpOptions`.

Tras editar, `npm run build`.

## Estado en vivo

`public/live.json` alimenta el badge del hero y el panel "¿Qué está corriendo
ahora?". La página lo relee cada 30 s, así que se puede regenerar sin rebuild:

```bash
python site/scripts/update_live.py   # desde la raíz del repo
```

Lee los PIDs de `.azoth/state/` y comprueba con `tasklist` si cada servicio
(caddy, gateway, world) sigue vivo.

## Public roadmap (display only; not the work tracker)

`src/data/roadmap-full.ts` is the canonical source. Regenerate
`public/roadmap.json` with `node site/scripts/gen-roadmap.mjs`; the landing page
re-fetches that JSON every 60 seconds, so no rebuild is needed for data-only
updates.

The long-term public site, **roadmap v2** (replace replay-era groups with eras
E0–E5), work-graph vs public display, agentic stack (Pi/Gentle/Orca/T3), and
open-GitHub automation are specified in
[`docs/PLAN-master-platform.md`](../docs/PLAN-master-platform.md) §14 / §14A /
§14B. Agent monitoring dashboards are ops-private, never mixed into this
landing’s public JSON. Until v2 ships, `roadmap-full.ts` remains the served
v1 source. Draft eras live in `src/data/roadmap-v2.ts` (not wired to
`gen-roadmap.mjs` yet).

- Keep planning and current status in root `STATUS.md` and
  `docs/ROADMAP.md` / `docs/PLAN-master-platform.md`. This JSON is the public
  display copy.
- Update the roadmap when a milestone closes, evidence changes, a new finding
  changes the plan, or sequencing changes. Do not use it as a daily task list.
- Each group must have a visible, informative `goal`; every item must have a
  useful `detail`, a state, evidence basis, and effort estimate. Keep completed
  work separate from partial progress.
- A `done` item needs durable source evidence and one authentic capture that
  demonstrates that specific result. Store only curated, public-safe captures
  under `public/evidence/`, with a precise caption. Never reuse an unrelated
  image or present a planned feature as implemented.
- For planned, active, or investigating work without a result capture, show
  that the capture is pending. Add it when the item's acceptance condition is
  met; do not fill the gap with concept art or an unrelated game screenshot.
- Do not delete roadmap items. If a claim is uncertain, keep it
  `investigating`; dates are estimates, and completion requires evidence.

Servir la web localmente (puerto propio, no el 8080 del gateway):

```bash
python az.py web start     # http://127.0.0.1:8090  (AZOTH_WEB_PORT para otro)
python az.py web status
python az.py web stop
```

Ojo: `public/roadmap.json` y `public/live.json` se copian a `dist/` en el
build; si editas los JSON sin rebuild, servir `dist/` mostrará la copia
antigua. `python az.py web` sirve `dist/` — tras editar los JSON, copia:

```bash
cp site/public/roadmap.json site/dist/roadmap.json
cp site/public/live.json site/dist/live.json
```
