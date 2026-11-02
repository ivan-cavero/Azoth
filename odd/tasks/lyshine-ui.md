# LyShine UI extraction + preview engine

Feature: read New World's LyShine UI out of the client PAKs into a neutral IR, then
render it to HTML for preview/edit and write it back to the game, so a website/launcher
and the game share one organized visual source.

Client build: 1.460.6033.6024067, SHA-256
`30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.

## Specs

- **S1** — the target, verbatim: "sacar dle juego ABOLSUTAMENTE TODOS LOS ELEMENTO DE UI,
  pantallas de carga, botones estilos, scrpites, UI, TODO, y crear un figma bien dividio
  y organizado de TODO para poder reusarlo crear webs y el luancher ... todo eh todos los
  estilos botones, texturas, todo, pero de UI y menus y demas eh, no texturas del mundo
  como tal pero si de los botones"
- **S2** — the loop, verbatim: "si por ejemplo toco algo lo podamos volzar dentro del juego
  cambiar estilos de los botones, etc pero ver la preview primero estilarlo etc, puede ser
  figma u otra cosa, puede ser un mtoor custom de UI si quieres"
- **S3** — portability, verbatim: "debemos tener scrpits y demas formas para poder en
  cualquier pc repdocurilo"
- **S4** — the engine, verbatim: "nuestro motor no me refiero al srever, me refiero crear
  un motor de renderizado de lyshine donde convertir a html, editar, exportar, etc, etc"
- **S5** — repo rule, quoted from `docs/LEGAL.md` §Hard rules: "**Do not commit New World
  client assets** (PAKs, audio, textures, shipped binaries, Steam trees)." Extracted UI
  bytes are private (ignored paths); only the tooling is committed.

## Measured facts

- UI lives in `lyshineui/` inside `DataStrm*.pak`: of 56,016 entries — 54,334 `.dds`,
  1,100 `.luac`, 164 `.dynamicuicanvas`, plus `*.loc.xml` localization. Read from the
  existing index `.azoth/cache/pak-index/pakindex.db`.
- Container = AZ ObjectStream. Note: `research/atlas/client-functions.json::uicanvas_binary_layout`.
  Spike 2026-11-01 read `lyshineui/benchmark/fpsscreen.dynamicuicanvas` (1889 -> 7314, method
  15, CRC `8c2ef308`) and confirmed the root class GUID
  `75651658-8663-478D-9090-2432DFCAFA44`.
- **Grammar, measured and round-tripped byte-exact 2026-11-01** (T1; corrects the atlas note):
  stream header is `[u8 0][u32 BE 3]` (**5 bytes**, not the 8 the note recorded). Element:
  `flags u8` -> `[nameCrc u32 BE]` if `0x40` -> `[version u8]` if `0x80` -> `typeId 16 raw bytes` ->
  `[size field if 0x20, width = flags & 7]` -> `value (size bytes) if 0x10`. **Every element is
  closed by its own `flags == 0` (leaves too, because O3DE `CloseElement` runs for every element),
  and the stream ends with one more close tag after the root.** Source: O3DE
  `Code/Framework/AzCore/AzCore/Serialization/ObjectStream.cpp`.

## Tasks

| ID | Spec | What | Route | Commit |
| --- | --- | --- | --- | --- |
| T1 | S4, S5 | `.dynamicuicanvas` reader + IR + byte-exact writer. Tool `reverse/tools/pak/uicanvas.py`, invoked as `ef.py re uicanvas`. Self-test: parse -> re-serialize byte-identical on >=3 canvases. **DONE 2026-11-01**: byte-exact on fpsscreen/fullscreenassert/buildbanner and on banner (45,282 elements) + styleguide (360,929 elements); 7 unit tests + catalog gate green. | inline | not committed (repo rule: commit only on request) |
| T2 | S1 | UI asset classifier over the existing index -> `research/derived/ui-assets.json` (canvas / dds / luac / loc), with size, method and evidence word. **DONE 2026-11-01**: `ef.py re uiassets`, 8 unit tests + catalog gate green, selftest pins 164/1100/54334/56016. | worker (context backstop) | not committed (repo rule) |
| T3 | S2, S4 | IR -> HTML preview renderer (static; no behaviours). **DONE 2026-11-01**: `ef.py re lyshine render` -> self-contained HTML; fpsscreen renders canvas 1920x1080 with 4 positioned rects (`_root`/`FPS`/`Label`/`Text`) + unknown-class/field inventory; 16 unit tests + selftest green. | worker | not committed (repo rule) |
| T4 | S2, S5 | Edit named tokens on the IR + export back to `.dynamicuicanvas` + `pakwrite` a patch pak. **DONE 2026-11-01**: `ef.py re lyshine set`/`patch`; fail-closed on missing/ambiguous/undecodable; verified byte-exactness still holds (newinventory 21 MB / 761k elements) and an alpha edit changes exactly 1 byte. | worker | not committed (repo rule) |
| T5 | S4, S5 | `.dds` -> PNG decoder (stdlib: DDS header + BC1/BC2/BC3/BC4/BC5/BC7 + zlib PNG). **DONE**: `reverse/tools/pak/dds.py` (`ef.py re dds`), 11 unit tests + selftest; the code landed with the UI commit. | inline | `9859626` |
| T6 | S2 | Renderer embeds sprite PNGs into the preview (private/ignored output only). **DONE 2026-11-02**: `sprite_ref_path` / `sprite_entry` / `sprite_data_uri` / `load_sprites`; `render_html(..., sprites=)` adds `background-image` + `data-sprite` only for a RESOLVED path, and `cmd_render` loads sprites from the read-only pak index with a new `--no-sprites` opt-out. 45 tests green (13 RED first); a real render of `arenaentermenu` embeds 106 sprites, `--no-sprites` embeds 0. | worker | not committed (repo rule) |
| T7 | S2 | `.luac` (compiled Lua) reader + disassembler, to read UI behaviours. **DONE 2026-11-02**: `reverse/tools/pak/luac.py` (`ef.py re luac` read/dis/strings/selftest) parses the measured format (2-byte prefix `04 00` + Lua 5.1 LE) into a function tree and decodes all 38 opcodes; 20 unit tests. Whole-install sweep: 1,100 files / 23,603 functions / 1,093,181 instructions, 0 malformed. | worker | not committed (repo rule) |

## Log

- **L1** — original request, verbatim: "Mira una idea que se me ocurre mas guay, molaria
  sacar dle juego ABOLSUTAMENTE TODOS LOS ELEMENTO DE UI, pantallas de carga, botones
  estilos, scrpites, UI, TODO, y crear un figma bien dividio y organizado de TODO para
  poder reusarlo crear webs y el luancher a corde todo lo de new world, pero todo eh todos
  los estilos botones, texturas, todo, pero de UI y menus y demas eh, no texturas del mundo
  como tal pero si de los botones, etc tengo otro agente en paralelo con el server privado"
- **L2** — verbatim: "Molaria entender esos PAKS poder sacar las cosas, poder extraer la
  UI/HUD/UX sabes, y tenerlo en un figma ordenatido y demas, asi si por ejemplo toco algo lo
  podamos volzar dentro del juego cambiar estilos de los botones, etc pero ver la preview
  primero estilarlo etc, puede ser figma u otra cosa, puede ser un mtoor custom de UI si
  quieres, valoralo, al final es como en la decompilacion entender que sacamos por que que
  es cad acosa, etc"
- **L3** — verbatim: "pero debemos tener scrpits y demas formas para poder en cualquier pc
  repdocurilo, igual nuestro motor podria manejar lyshine no?"
- **L4** — verbatim: "nuestro motor no me refiero al srever, me refiero crear un motor de
  renderizado de lyshine donde convertir a html, editar, exportar, etc, etc"
- **L5** — "si" (authorize the T1 spike).
- **L6** — decision/law, 2026-11-01: HTML is a *view*, the IR (mirroring the ObjectStream) is
  the source of truth; edits touch named fields and every other byte is preserved verbatim.
  Feasibility measured: install present, `pak-read` decodes the canvas (CRC match), root GUID
  matches, stream header corrected to 5 bytes.
- **L7** — T1 outcome, measured 2026-11-01. `reverse/tools/pak/uicanvas.py` parses the
  ObjectStream to an IR and re-serializes byte-for-byte identical. Verified: `ef.py re uicanvas
  selftest` OK on 3 canvases; `roundtrip` OK on `banner` (1,292,135 B / 45,282 elements) and
  `_samples/styleguide` (9,920,249 B / 360,929 elements); `read` on `fpsscreen` reports 289
  elements, root `75651658-8663-478D-9090-2432DFCAFA44`, 288 named, 210 with value, depth 11.
  Two grammar facts the atlas note lacked and the spike pinned: every element carries its own
  close tag (leaves included), and the stream has one extra terminator after the root.
  Files: `reverse/tools/pak/uicanvas.py`, `reverse/tools/tests/test_uicanvas.py`,
  `reverse/tools/catalog.json`, `lab/tools.py`. Not committed (repo rule: commit only on request).
- **L8** — T2 outcome, 2026-11-01. `reverse/tools/pak/uiassets.py` (`ef.py re uiassets build`)
  classified the index -> `research/derived/ui-assets.json`: lyshineui 56,016 (canvas 164,
  luac 1,100, dds 54,334, other 418) + 1,467 loc; 8 unit tests + catalog gate green. Parent
  review removed test console noise (a `selftest` FAIL banner printed under a green run) by
  redirecting stdout in the two selftest-shaped tests. **Finding for T3:** the client's
  `az-type-registry.json` already names ~half of `fpsscreen`'s 35 element classes
  (`bool`, `float`, `Vector2`, `Anchors`, `Offsets`, `EntityId`), i.e. the UI layout structs
  are identifiable; the remaining classes need the public O3DE LyShine class UUIDs (same
  approach as the container format). Not committed (repo rule).
- **L9** — T3 outcome, 2026-11-01. Decoding solved: canvas = a tree of `AZ::Entity`, each
  carrying LyShine components named from the public O3DE LyShine namespace UUIDs
  (`research/derived/lyshine-classes.json`), and every element's `name_crc` is
  `CRC32(lowercase(field))` (`bf396750`=id, `35dd939b`=anchors, `9d841715`=offsets,
  `665648e9`=color, `3b8ba7c7`=text, `e670990a`=fontsize, ...). `reverse/tools/pak/lyshine.py`
  (`ef.py re lyshine render`) names classes+fields, decodes the typed leaves, resolves the
  entity hierarchy, computes rects from anchors/offsets/scale-about-pivot, and writes one
  self-contained HTML (no game assets). Measured on fpsscreen: canvas 1920x1080; `_root`
  (910,490,100,100), `FPS` (801,490,209,101) anchored top-right, `Label`/`Text` nested;
  228/289 elements named-class, 61 unknown (18 ids) shown as a dashed inventory, never
  invented. 16 unit tests + catalog gate green; parent review added the geometry oracle
  check. **Process gap (honest):** the worker authored tests with the implementation and did
  NOT record an isolated RED. Not committed (repo rule).
- **L10** — T4 outcome, 2026-11-01. `uicanvas` now recomputes the leaf size encoding from the
  actual value length (inline <8, else EXTRA size field width 1/2/4), so `serialize` re-encodes a
  length-changing edit while an unedited canvas stays byte-exact. `ef.py re lyshine set` edits a
  named field (float/Vector2/bool/string/Color) resolved by `CRC32(lowercase)` + class, fail-closed
  on missing/ambiguous/undecodable (nonzero exit, no partial write); `ef.py re lyshine patch`
  writes a one-entry method-8 patch pak and re-reads it with `pakread`. Verified: RED recorded
  first (uicanvas 4 errors, lyshine 14 errors); 11 + 31 unit tests + catalog gate green;
  byte-exactness preserved on `newinventory` (21,227,583 B / 761,295 elements); parent re-ran an
  `alpha=0.5` edit and confirmed EXACTLY one byte changed (offset 3851: 00 -> 3f). The in-game load
  step (copy to `<install>/Assets/` + first `PaksList.lst` line) is human-owned and NOT run; the
  install was never touched. Not committed (repo rule).
- **L11** — T5 outcome and the move to this branch, 2026-11-02. T5 (`.dds` -> PNG, stdlib) shipped
  inside the same UI change: `reverse/tools/pak/dds.py` (BC1/2/3/4/5/7 + RGBA8/BGRA8, PNG written
  with `struct`+`zlib`), 11 unit tests + `ef.py re dds selftest`. The whole UI feature was written
  in a parallel session on `feat/lyshine-ui-pipeline` (`aab624c`, pushed) and is now CHERRY-PICKED
  onto `refactor/knowledge-os` as `9859626` at the owner's instruction ("traelo todo aqui y hazlo
  en esta"); T1-T5 therefore live in this branch's history now. Its own test table above is stale
  for T5 (it said pending while the code was already in that commit).
- **L12** — T6 measurement, 2026-11-02. The sprite reference was measured on the real canvases
  (client 1.460.6033.6024067) rather than guessed. A `LyShine::UiImageComponent` stores its sprite
  in a named-blob leaf (CRC `0x8df2fdbe`, no seed entry): 16B asset GUID, 16B zeros, 16B constant
  sprite-type GUID `59d5e20b34db4d8eb867d33cc2556355`, then a u64 BIG-ENDIAN path length and the
  UTF-8 path (e.g. `lyshineui/images/icons/misc/dropdownarrowwhite.dds`); parsing all 164 canvases
  read 58,178 blobs, 0 malformed, 1,754 distinct paths. A `LyShine::UiImageSequenceComponent`
  stores a frame FOLDER in a plain string leaf (CRC `0xcee077ed`), e.g.
  `lyshineui/images/slices/button/blue_loop` -> `.../blue_00.dds`. Resolution is through the pak
  index: exact path, else the folder's first frame by `ORDER BY path`. The renderer embeds a PNG
  data URI only into the private/ignored output (`.azoth/tmp/lyshine/`), never into the repo (S5).
- **L13** — T6 outcome and verification, 2026-11-02. Implementation in `reverse/tools/pak/lyshine.py`:
  `sprite_ref_path` (blob -> path), `_entity_sprite` (image or sequence component -> path),
  `sprite_entry` (pak-index lookup; LIKE prefix properly escaped with `ESCAPE '\'`),
  `sprite_data_uri` (`.png` passthrough, else `dds.decode` + `dds.png_bytes`), `load_sprites`
  (path -> data URI, skipping anything unresolved), and `render_html(..., sprites=)` which emits
  `background-image:url(<uri>)` + `data-sprite` ONLY for a resolved path. Writer self-verification
  (the assess plan adds no separate verifier because RDD is off and no Task Size high-risk item is
  escalated): `test_lyshine.py` 45/45 green after a recorded RED of 13 errors, `test_uicanvas` 11,
  `test_uiassets` 8, `test_dds` 11 + selftest, catalog gate green. End to end on the real install: a
  render of `lyshineui/arena/arenaentermenu.dynamicuicanvas` embeds **106** sprite data URIs and
  `--no-sprites` embeds **0**; the output lands under the gitignored `.azoth/tmp/`. One deviation
  from the handoff: `pakread.read_entry` returns `(bytes, meta)`, so the CLI path passes a bytes
  adapter. **Risk: none** (no stored data is rewritten and no shared contract changes; the model
  only gains an additive `sprite` key and the sprite bytes are private output).
