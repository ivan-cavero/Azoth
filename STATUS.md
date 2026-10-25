# Live status

Everfall. Private New World server. The Rust tree in `server/` was removed
on 2026-10-25. Inventory: `research/atlas/meanings.md`. How we rebuild:
`docs/PLAN.md`. Command: `python ef.py`.

## Now

The Python gateway, Python world, and Caddy are the measuring lab
(`python ef.py dev`). They can still put a client into a world by sending
captured traffic. That is a rig, not the game.

Client build under study: **1.460.6033.6024067** —
`30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.

## Next

Name a field inside the 21-byte self-identification body. The 4-byte `0x1791`
note was the header `00 01 91 17` read as a little-endian integer; those bytes
are wire type `0x5d1`. Decompile the handler on the 1.460 build, or adopt the
installed build first. Its SHA-256 is `8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e`.

## Blocked by

The 21-byte body still has no named field, so Rust would only resend zeros.

## Do not

Recreate `server/`. Send a datagram because a capture contained it. Rename
the in-game resource Azoth. Read `docs/archive/` or `docs/journal/raw/` whole.
