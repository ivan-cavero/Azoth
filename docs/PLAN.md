# Everfall

Private server for New World. The project used to be called Azoth. That name
belongs to another preservation project (projectazoth.com), so the public name
is Everfall. The in-game resource is still called Azoth. Do not rename it.

The Rust server that lived in `server/` was deleted on 2026-10-25. It sent
the client a ladder of captured bytes, including a 46,393 byte spawn and a
self-identification of 21 zeros. Git history keeps the code. The inventory of
what those bytes were trying to be is `research/atlas/meanings.md`.

## What runs today

`python ef.py` is the command. On a fresh Windows checkout, `.\az.ps1 setup`
once installs the pinned local Python, then every later command is
`python ef.py`. The hidden tool directory stays `.azoth/` so the existing lab
keeps its paths.

`python ef.py dev` starts the Python gateway, the Python world, and Caddy.
That stack is a measuring lab. It is allowed to replay a capture so we can
watch the client. It is not the game server we are building.

The public site lives in `platform/web`. GitHub Pages still publishes with
base path `/Azoth` because that is the repository name. The words on the page
say Everfall.

## How the server comes back

One meaning at a time, from `research/atlas/meanings.md`.

1. Pick the single next row whose fields are still unknown.
2. Decompile or measure until those fields have names, or until you can write
   down why a field is intentionally unused.
3. Update the row. Say what was observed, on which client build.
4. Only then add Rust. The first crate builds that one message from the names.
   A test checks the meaning (this message tells the client which territory
   it is entering), not only that the bytes match a capture.

A capture transformer is allowed beside the simulation. It is the only place
unnamed bytes may exist. Each unnamed field carries an id from the meanings
file. Adding a new unnamed field without a new id is a failed change.

The simulation crate does not open sockets and does not import the
transformer. The process that owns the socket calls the simulation, then
encodes the result. Crypto and the handshake stay off the 50 Hz tick. That
split was already measured as necessary: a join must not stall the 20 ms
budget.

Later, a patched client may speak a clearer protocol. That is an explicit
version, shipped beside the stock path. The stock client remains the proof
that the preservation server works.

## Rust, when a crate is justified

- Workspace under `server/`, crate names prefixed `everfall-`.
- `everfall-sim`: rules and state, no I/O.
- `everfall-wire`: encode and decode only.
- `everfall-net`: DTLS and UDP. OpenSSL stays inside this crate.
- One binary at first: the world process. Channel and region HTTP stay in
  Python until their JSON fields are named the same way.
- No `unwrap` outside tests. No `unsafe` without a written reason.
- `clippy` with warnings denied on crates we add.
- The server rejects client claims about position, items, and currency that
  the simulation did not accept.
- Tickets expire. Admin commands are not accepted on the game port.
- Do not log session tokens.
- Measure tick time and bytes per player before changing a data structure.
- Interest comes before serialization: do not build a packet for someone who
  cannot see the actor.

## What an agent is for

`STATUS.md` is the only status. It says what is happening, the single next
step, what blocks it, and what not to do. An agent that is asked "por dónde
vamos" reads that file and `research/atlas/meanings.md`, then answers with
the next step. It does not read `docs/archive/` or `docs/journal/raw/`.

When you say "vamos con eso", the agent does that step: one decompile or one
live measurement, then an update to the meanings file. It does not open a
second front and it does not recreate `server/`.

Paste this when you want a session to stay on the rails:

```text
Lee STATUS.md y research/atlas/meanings.md.
Dime el único siguiente paso y espera.
Cuando te diga que sigas, haz solo ese paso.
Si el paso es decompilacion o una prueba en el cliente, escribe el resultado
en la ficha de significados con el build del cliente y lo que sigue sin nombre.
No crees server/ ni envies un mensaje cuyos campos no esten escritos en esa ficha.
El cliente oficial es el contrato. Un transformador de captura solo es valido
si cada byte sin nombre tiene un id en la ficha y el numero de esos bytes no crece.
```
