# Easy Anti-Cheat EOS y por qué leer memoria ahora es mala idea

New World usa **Easy Anti-Cheat EOS** (Epic Online Services), no el EAC clásico suelto.

IDs de esta instalación (`EasyAntiCheat/Settings.json`):

| Campo | Valor |
| --- | --- |
| productid | `b0855340e2ed491096135339f6fc94b7` |
| sandboxid | `c9882365293e4c2e858eee62c4b181b5` |
| deploymentid | `29e9a08ed0974685b64a6d52b74570a2` |
| executable | `Bin64/NewWorld.exe` |
| bootstrap | `NewWorldLauncher.exe` → `EasyAntiCheat_EOS_Setup.exe install <productid>` |

## Cómo está montado

Tres piezas:

1. **Launcher** — Steam abre `NewWorldLauncher.exe`, que arranca el servicio EAC EOS y luego el juego “protegido”.
2. **Módulo usermode** — una DLL de EAC se carga **dentro** de `NewWorld.exe`. Integrity checks, lista de procesos, módulos, heartbeats al backend de Epic.
3. **Driver kernel** (`EasyAntiCheat_EOS.sys` / familia EAC) — ring 0. Aquí está la protección de memoria.

Documentación oficial de Epic (crash dumpers): un proceso externo **no puede** abrir un handle al juego con derechos de memoria. Si lo hace, el juego se cuelga y EAC lo mata. Eso incluye dumpers “solo lectura”.

## Leer vs escribir

No es “escribir = ban, leer = ok”.

El driver registra `ObRegisterCallbacks` sobre procesos. Cuando *cualquier* programa hace:

```text
OpenProcess(PROCESS_VM_READ,  ..., NewWorld.exe)
OpenProcess(PROCESS_VM_WRITE, ..., NewWorld.exe)
```

el callback del kernel **se dispara igual**. EAC puede:

- quitar `PROCESS_VM_READ` y `PROCESS_VM_WRITE` del handle (la lectura falla)
- marcar la sesión y mandar telemetría al backend
- cerrar el juego

`ReadProcessMemory` es el API de wallhacks, radar y bots. Protegerlo es el trabajo del anti-cheat, no un extra. Cheat Engine en modo “solo mirar” también pisa esto.

Tampoco es stealth:

- Frida / inject / debugger
- drivers “para que no se note”
- mapear memoria física para saltarse el handle

Eso es el catálogo de cheats que EAC está diseñado para cazar. No lo vamos a construir, ni ahora ni “un poquito”.

## Qué sí es seguro *mientras juegas en oficial*

Todo lo que **no abre el proceso del juego con VM_READ**:

| Técnica | Qué aporta al private server |
| --- | --- |
| `Game.log` | Login entero, estados, URLs, REP `ip:puerto`, nombres de RMI |
| pktmon en la NIC | Flujos TCP 443 + UDP, SNI TLS, DTLS hello, tamaños, timing |
| DNS cache / ETW DNS | hostname → IP (CloudFront, API Gateway, Vivox, EAC) |
| netstat por PID | tabla de conexiones sin leer RAM del juego |
| Archivos en disco | PAKs, configs, channel JSON, logs EAC locales |
| Strings / PE del exe **en disco** | URLs embebidas, cipher DTLS, nombres Javelin, imports |

Eso es ingeniería inversa de **protocolo**, que es lo que hay que clonar. Un dump de RAM te da estructuras C++ (offsets de `GameConnection`). Útil, sí. **No es lo que cierra en enero.** Lo que cierra es el tráfico vivo Amazon ↔ cliente.

## Cuándo sí leeremos memoria

Cuando el cliente **ya no hable con Amazon ni con el backend de EAC**:

- servidores oficiales apagados (31 ene 2027), o
- nuestro REP + el juego lanzado **sin** el bootstrap EAC (exe directo, producto EAC dado de baja)

Ahí `ReadProcessMemory` es un depurador sobre *nuestro* proceso local, no una evasión. Lo haremos entonces, con scripts claros, **sin** ocultarnos del kernel.

Hasta esa fecha, el valor por hora invertida es:

1. **Red** (pcap + SNI + DTLS + cola de login)
2. **Game.log** estructurado
3. **Estático del exe** (Ghidra / strings)
4. Memoria — después

## Qué nos hace falta de “runtime” sin RAM

El juego, al correr, ya emite:

- cada transición `Disconnected → … → InGame`
- cada URL HTTPS que pega
- el `RepAddress` que el launcher/gateway le da para el mundo
- el cipher y el hecho de que el socket REP se establece
- los `messageType` de las RMI (`*ComponentClientFacet_*`)

Eso *es* runtime. Sale a disco y a la red. No hace falta entrar en el address space.

Scripts: `tools/re/README.md`.
