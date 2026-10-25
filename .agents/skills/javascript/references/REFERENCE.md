# JavaScript reference

## Astro

Pages and layouts are `.astro`. Interactive islands are the exception, not the default. Prefer server-rendered HTML for the roadmap and status.

Data files in `platform/web/src/data/` are the content. Components display them. Do not fetch gameplay state from the browser except `live.json`, which the lab refreshes.

`roadmap-v2.ts` is the public roadmap. `gen-roadmap.mjs` writes `public/roadmap.json`. If `gen-roadmap.mjs` mentions `roadmap-full` or `roadmap-v1-inventory`, the docs check fails.

## Style

Match the file. The existing site uses `const`, arrow functions, and template strings. A `for` loop is fine when it is clearer than a chain. `async/await` is fine in the Node scripts under `platform/web/scripts/`.

Do not add runtime type checks that repeat what the data file already guarantees. Validate at the edges: JSON read from disk, query parameters, anything a visitor typed.

## Names

| Kind | Form | Example |
| --- | --- | --- |
| File | kebab-case | `live-panel.astro` |
| Function | camelCase, verb | `formatBuildSha` |
| Constant | SCREAMING_SNAKE | `STATUS_MAX_LINES` |
| Component | PascalCase | `RoadmapGroup` |
| Boolean | is/has/can | `isAgentRunning` |

## npm

From `platform/web`:

```text
npm install
npm run dev
npm run build
```

Lockfile is `package-lock.json`. Commit it when the user asks to commit a dependency change. Do not upgrade Astro or Tailwind as a side effect of another edit.
