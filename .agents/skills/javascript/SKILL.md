---
name: javascript
description: >-
  JavaScript and Astro rules for the Everfall public site in platform/web.
  Use when editing the landing page, Astro components, Tailwind, or npm scripts.
  Mutation and async/await are allowed here.
paths:
  - "platform/web/**/*.astro"
  - "platform/web/**/*.js"
  - "platform/web/**/*.mjs"
  - "platform/web/**/*.ts"
  - "platform/web/**/*.css"
---

# JavaScript

The site is `platform/web` (Astro, Tailwind). npm only. The long list is [reference.md](references/REFERENCE.md).

This is not an immutable-JavaScript codebase. Game servers mutate, and the site may mutate local objects while building a view. Do not import a ban on `let`, loops, or `async/await` from another project.

## Always

- `const` until a binding must change. Then `let`. Never `var`.
- Descriptive names. No `x`, `res`, `tmp`, `data` when a real noun exists.
- Module files in kebab-case. Functions in camelCase, verb first.
- The smallest change that keeps the page honest. Do not render `platform/web/src/data/archive/roadmap-v1-inventory.ts`.
- Generated facts come from `platform/web/scripts/build_facts.py`. Do not hand-edit `repo-facts.gen.json`.

## Never

- A new package manager, or a dependency the user did not accept.
- `any` in TypeScript.
- A claim on the page that the Rust server is running, or that players can see each other, unless `STATUS.md` says that.
- Secrets in client-side code. The site is static.

## Before you finish

- [ ] `npm run build` in `platform/web` if the change affects render
- [ ] Copy still says Everfall, and the in-game resource is still Azoth where the text means the resource
- [ ] GitHub Pages base path stays the repository name until the repo is renamed
