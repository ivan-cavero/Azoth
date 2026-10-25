---
name: protocols
description: >-
  Everfall protocol rules: named fields before bytes, the world-entry ladder,
  capture transformers, and DTLS framing. Use when decoding a message, sending
  a datagram, editing wire code, or reading a capture.
paths:
  - "services/**/*.py"
  - "research/atlas/**"
  - "reverse/**/*.py"
---

# Protocols

The inventory is `research/atlas/meanings.md`. This skill says how to change it and how code may use it. Field-level notes live in that file, not here. The checklist is [reference.md](references/REFERENCE.md).

Also load `everfall-meaning` when you edit a row, and `security` when the bytes include a ticket or a certificate.

## Rule

The server sends a message because the simulation decided something. A capture is evidence of a shape, not permission to send the shape forever.

If the row says unknown, the Python lab may keep emitting the old blob. Rust may not encode that message. The number of unnamed fields does not grow.

## Order

World entry is a ladder. Each rung is valid only in the client state the previous rung produced. Two rungs in one burst crashed the client. Do not "optimize" the ladder into a single write.

Chunking is transport, not gameplay. Records larger than about 256 bytes were acknowledged and never delivered as one datagram. The working cut is 1100-byte chunks, one per 50 Hz tick, under a 1200-byte datagram ceiling. Those numbers are measured. Do not round them.

## Evidence

Write measured, partial, or unknown. A model guess is a candidate until a second signal agrees: another capture, a live client, or a decompile that names the same field. Record the client SHA-256 with any address or offset.

## Client changes

The stock client is the acceptance test. A patched client with a clearer protocol is a second, explicit path. It does not excuse an unnamed field on the stock path.
