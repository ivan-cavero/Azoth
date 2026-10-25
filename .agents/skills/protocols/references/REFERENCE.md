# Protocol reference

## Closing a row

1. Read the row in `research/atlas/meanings.md` and `STATUS.md`. Pick one unknown.
2. Decompile or measure. One question.
3. Update the row: what the field is, what is still unnamed, the build SHA-256, the evidence word.
4. Stop. Encoding in Rust is a later change that loads `everfall-server` and `rust`.

## Capture transformer

Allowed only as a separate module or crate. Each unnamed slice has an id written in the meanings file. A test lists those ids. Adding a slice without a new id fails the test.

The simulation does not import the transformer. The process at the edge may call it while a row is still partial, and the log line says which id was sent.

Retire an id by replacing the slice with named fields in the same change that updates the row. Do not leave both paths alive.

## What not to copy

| Blob | State |
| --- | --- |
| Registration response, 88 bytes | partial, size measured |
| Self identification, 21 zero bytes | unknown |
| Level info, 106 bytes, 26 unexplained | partial |
| Spawn record, 46,393 bytes, 48 fragments | unknown |
| Add-actor with zeroed fields | not "players see each other" |

## HTTP versus world

Channel HTTP gets the client to login. It does not own identity. Region HTTP owns login, the world list, and the queue ticket. The world process owns gameplay after DTLS. Do not add a gameplay route to the gateway because the client happened to call HTTP.

## Framing facts that are already measured

- Reliable records have a sequence. The resend table is keyed by that sequence.
- A record the client ACKs is not a record the client applied. Check the client log or a probe before claiming the rung landed.
- Full client SHA-256 before trusting a virtual address. Corpora stay under `reverse/builds/<sha256>/`.
