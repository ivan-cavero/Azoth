# Meanings

This is the inventory of what a New World server has to mean, taken from the
Rust workspace the day it was deleted (2026-10-25). The code remains in git
history under `server/`. A new server may send a message only after its row
here says the fields are understood.

The Python gateway and world under `services/` are the measuring lab. They may
still emit a captured blob. That blob is not a model of the game.

Client build this inventory was taken against: **1.460.6033.6024067**,
SHA-256 `30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.

Evidence words: **measured** (seen on a live client or capture), **partial**
(we know the role, not the fields), **unknown** (bytes we cannot name).

## Names

| Word | What it is |
| --- | --- |
| Everfall | This project: a private New World server |
| New World | The game. The stock client is the contract |
| Azoth | A resource inside the game. Also the previous name of this project. Not the server |
| `.azoth/` | Local tools, logs, and the pinned Python. The path stays so existing checkouts keep working |
| `azoth_gateway`, `azoth_world` | Import names of the Python lab. Not crate names |
| `ef.py` / `lab/` | The command that starts and stops processes |
| `services/` | The measuring lab: HTTP gateway, DTLS replay, private-client launcher |
| `server/` | Absent. A Rust crate appears only after a row below names its fields |

## Unnamed, with ids

Every byte we cannot name has an id. The set does not grow without a new id.
Naming a field removes it from this list. None of these ids is a gameplay noun.

| Id | What is still unnamed | Evidence |
| --- | --- | --- |
| `flow.channel.document` | The channel HTTP document the client needs before login. Identity does not belong in it. | partial |
| `flow.region.captured-body` | Login, entitlements, world list, and ticket JSON that still copies an official response | unknown bodies |
| `flow.world-entry.rung.registration.body` | Registration response. 88 captured bytes. | partial, measured size |
| `flow.world-entry.rung.greetings.body` | GridMate greeting. Not a game event. | partial |
| `flow.world-entry.rung.self-identification.body` | The 21 bytes after the typed-envelope header. Wire type is `0x5d1`. No field inside the body is named. | unknown |
| `flow.world-entry.rung.level-info.unexplained` | The part of `LevelInfoChangedMsg` (`0x663`) that is not the level name, the coatlicue path, the floats, or the context key. One note says 106 bytes with 26 unexplained. Another parse of the same type says 110 bytes. | partial |
| `flow.world-entry.rung.spawn.body` | Spawn record id 1. 48 fragments, 46,393 captured bytes. | unknown |
| `flow.world-entry.rung.state-stream.body` | The resend of that spawn, about once a second. The quiet cable is measured. The body is the spawn. | measured effect |
| `flow.world-entry.presence.fields` | Add-actor fanout. A candidate actor id and zeros. Not "players see each other." | unknown |

## What the client walks

The client does three different jobs against three different programs. Mixing
them into one process is how a private server becomes a pile of routes.

| Program | Job | What we actually know | Lab today |
| --- | --- | --- | --- |
| Channel | HTTP document that gets the client to the login screen: channel list, news, images, cache validators | The client will not continue without it. Identity does not belong here. | Python gateway |
| Region | Who you are: token, credentials, entitlements, login info, world list, queue ticket | The route list is real. Many JSON bodies are still the shape the official servers returned, not values this project owns. | Python gateway |
| World | Gameplay over DTLS. One UDP socket, a 50 Hz tick, then the entry ladder below. | The tick rate and the datagram ceiling are measured. The bodies of the ladder are mostly captured. | Python world |

A captured HTTP body is allowed in the lab so the client can be opened and
observed. It is labeled unknown until someone writes the fields down here.

## World entry ladder

Order is part of the meaning. Sending two rungs in one burst crashed the
client. Sending them out of order leaves the client stuck with no error.
Each rung is valid only in the state the previous rung produced.

| Rung | Client state it moves | What it is | Evidence |
| --- | --- | --- | --- |
| Registration response | Waiting for the REP connection → waiting for the actor connection | The server accepts the client's registration. The body we had was 88 captured bytes. | partial, measured size |
| Greetings | GridMate peer handshake | The stock greeting, not a game event. | partial |
| Self identification | → waiting for a spawn point | `PlayerManagerSelfIdentificationMsg`. The lab sends a typed-envelope header `00 01` plus prefix-varint `91 17`, which is wire type `0x5d1`. Reading `91 17` as a little-endian integer yields `0x1791`, the old 4-byte note. The body after that header is 21 zero bytes, id `flow.world-entry.rung.self-identification.body`. No field in those 21 bytes is named. A lab comment points at VA `0x146454c00` and a 56-byte in-memory struct; that address is a function entry on installed SHA-256 `8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e`, which is not the 1.460 build this inventory uses. It was not decompiled. | partial header, unknown body |
| Level info | → waiting for the player spawn; the map loads | `LevelInfoChangedMsg`, wire type `0x663`. A 2026-09-30 parse names a level name, a coatlicue path, floats, and a context key. The remainder is `flow.world-entry.rung.level-info.unexplained`. | partial, measured |
| Spawn | → in game; the player appears | One record, id 1, 48 fragments, 46,393 captured bytes. | unknown |
| State stream | keeps the connection indicator quiet | The same spawn record re-sent about once a second. The effect is measured. The payload is the unknown spawn. | measured effect, unknown body |

Chunking is a transport fact, not a game fact. A record bigger than about 256
bytes was acknowledged and never delivered when sent as one datagram
(measured 2026-09-24). The working cut is 1100 byte chunks, one chunk per
50 Hz tick. The datagram ceiling is 1200 bytes. Above the path MTU a lost
fragment loses the whole datagram.

## Presence

The deleted server fanned out an add-actor message after the ladder, with a
candidate actor id and zeros in the fields nobody had decoded. That is not
"players see each other." Do not rebuild it until the head id is proven
against a live client and the other fields have names.

## What "official" means here

An official-feeling server decides, then tells the client what happened.

- The client asks to move. The server accepts a new transform or rejects it.
- The client asks to join a world. The server chooses the character, the
  territory, and the spawn because it knows those things.
- Another player enters your interest set. The server says so because the
  simulation moved them there.

A transformer is allowed when a field is still unknown. It lives apart from
the simulation, it names the capture and the client build, and the number of
unnamed fields in it is not allowed to grow. Replacing that transformer with
real values is the work. Changing the client later, so we can speak a clearer
protocol, is a second project and does not replace this one. The stock client
stays the test that preservation works.

## Next meaning to earn

The header is settled. `flow.world-entry.rung.self-identification.body` is
still the 21 bytes, with no named field. The next decompile has to be of the
handler on build `30fe6461…`, or the installed build has to be adopted on
purpose. Rust does not encode this body.
