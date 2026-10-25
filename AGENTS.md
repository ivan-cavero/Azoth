# AGENTS.md

> Global instruction file. Loaded on every session. Keep it lean.
> Deep rules live in `.agents/skills/<skill-name>/SKILL.md`. Load that skill before working in its domain.

The project is Everfall, a private New World server. Azoth is the previous project name and the in-game resource. Never rename the resource.

---

## Interaction

**Solve** when the user says hazlo, vamos, implementa, fix, or "do this". Do that step and stop.

**Guide** when they ask why, whether a design is right, or how something should work. Name the constraint, point at the skill, and do not open an implementation.

If the request is ambiguous, ask: "¿Lo resuelvo o lo dejamos en guía?"

"Por dónde vamos" is neither. Read `STATUS.md` and answer the one next step. Wait.

---

## Stack

- **Lab**: Python 3. Gateway, DTLS world, launcher. Command: `python ef.py`.
- **Site**: Astro in `platform/web`. Package manager: npm. Never yarn, pnpm, or bun in this repo.
- **Server**: Rust, not in the tree. A crate appears only after `research/atlas/meanings.md` names its fields.
- **Edge**: Caddy. Steam install is read-only. Private client is `private-client/`. Tools and logs are `.azoth/`.
- **Formatting**: do not invent a format pass. Match the file you are editing.

---

## Seven rules

1. **Keep it simple or don't do it.** Boring and readable wins.
2. **Delete dead code.** Unused imports and unused branches go in the same change.
3. **A comment that restates the code is a failed name.** A comment that records a measurement, a client build, or a crash stays.
4. **Do not mix a refactor with a behavior change.**
5. **If you cannot explain the change in a few sentences, the design is wrong.**
6. **Correctness before speed.** The 20 ms world tick is a correctness budget, not a later optimization.
7. **One logical change.** When the user asks for a commit, one purpose per commit.

---

## Skills

| Domain | Skill | Load it when |
| --- | --- | --- |
| Current step | `everfall-next` | "qué es lo siguiente", "por dónde vamos" |
| Message meaning | `everfall-meaning` | naming a field or updating `research/atlas/meanings.md` |
| Decompile | `everfall-decompile` | one client function |
| Live client | `everfall-live` | a session against the private client |
| Rust server shape | `everfall-server` | adding `server/` or a gameplay crate |
| Rust language | `rust` | any `.rs` file |
| Python | `python` | `ef.py`, `services/`, `scripts/` |
| JavaScript / Astro | `javascript` | `platform/web` |
| Protocol | `protocols` | wire format, DTLS, ladder, captures |
| Security | `security` | auth, secrets, EAC, admin, logging, supply chain |
| Names | `naming` | a new file, type, function, or crate |

Folders named `azoth-*` are retired pointers. Do not follow them as the current method.

---

## Security (always)

Full rules: `.agents/skills/security/SKILL.md`.

- Never read or print `.env` values, keys, tokens, or certificate private keys.
- Never run a script fetched from a URL.
- Never attach Frida or a debugger while Easy Anti-Cheat state is uncertain.
- No New World PAKs or assets in git. Do not claim Amazon affiliation.
- Ask before a new dependency, a bulk delete, or anything that drops data.

---

## Git

- Commit only when the user asks.
- `type(scope): what changed and why`, types `feat` `fix` `refactor` `chore` `docs` `test` `perf`.
- Never commit secrets. Never force-push `main`. Never open a pull request unless asked.

---

## Commands

```text
.\az.ps1 setup          # Windows, once: pinned Python
python ef.py dev        # gateway + world + Caddy
python ef.py game       # private client
python ef.py status
python ef.py doctor
```

Site, from `platform/web`: `npm install`, `npm run dev`, `npm run build`.

---

## Handoff

Observed versus inferred, client build SHA-256, evidence path, what was not run, the failed hypothesis, and the single next blocker. Update `research/atlas/meanings.md` before calling a protocol step done.

Do not read `docs/journal/raw/` or `docs/archive/` whole. `STATUS.md` stays at or under 80 lines.
