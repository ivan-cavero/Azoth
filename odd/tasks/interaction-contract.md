# Interaction contract — what the client sends per game surface

Feature: name, per player-facing surface (NPC dialogue, inventory, equip/unequip,
weapon swap, abilities, skill and attribute points, gathering, crafting, trading
post), the messages the stock client sends and the state it expects back, so a
server can be written against names instead of captures.

Client build: 1.460.6033.6024067, SHA-256
`30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.

## Specs

- **S1** — the surfaces to cover, verbatim:
  "interactuar con npcs, abrir dialogos, arir inventairo equipar armas del
  invventario, cambia rarma, pegar usar habilidades, asignar habilidade ssubir
  puntos de skill, de personaje, equipar armadura desequipar, recolectar
  materiales fabricarlos, usar la subasta"
- **S2** — the goal, verbatim:
  "aun que sea una replay y n vaya lo ideal es conseguir deocmpilar y entener
  todo eso para cuando tegamos el server saber que espera el client del server
  que envia por que etc"
- **S3** — repo evidence rule, quoted from `research/atlas/meanings.md`:
  "Evidence words: **measured** (seen on a live client or capture), **partial**
  (we know the role, not the fields), **unknown** (bytes we cannot name)."
  Every row this feature adds carries one of those three words and the build.
- **S4** — repo rule, quoted from `docs/PLAN.md`: "Do not create `server/`" and
  "The client official es el contrato" — no Rust in this feature, no datagram
  sent for a message whose fields are not named.

## Tasks

| ID | Spec | What | Route | Commit |
| --- | --- | --- | --- | --- |
| T1 | S1, S2 | Extract the client's own input contract from the PAK: key -> action name -> actionlist action, for the S1 surfaces. Artifact `research/derived/input-contract.json`, tool `reverse/tools/pak/input-contract.py`, self-test. | inline | not committed (repo rule: commit only on request) |
| T2 | S1, S2 | Register the type-level per-window instrument as `python ef.py re segment-types`, add a tail `--offset` so a 600 MB live log is not re-read, add `--check`. | inline | idem |
| T3 | S1 | Add an `interact` plan to `scripts/session/capture-segments.py` covering the S1 surfaces with the measured keys from T1. | inline | idem |
| T4 | S1 | One live labelled session against the running in-world client; per-window wire-type counts under `research/sessions/<id>/`. | inline (live) | idem |
| T5 | S2, S3 | Write the result into `research/atlas/meanings.md`: per surface, wire types sent, names from the registry, evidence word, what stays unknown. | inline | idem |

## Log

- **L1** — the user's original request, verbatim:
  "prueba lo que necesites interactuar con npcs, abrir dialogos, arir inventairo
  equipar armas del invventario, cambia rarma, pegar usar habilidades, asignar
  habilidade ssubir puntos de skill, de personaje, equipar armadura desequipar,
  recolectar materiales fabricarlos, usar la subasta,etc, etc aun que sea una
  replay y n vaya lo ideal es conseguir deocmpilar y entener todo eso para
  cuando tegamos el server saber que espera el client del server que envia por
  que etc"
- **L2** — "sigue": continue the authorized work without further approval per step.
- **L3** — outcome, measured 2026-10-26. The keys arrive and the UI works (78.22% pixel
  change after `tab`; the inventory renders with items; a gem click opens its tooltip),
  yet opening the inventory, the skills panel, pressing `q`/`r`/`f`, `lshift`, `tilde`,
  numpad `1`/`2`, `e` and `1` sent **zero** typed messages. Only `0x635` and `0x15d` ran.
  Two types moved and both are UI-side: `0xa39 NotifyOpenUiScreen` (4x) and
  `0xf82 RequestSetIsLookingThroughLoadout` (4x, and it fires on panel **close**).
  The positive result is structural: the ALC body is variable-length and tracks UI state,
  not keys — 283 B with the position marker at 91 when idle/combat, 298 B with the marker
  at 94 when inventory or skills is open. The 15-byte growth inserts before the marker and
  shifts everything after it by 3, which is exactly why a naive byte map reported 133
  "differing fields" that were one shifted region. Inventory-open alone is separable
  (`0x04` at from-end offset 54), validated on two windows outside the plan; the skills
  panel has no separating offset at all, so "a panel is open" is not a field.
  Written to `research/atlas/meanings.md` under "The interaction contract".
  Next blocker for decompilation: what the 15 inserted bytes mean — decompile the
  `ActionListComponent` input-stream writer on build `30fe6461…`.
- **L4** — user correction, verbatim: "pero tienes el menu de compañia poder crea runa
  comañia gestionarla invitar a gente, el menu de diario, el menu de montura, para poder
  tenr momutra,s el de personaje, este segur que es server tambien igual que monturas y
  compañia ya que es del personaje, luegpo map tambien al final puedes poner marcas para
  tu party, aciviades, temporada y la tienda, todos son de server..."
- **L5** — the correction was right and the previous conclusion was a non sequitur
  ("no traffic -> local panel"). Fixed by deriving the surface inventory from the client
  and adding an explicit menu -> family table. 12 menus, 564 client->server messages.
  The same log holds the counter-evidence: `RequestBatchCreateGuildInvites` (18:16),
  `RequestExecuteTradingPostTransaction` (19:42), `RequestGetGuilds` (20:52),
  `AttemptTerritoryUnlock` (20:52), `RequestRemoveRaidMember` (20:52). A panel's contract
  is what it sends when the player ACTS inside it; opening it is not acting.
