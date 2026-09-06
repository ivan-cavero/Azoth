# Azoth

Servidor privado de **New World: Aeternum**. Azoth es la esencia del mundo en el juego; aquí es el nombre del proyecto y del mundo.

El cliente que ya posees no se crackea: se le habla en su idioma (modelo TrinityCore). En **private** se lanza **sin Easy Anti-Cheat** y **sin Steam**, con un launcher propio.

Este directorio es el **repo paraguas**. Tres git independientes (submódulos):

| Submódulo | Repo | Qué es |
|---|---|---|
| [`research/`](research/) | [Azoth-Research](https://github.com/ivan-cavero/Azoth-Research) | Captura live, RE, decompilación, schemas JSON |
| [`emulator/`](emulator/) | [Azoth-Emulator](https://github.com/ivan-cavero/Azoth-Emulator) | Gateway HTTPS + world/REP + Postgres |
| [`launcher/`](launcher/) | [Azoth-Launcher](https://github.com/ivan-cavero/Azoth-Launcher) | Updater, cliente parcheado, Play |

Docs de sistema: [`docs/INDEX.md`](docs/INDEX.md) · Arquitectura: [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md) · Nombre: [`docs/NOMBRE.md`](docs/NOMBRE.md)

## Dos perfiles, nunca mezclados

**Official** (grabar Amazon hasta 2027-01-31): Steam → launcher de Amazon → EAC → exe vanilla. Hosts limpio. Kit: `research/tools/capture`.

**Private** (Azoth): nuestro launcher → `Bin64\NewWorld.exe` directo. Habla solo con `emulator/`. Parches de URL/pin solo en una **copia** del cliente.

## Clone

```powershell
git clone --recurse-submodules https://github.com/ivan-cavero/Azoth.git
# o, si ya clonaste el paraguas:
git submodule update --init --recursive
```
