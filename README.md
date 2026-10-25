# Everfall

Everfall is a private server for New World. The stock client is the contract:
it should enter a world because our server decided what that world is, not
because we copied a packet we cannot explain.

This is unofficial. It is not affiliated with Amazon Games.

## The idea

A server tells the client what happened. It does not let the client invent
its position, its items, or its currency. To do that we have to know what
each message means. A captured blob is evidence of a shape. It is not a
model of the game.

So the rule is: name the fields, then send the message. Until a row in
[`research/atlas/meanings.md`](research/atlas/meanings.md) names those
fields, the only thing allowed to emit the old bytes is the measuring lab.
Rust does not encode an unnamed field.

The lab exists so we can watch the client. `python ef.py dev` starts three
local programs:

- Caddy terminates local HTTPS.
- The gateway answers the HTTP the client uses before a world: the channel
  document, login, and the world list.
- The world speaks DTLS and can replay a captured session.

That replay can put a client on a loading screen. It does not decide the
game. When a meaning is written down, the real server grows by one message:
the simulation decides, the encoder writes the named fields, and the socket
sends the result. Crypto stays off the 20 ms tick. The stock client remains
the test. A patched client, later, would be a second protocol beside this
one, not a way around an unnamed field.

How that server is allowed to come back is [`docs/PLAN.md`](docs/PLAN.md).
The current step is [`STATUS.md`](STATUS.md).

## Run

`python ef.py` is the only command. On Windows, any Python 3.11 or newer
can run the first setup. Setup installs the pinned interpreter, the
virtualenv, and Caddy under `.azoth/`.

```text
python ef.py setup
python ef.py doctor
python ef.py dev
python ef.py game
python ef.py status
python ef.py stop
```

The Steam install stays read-only. The private client copy is
`private-client/`. Logs are `.azoth/logs/`. `python ef.py setup --re` adds
Ghidra. `python ef.py mode private` switches host routing and needs an
elevated shell.

## Where things live

| Path | What it is |
| --- | --- |
| `ef.py`, `lab/` | The command. It starts and stops processes. It is not the game. |
| `services/gateway` | The HTTP the client needs before it opens a world |
| `services/world` | The DTLS measuring lab, including capture replay |
| `services/launcher` | How the private client is started |
| `platform/web` | The public site |
| `research/atlas` | Facts, and the meaning inventory |
| `reverse/` | Decompilation and live probes |
| `deploy/` | Caddy and local certificates |
| `scripts/` | Helpers behind `python ef.py run` |

There is no `server/` directory. The previous Rust tree sent captured bytes
whose fields were not named, so it was removed. Git history still has it.

## Names

Everfall is this project. New World is the game. Azoth is a resource in the
game, and it is also the previous name of this project. The local tool
folder stays `.azoth/` so checkouts that already use it keep working. The
Python packages `azoth_gateway` and `azoth_world` keep those import names
for the same reason. None of those words is the server we are building.
