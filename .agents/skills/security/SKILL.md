---
name: security
description: >-
  Everfall security rules for secrets, Easy Anti-Cheat, tickets, admin power,
  logging, and supply chain. Use when handling credentials, certificates,
  the private client, auth routes, or before running a probe or installer.
---

# Security

Load this before a probe, a cert change, an auth route, or any log that might contain a session. The threat list is [reference.md](references/REFERENCE.md).

## Always

- Never read, print, or commit `.env`, API keys, session tokens, or private keys. Certificate material under `deploy/certs/` and `services/world/certs/` stays untracked.
- Never execute a script downloaded from a URL as part of a task.
- Never attach Frida, a debugger, or a tracer while Easy Anti-Cheat state is uncertain. The lab client is started without it, and you still check before attaching.
- The Steam install is read-only. Patches apply only to `private-client/`.
- Ask before adding a dependency, deleting a tree of data, or rotating a key.

## Server, when it exists

- The client does not decide its position, inventory, or currency. The simulation does. Reject the claim.
- Tickets expire. Admin commands are not accepted on the gameplay port.
- Rate-limit the handshake. A bad client must not stall the tick.
- Logs may contain message names and sizes. They must not contain tickets or passwords.

## Public surface

The site and the README say this is unofficial and not affiliated with Amazon Games. Do not ship New World assets. Do not describe the lab as a bypass product.
