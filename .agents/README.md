# Agent skills

`AGENTS.md` is the session file. It stays short. A skill is the rulebook for one domain. Load the skill before editing that domain. Load `reference.md` in the same folder only when the task needs the detail.

## Workflow

| Skill | When |
| --- | --- |
| `everfall-next` | Where the project is going |
| `everfall-meaning` | A row in `research/atlas/meanings.md` |
| `everfall-decompile` | One client function |
| `everfall-live` | One measured private-client session |
| `everfall-server` | The day Rust gameplay code is allowed |

## Domain

| Skill | When |
| --- | --- |
| `rust` | Any Rust |
| `python` | Lab, `ef.py`, scripts |
| `javascript` | `platform/web` |
| `protocols` | Bytes, messages, DTLS, captures |
| `security` | Secrets, auth, EAC, admin, supply chain |
| `naming` | New names |

`azoth-*` skill folders are retired. Do not extend them.

## How a skill is written

`SKILL.md` is the procedure. Longer checklists live in `references/REFERENCE.md` in the same skill folder, one level down. Cursor only shows the description until the skill is relevant, and `paths` in the frontmatter limits Rust, Python, JavaScript, and protocol skills to the files they govern.
