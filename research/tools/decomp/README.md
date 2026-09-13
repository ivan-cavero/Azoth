# tools/decomp

Ghidra, parches de la **copia private** del exe (URL de channel, pin DTLS), ingest de `typeindex.json` (7052 UUIDs AZ).

No se ejecuta contra el `NewWorld.exe` de Steam mientras se juegue official. La copia parcheable vive en `private-client/` (gitignored, en el paraguas o aquí).

El loop de “decompilar el juego entero con agentes” es posterior a tener nuestro REP (para ver DTLS en claro). Hasta entonces: strings del exe-como-archivo (`../re/strings.py`) y este directorio como notas.