- **L14** — T7 outcome and verification, 2026-11-02. The `.luac` payloads are Lua 5.1 LITTLE-ENDIAN
  dumps behind a constant 2-byte prefix `04 00` (confirmed by parsing all 1,100 to exact EOF, 0
  malformed). The deliverable is a DISASSEMBLER, not a decompiler to source: `reverse/tools/pak/luac.py`
  (`ef.py re luac read|dis|strings|selftest`) parses a function tree (source, lines, params, nups,
  maxstack, code, constants, protos, upvalues, debug), decodes every instruction against the public
  Lua 5.1 `lopcodes.h` (iABC/iABx/iAsBx, ISK/INDEXK), and prints a listing that resolves
  constant/global/upvalue/proto names (`GETGLOBAL R0 := Gbl[RequireScript]`, `LOADK R1 := K1("…")`,
  `TAILCALL return R0(R1..R1)`). Registered in `reverse/tools/catalog.json` + `lab/tools.py`.
  Writer self-verification (RDD off, no Task Size high-risk item escalated): `test_luac` 20/20 green
  after a recorded RED, the four sibling suites + the catalog import gate green; real `read`/`dis` on
  `basescreen.luac` and `socialmenu.luac`; a full-install sweep parsed 1,100 files / 23,603 functions /
  1,093,181 instructions with 0 malformed; a missing entry fails closed (rc=1, no traceback).
  **Risk: none** (a new tool only; no shared contract changes, no data rewritten, game bytes never
  enter the repo). Note the native assess could not bind this candidate because the two new files are
  untracked until committed (`untracked files require an explicit declaration`); its plan still adds
  no separate verifier.
