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

Name the fields of one world-entry rung that is still a captured blob.
Start with self-identification (21 zero bytes) or level info (106 bytes,
26 unexplained). Write the names into `research/atlas/meanings.md`.

## Blocked by

Those fields have no names, so a new Rust server would only resend the capture.

## Do not

Recreate `server/`. Send a datagram because a capture contained it. Rename
the in-game resource Azoth. Read `docs/archive/` or `docs/journal/raw/` whole.
