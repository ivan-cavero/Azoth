# Captura de datos — qué, por qué, y qué no tocar

Los servidores oficiales cierran el 31 de enero de 2027. Cada sesión que juegues **ahora** es protocolo que luego no existe. Este kit graba esa sesión sin meter las manos en el proceso del juego.

## Lo que NO vamos a hacer (baneo)

Easy Anti-Cheat EOS está activo en el cliente live. Estas cosas son exactamente lo que EAC detecta y reporta a Amazon/Epic:

| Acción | Riesgo |
| --- | --- |
| `ReadProcessMemory` / dump de RAM | Ban |
| Frida, DLL inject, hook de API | Ban |
| Debugger (x64dbg, Cheat Engine, ReClass) sobre `NewWorld.exe` | Ban |
| Parchear el exe en disco y lanzarlo | Ban / EAC no arranca |
| Drivers para “ocultarte” de EAC | Ban + peor |

No hay modo “undetected” fiable contra EAC mientras el cliente hable con Amazon. No lo vamos a construir. No hace falta para un emulador: el cliente **ya escribe** el mapa de login en `Game.log`, y el tráfico de red se ve en la NIC.

Cuando tengamos **nuestro** REP y el cliente ya no hable con Amazon, la ingeniería inversa del protocolo se hace contra paquetes nuestros y análisis estático del exe (archivo). Eso es otro momento.

## Lo que SÍ captura el kit (pasivo)

| Fuente | Qué sale | ¿EAC lo ve? |
| --- | --- | --- |
| `%LOCALAPPDATA%\AGS\New World\Game.log` | Toda la máquina de estados, URLs, Omni, REP IP:puerto, spawn | No. Lo escribe el propio juego |
| `pktmon` en la NIC (`--comp nics`) | UDP/DTLS cifrado + TCP 443. IPs, puertos, tamaños, timing del handshake | No inyecta en el proceso. Es el monitor de paquetes de Windows |
| `netstat -ano` filtrado por PID | Conexiones del launcher/cliente | Consulta al OS, no abre el proceso con `VM_READ` |
| DNS cache | Resolución CloudFront / API Gateway / Vivox | Igual |
| Archivos en disco | channel config, EAC logs locales, settings, Steam `runprocess_log` | Lectura de archivos |
| Strings de `NewWorld.exe` **como archivo** | URLs y nombres Javelin embebidos | No es memoria del proceso |

El UDP del REP va cifrado (DTLS). El pcap **no** te da el protocolo en claro. Te da:

- la IP y el puerto reales del REP (cambia por sesión)
- cuántos paquetes, de qué tamaño, en qué orden
- cuánto tarda el handshake

El **claro** de auth está en `Game.log` (el cliente lo imprime). Eso vale más que un MITM de HTTPS contra Amazon, y no rompe el login oficial.

## Cómo usarlo

1. Cierra overlays raros (no Steam overlay; ese ya está). No tengas Cheat Engine abierto “por si acaso”.
2. **Doble clic** en `tools\capture\Start-NwCapture.bat` y acepta el UAC (pktmon necesita admin).
3. Se abren dos ventanas: orquestador (pulsa **Q** para terminar) y watcher (eventos en vivo).
4. Abre Steam, lanza New World **como siempre**, loguéate, entra al mundo.
5. Juega **5–15 minutos** de verdad: anda, pega a un mob, abre inventario, cambia de arma, habla si puedes. Cuanto más sistemas toques, más nombres de RMI salen en el log.
6. Vuelve al orquestador, pulsa **Q**. Espera a `REPORT.md`.

Salida:

```
sessions/YYYYMMDD_HHMMSS/
  REPORT.md                      ← empieza aqui
  logs/Game.log.raw              ← NO lo subas (tickets Steam)
  logs/Game.log.redacted
  logs/events.jsonl              ← secuencia estructurada
  network/pktmon.pcapng
  network/connections.jsonl
  extracted/identities.json      ← player, world, REP
  extracted/urls.txt
  extracted/state_machine.jsonl
  static/                        ← strings del exe (si no usaste -SkipStatic)
```

## Qué grabar en cada sesión (prioridad)

Mientras Amazon viva, el orden de valor es:

1. **Login completo hasta InGame** (ya lo hiciste una vez; repetirlo con el kit da pcap + eventos alineados).
2. **Movimiento + un combate** (RMI de `ActorMover`, abilities).
3. **Inventario / storage** (hoy el log ya disparó `GlobalStorageComponentClientFacet_*`).
4. **Cambio de territorio / fast travel**.
5. **Entrar a una expedición** (otro `level.pak`, otro REP o instance).
6. **War / crafting / trading** — cuando 1–5 estén en caja.

No hace falta 4 horas. Hace falta **cobertura de sistemas**, sesiones cortas y bien etiquetadas.

Renombra la carpeta si quieres: `sessions/20260906_ingame_combate`.

## Flags

```text
Start-NwCapture.ps1
  -SkipPktmon     solo logs (si no puedes admin)
  -SkipStatic     no extrae strings del exe (ahorra CPU al arrancar)
  -HashExe        SHA-256 de NewWorld.exe (lento, ~179 MB)
  -SessionName X  nombre fijo de carpeta
```

## Después de la captura

`REPORT.md` tiene un checklist: Steam → Omni → Campfire → cola → REP → V3 → InGame. Si falta una casilla, esa sesión no sirve para esa capa.

Con una sesión InGame buena se puede empezar el gateway HTTP (Fase 1) sin tocar memoria ni el proyecto de la comunidad: los schemas salen de `events.jsonl` y de tu `Game.log`.
