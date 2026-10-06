# World server

The world process speaks Javelin REP over UDP with DTLS 1.2. The login queue
returns its `RepAddress`; local development defaults to `127.0.0.1:9000`.

```powershell
python az.py world start
```

`python az.py dev` starts the gateway and world together. The world needs
pyOpenSSL because Python's standard `ssl` module does not implement DTLS.
Install it in the interpreter used for the world with
`python -m pip install pyOpenSSL`.

## Current behavior

The client completes the connection, loads the world, and possesses its local
player. Movement is still blocked because the local entity has no physics
components. See [STATUS.md](../../STATUS.md) and the
[component creation evidence](../../research/atlas/client-functions.json).
The captured 1.365 state replay does not implement the current client's missing
component path.

## Code and local data

- `src/azoth_world/rep.py` — DTLS peer sessions, Carrier handling, dispatch,
  replay, and traffic logging.
- `src/azoth_world/javelin/` — bitstream, Carrier records, V3 messages, and
  replay helpers.
- `tests/` — standard-library `unittest` coverage for wire and session behavior.
- `certs/` and `rep_traffic.jsonl` — generated local files; ignored by Git.

## Useful runtime settings

- `AZOTH_LOG_RAW=1` records encrypted UDP datagrams before/after DTLS. Set it
  in the environment used to start the world process. `python az.py dev` does
  not forward changes made in another shell.
- `AZOTH_LOG_OUTBOUND_PAYLOADS=0` disables captured plaintext server sends.
- `AZOTH_REP_TRAFFIC_JSONL=<path>` redirects the append-only traffic log.
- `AZOTH_REPLAY_LOCAL_PLAYER_UUID=character` applies the measured replay UUID
  substitution that allows local-player possession; it does not add physics.

Traffic logs contain decrypted payloads and may include session identities.
Keep them in ignored local storage. Stop the server before editing or replacing
its append-only log. For other replay controls, use the focused entries in
`research/atlas/levers.md`.
