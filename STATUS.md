# Azoth — live status

Last updated: 2026-10-04 ~14:30 local (12:30 UTC). Diagnóstico en
`research/derived/symbols.json`: `capture_redactions_block_player_state_20261004`,
`client_self_reconnect_kills_context_20261004`, `local_player_has_no_physics_20261004`.

## El bloqueo (caden completa, medida)

El cliente entra al mundo, espera un mensaje con la identidad correcta, no llega, y a los ~3 s **el
mismo** arranca una reconexión. En la reconexión el `ClientContext` nunca se recrea, así que el
cliente descarta **todo** el estado del mundo (`skipping ReceiveStateBundle ... clientContext ==
nullptr`, cientos de líneas). Sin ese estado, el jugador local **no tiene componentes de física**, y
por eso WASD no mueve nada y el cable sube hasta cortarse.

**Por qué no llega:** el mensaje que el cliente espera es el state bundle `0x08`. En el capture son
los 5 más grandes (`seq 0x25/0x2a/0x2b/0x2e/0x2f`, 46 407–46 423 bytes cada uno). Cada uno tiene
**453 redacciones de 36 bytes** (el UUID del jugador/cuenta del capture, puesto a `XX`), más
**9 420 bytes de huecos por mensaje**. El replay rellena sólo las 6 ranuras del allowlist
`REPLAY_IDENTITY_TARGETS` y `AZOTH_REPLAY_LOCAL_PLAYER_UUID`; los otros **~24 800 bytes de huecos
quedan en cero**.

Con esos huecos, el cliente no puede reconstruir los componentes del jugador (incluido el rigid
body/character controller), y sin ellos la identidad que la puerta compara no coincide.

**Y de fondo:** el capture es de build **1.365** y el cliente es **1.400.6031**. Incluso sin
redacciones, el estado sería el del personaje del capture, no el del jugador de Azoth.

**Conclusión de arquitectura:** el cliente no se estabiliza retransmitiendo el capture. El servidor
tiene que implementar el protocolo de replicación real: crear la entidad del jugador con sus
componentes (incluido el rigid body/character controller), mandarle el estado con las identidades
correctas, y responder al input. Eso es lo que hace el servidor real para miles de jugadores
sincronizados.

## Lo que sí funciona (medido)

- El gateway, el mundo (UDP :9000) y el ClienteContext en la **primera** sesión.
- El cliente entra al mundo, renderiza Monarch's Bluffs, manda el estado 0x635 con el actor del
  jugador, y responde al heartbeat.
- El input **llega** al cliente (GetRawInputData con makeCode 0x11 / VKey 0x57), y el mouse mueve la
  cámara.
- Las teclas UI funcionan (Escape/I/M abren menús).

## Herramientas nuevas

- `focus-window.py` (fuerza y **verifica** el foco; usar en vez de `SetForegroundWindow` a pelo).
- `hold-key.py`, `bmp-diff.py`, `frida-activity-timer.py`.

## Próximo paso (realista)

Implementar el protocolo de replicación de Javelin/GridMate para la entidad del jugador:
1. Decodificar el state bundle `0x08` del capture (Oodle) para entender el formato exacto de los
   fragmentos y qué campos identifican al jugador.
2. Construir los bundles propios con las identidades de Azoth y el rigid body del jugador.
3. Mandarlos con el seq/identidad correctos.

No reactivar el stream 0x08 ni el attach de transforms.

---

## Diagnóstico final (2026-10-04, íntegro y verificado)

**El cliente se desconecta por `transportError 4` del ClientSDK anticheat ~50 s después del spawn, en TODAS las sesiones, siempre.** El stub EOS está vivo (el log lo dice), el watchdog está parcheado (b001→b000), y el servidor no cierra la DTLS. Pero el ClientSDK espera que el servidor le mande mensajes anticheat por el canal REP que el servidor real manda; nuestro servidor no los implementa, así que después de un timeout el SDK reporta `@mm_csdkerr_disconnect (4)` y el cliente corta la conexión REP.

**Consecuencia en cadena (medida, no teoría):**
1. El cliente se desconecta → reconecta.
2. En la reconexión, `clientContext->Initialize` **nunca** corre de nuevo (el gate `FUN_14643e7b0` exige que la identidad del mensaje coincida con `port[+0x80]`, y el estado del puerto ya cambió).
3. Sin ClientContext, el cliente descarta **TODO** el estado del mundo (cientos de `skipping ReceiveStateBundle ... clientContext == nullptr`).
4. Sin ese estado, el jugador local no recibe sus componentes de física (`GameRigidBodyComponent`, `CharacterPhysicsComponent`, `CharacterControllerComponent`).
5. Sin física, **WASD no mueve nada** — el input llega (verificado con GetRawInputData) pero no hay cuerpo que mover.
6. El cable sube hasta el rojo porque el ClientSDK no reporta heartbeat al servidor.

**El capture 1.365 tiene 453 redacciones de 36 bytes por bundle 0x08** (los 5 bundles más grandes son 46 407–46 423 bytes cada uno). El replay rellena solo 6 ranuras del allowlist; los otros ~24 800 bytes de huecos quedan en cero. Con esos huecos el cliente no puede reconstruir los componentes del jugador.

**Y de fondo: el capture es de build 1.365, el cliente es 1.400.6031.** Incluso sin redacciones, el estado sería del personaje del capture, no del jugador de Azoth.

## Qué se necesita de verdad

El servidor tiene que implementar el protocolo de replicación real de Javelin/GridMate:
1. Crear la entidad del jugador con sus componentes (incluido el rigid body/character controller).
2. Mandar el estado con las identidades correctas.
3. Implementar el canal anticheat que el ClientSDK espera.
4. Responder al input del cliente con posiciones autoritativas.

Eso es lo que hace el servidor real para miles de jugadores sincronizados. Es un proyecto de ingeniería inversa sustancial, no un parche.

