# Carrier inbound: why the client never consumes our ladder

Feature: find the ENTIRE inbound flow of the private client from the DTLS/Carrier
datagram to the message dispatch, name every step, understand what each step waits for,
and locate why the client **never consumes our ladder records** (`0x65c` self-ident in
particular) against the Rust server while it does against the Python lab. Then fix it and
document it.

Client build: 1.460.6033.6024067, SHA-256 `30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.

## Specs

- **S1** — the mandate, verbatim: "algo estamos enviando mal entonces no? algo no emos
  medido bien o algo no hemos entendido, haz clas cadenas de proebs en vivo que necesites,
  quiero que averigues todo el lfujo que pasa entenderlo dale nombre entender que espera y
  demas no pares hasta sacar que es y como arreglarlo y documentarlo dalre nombre, etc"
- **S2** — naming: every step of the flow gets a name and a one-line "what it waits for".
- **S3** — the fix must make the private 1.460 client consume our ladder against
  `everfall-netd` (rung 15 `WaitingForActorGameConnection` -> `WaitingForSpawnPoint`).
- **S4** — document the flow and the fix (feature doc + `research/atlas/meanings.md` row).

## Tasks

| ID | Spec | What | Route | Evidence |
| --- | --- | --- | --- | --- |
| F1 | S1 | Capture the real enqueue PC (the parse step that pushes a record). | probe | pending |
| F2 | S2 | Decompile the enqueue/parse chain; name each step and its wait. | inline | pending |
| F3 | S1 | Compare the Rust vs Python inbound at each named step (counters). | probe | pending |
| F4 | S3 | Name the send defect in `everfall-netd` and fix it. | worker | pending |
| F5 | S3 | Live re-run: rung 15 crosses against the Rust server. | live | pending |
| F6 | S4 | Document: feature doc + `meanings.md`. | inline | pending |

## Log

- **L1** — user's mandate, verbatim: see S1 above.
- **L2** — starting boundary (from `odd/tasks/1.460-frontier.md` L31-L40): against the Rust
  server the client reaches `WaitingForActorGameConnection` and times out; the `0x65c`
  handler never runs (0 vs 1); the dispatch fallback `FUN_14647c210` never runs (0 vs 1);
  the queue drainer `FUN_146b6e7c0` runs a lot (drains=1678), so inbound records DO flow —
  our `0x65c` record is specifically not dispatched. The byte corpus says our ladder body
  is identical to the reference, so the defect is in the surrounding context (framing,
  channel, sequence, or an unanswered handshake), not the body bytes.

- **L3** — F1 + chequeo decisivo (run v3, `.azoth/logs/run-20261104-enqueue-rust3/`).
  - El watchpoint de encolado (filtro corregido) disparó **una vez** contra nuestro servidor: `pc_rva=0x644b330` (`FUN_14644b330`), con `drains=3423`. Pero esa función resultó ser un **state machine por fases** (`switch(*(int*)(param_1+0x1530))`), no el encolado → el watchpoint sobre el contador de la cola es ruidoso (captura stores a direcciones que coinciden).
  - **El servidor SÍ manda la escalera completa**: `ladder sent` = 17 B (keepalive `SM_CLOCK_SYNC`), 25 B (heartbeat `0x15d`), 89 B ×2 (`0x40a`, `0x1be`), ~12 × 1114 B + 622 B = el **`0x65c` (12.702 B) troceado a 1.100**, 123 B (`0x663`), y el state bundle `0x08` en 1114 B. **No hay truncamiento de envío.**
  - **Flujo nombrado (S2)** hasta ahora: (1) *DTLS transport* (`everfall-net`); (2) *Carrier envelope/records* (server↔client); (3) [cliente] *record decoder* → (4) *message queue* (drenador `FUN_146b6e7c0`; la cola está en `processor+0x50`, contador 64-bit en `queue+0x30`); (5) *dispatch* (tabla hash; fallback `FUN_14647c210`); (6) *handler* `0x65c` = `FUN_146455ec0`; (7) *setter* `FUN_145a88140` → `[carrier+0xA0]=2`.
  - **Frontera abierta**: por qué el record `0x65c` —que el servidor manda y el cliente ACKea a nivel transport— no llega a la cola/dispatch contra el Rust. Siguiente: hookear el *record decoder* (paso 3) para etiquetar el `0x65c` en el parse.

- **L4** — dos hallazgos que reencuadran el problema.
  - **(a) El lab NO manda self-ident post-V3.** `services/world/src/azoth_world/rep.py:66` → `POST_V3_ENABLED = False`; `maybe_send_post_v3` (línea 4950) sólo emite si está activo. El `0x65c` del lab llega por el **replay de la captura**: `.azoth/logs/world.log` muestra `"event": "replay", "seq": 6, "type": "0x65c", "size": 12706, "chunks": 12, "remaining": 101` — o sea el `0x65c` es el **mensaje seq 6 de una secuencia de ~107 capturados**, con el `sequence` del propio capture. Nuestro `everfall-netd` manda el `0x65c` como **4º record de una escalera propia de 22**, con contador propio (`post_v3_message_seq` desde 1).
  - **(b) El framing chunked YA es paritario** y no es la diferencia: referencia `chunk_replay_payload` (`javelin/wire.py:68-87`) corta a 1100 B con countdown, pero `_send_replay_message` (`rep.py:4744`) usa **total** por defecto (`REPLAY_CHUNK_COUNT_TOTAL`), flags `0x25`, **un chunk por datagrama**, gap 4 ms y seq que incrementa por chunk. Nuestro Rust (`ladder.rs:443/472`, `rep.rs:747/773`) hace exactamente lo mismo, y `oracle_differential` lo fija.
  - **Flujo nombrado completo (S2)** — pasos y qué espera cada uno:
    1. *DTLS transport* (`everfall-net`): handshake; entrega bytes.
    2. *Carrier envelope/records*: `[0x80 0x01][seq][records]`; records con canal/flags/seq.
    3. *Record decoder* (cliente; candidato 1.460 `0x146b6ea20`, vecino del drenador `0x146b6e7c0`): lee el **vlq32 de longitud**, deserializa, y **si el unmarshal falla no encola** (loguea por `FUN_146b6c500`).
    4. *Ten-GUID switch*: diez tipos conocidos se manejan inline; **todo lo demás** va al push de la cola (`0x65c` no está entre los diez → debe encolarse).
    5. *Message queue* (`processor+0x50`, contador en `queue+0x30`): encolada por `FUN_146b6bf50` (1.400) — pendiente de VA 1.460.
    6. *Drainer* `FUN_146b6e7c0`: saca items, resuelve handler por tabla hash; miss → fallback `FUN_14647c210`.
    7. *Handler* `0x65c` = `FUN_146455ec0` → *setter* `FUN_145a88140` → `[carrier+0xA0]=2`.
  - **Hipótesis rankeadas para el próximo run** (H2 es la más fuerte):
    - **H2 (contexto/orden)**: el lab reproduce la secuencia capturada completa (~107 mensajes en orden de capture, con sus `sequence`); nosotros mandamos 22 records sintetizados. Algún mensaje previo (registro de actor/PlayerManager) puede ser necesario para que el `0x65c` se despache. **Experimento**: hacer que `everfall-netd` reproduzca el stream capturado en orden de capture con sus `sequence`, en vez de la escalera sintética.
    - **H1 (sequence)**: el cliente descarta por `sequence` esperada; usar el `sequence` del capture (como el lab) en lugar de un contador propio.
    - **H3 (reensamblado)**: si H1/H2 fallan, comparar los 12 datagramas de chunk campo por campo contra los del lab.
  - Corrección de documentación pendiente: `PRIVATE-CLIENT-RUNBOOK.md:160-176` afirma que rung 15 es "a transport job" y que "no `mov dword [reg+0xA0],2` exists" — ambas falsadas por L34/L36.
