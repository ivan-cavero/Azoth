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

## Roadmap público (solo display, NO es el tracker de trabajo)

`public/roadmap.json` es el roadmap visible en la web. La página lo relee cada
60 s: editar ese fichero basta, **sin rebuild**.

Reglas para agentes y humanos:

- **El roadmap NO es la fuente de trabajo.** El trabajo real se planifica y
  registra en `STATUS.md`, `HANDOFF.md` y `docs/ROADMAP.md`, como siempre.
  Este JSON es un espejo público.
- **Cuándo tocarlo:** al cerrar un hito (marcar `done` con evidencia), al
  descubrir algo nuevo que cambie el plan (añadir puntos con su `evidence`),
  o al reordenar prioridades. No como lista de tareas diarias.
- **Cómo:** edita `public/roadmap.json` directamente. Cada punto lleva
  `state` (`done|active|planned|investigating|blocked`), `evidence`
  (obligatorio para `done`: tipo del cliente, mundo del PAK o doc pública) y
  `effort` (`S|M|L|XL`, estimación). Actualiza `updatedAt` y el `progress`
  del grupo. No borres puntos: lo cerrado se marca, no se elimina.
- **Honestidad ante todo:** si algo está sin confirmar, `investigating`.
  Los ETA son estimaciones; lo hecho, hecho con evidencia.

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
