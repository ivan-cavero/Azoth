# Easy Anti-Cheat EOS and why reading memory now is a bad idea

New World uses **Easy Anti-Cheat EOS** (Epic Online Services), not the classic standalone EAC.

IDs of this install (`EasyAntiCheat/Settings.json`):

| Field | Value |
| --- | --- |
| productid | `b0855340e2ed491096135339f6fc94b7` |
| sandboxid | `c9882365293e4c2e858eee62c4b181b5` |
| deploymentid | `29e9a08ed0974685b64a6d52b74570a2` |
| executable | `Bin64/NewWorld.exe` |
| bootstrap | `NewWorldLauncher.exe` → `EasyAntiCheat_EOS_Setup.exe install <productid>` |

## How it is set up

Three pieces:

1. **Launcher** — Steam opens `NewWorldLauncher.exe`, which starts the EAC EOS service and then the "protected" game.
2. **Usermode module** — an EAC DLL loads **inside** `NewWorld.exe`. Integrity checks, process/module lists, heartbeats to Epic's backend.
3. **Kernel driver** (`EasyAntiCheat_EOS.sys` / EAC family) — ring 0. This is where the memory protection lives.

Epic's official documentation (crash dumpers): an external process **cannot** open a handle to the game with memory rights. If it does, the game hangs and EAC kills it. That includes "read-only" dumpers.

## Reading vs writing

It is not "write = ban, read = ok".

The driver registers `ObRegisterCallbacks` over processes. When *any* program does:

```text
OpenProcess(PROCESS_VM_READ,  ..., NewWorld.exe)
OpenProcess(PROCESS_VM_WRITE, ..., NewWorld.exe)
```

the kernel callback **fires all the same**. EAC can:

- strip `PROCESS_VM_READ` and `PROCESS_VM_WRITE` from the handle (the read fails)
- flag the session and send telemetry to the backend
- close the game

`ReadProcessMemory` is the API of wallhacks, radar and bots. Protecting it is the anti-cheat's job, not an extra. Cheat Engine in "just looking" mode steps on this too.

It is not stealth either:

- Frida / inject / debugger
- drivers "so it doesn't show"
- mapping physical memory to bypass the handle

That is the catalog of cheats EAC is designed to catch. We are not building it, not now, not "a little".

## What IS safe *while playing official*

Everything that **does not open the game process with VM_READ**:

| Technique | What it gives the private server |
| --- | --- |
| `Game.log` | Entire login, states, URLs, REP `ip:port`, RMI names |
| pktmon at the NIC | TCP 443 + UDP flows, TLS SNI, DTLS hello, sizes, timing |
| DNS cache / ETW DNS | hostname → IP (CloudFront, API Gateway, Vivox, EAC) |
| netstat per PID | connection table without reading game RAM |
| Files on disk | PAKs, configs, channel JSON, local EAC logs |
| Strings / PE of the exe **on disk** | embedded URLs, DTLS cipher, Javelin names, imports |

That is **protocol** reverse engineering, which is what needs cloning. A RAM dump gives you C++ structures (`GameConnection` offsets). Useful, yes. **It is not what closes in January.** What closes is the live Amazon ↔ client traffic.

## When we WILL read memory

When the client **no longer talks to Amazon or the EAC backend**:

- official servers off (Jan 31, 2027), or
- our REP + the game launched **without** the EAC bootstrap (direct exe, EAC product decommissioned)

Then `ReadProcessMemory` is a debugger over *our* local process, not an evasion. We will do it then, with clear scripts, **without** hiding from the kernel.

Until that date, the value per invested hour is:

1. **Network** (pcap + SNI + DTLS + login queue)
2. **Game.log** structured
3. **Static of the exe** (Ghidra / strings)
4. Memory — later

## What we need of "runtime" without RAM

The game, while running, already emits:

- every transition `Disconnected → … → InGame`
- every HTTPS URL it hits
- the `RepAddress` the launcher/gateway gives it for the world
- the cipher and the fact that the REP socket establishes
- the `messageType` of the RMIs (`*ComponentClientFacet_*`)

That *is* runtime. It goes to disk and to the network. There is no need to enter the address space.

Scripts: `tools/reversing/README.md`.
