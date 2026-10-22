# Feature: azoth-wire parity, and the remaining 1.460 measurements

Phase 0 closure of `docs/PLAN-backend-rust.md`. Two halves:

* **Code** — the first crate of the Rust workspace, `azoth-wire`, ported from the
  Python codecs and proven byte-for-byte against them over the captured corpus.
* **Measurement** — the three 1.460 rows that Phase 0 left open (entity
  transform, sprint ceiling, buffer slot order) plus continued decoding.

Build in scope: `1.460.6033.6024067` /
`30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.

## Specs

- **S1.** "1. La paridad de azoth-wire" — the codecs are ported to Rust and their
  output is byte-identical to the Python encoders over the whole captured corpus.
- **S2.** "Arreglar el probe de transform" — the entity transform measurement
  works, or its unavailability is demonstrated with a concrete reason.
- **S3.** "Re-medir con sprint" — the sprint speed ceiling is measured, and the
  five-position buffer's slot order is resolved.
- **S4.** "luego continua toda la noche investigando cosas, haciendo decoding,
  con frida, etc lo que necesites" — continue the decoding work beyond the named
  items, within the repository's evidence rules.
- **S5.** "ves monitoreando el disco importante no pasarte" — check free disk
  before and after every disk-heavy step; compress raw logs rather than keep them
  raw; never let a log grow unbounded.
- **S6.** "cuando acabes todo pushea commitea y apaga el ordenador" — at the end:
  commit, push, then shut the machine down. Nothing is left running.
- **S7.** "consiguiendo tener todo para la 1.460" — every fact recorded is
  build-scoped to the SHA-256 above; a fact from another build is not evidence.
- **S8.** Repository rules: no EAC, no memory reads while its state is uncertain,
  Steam install read-only, no raw captures committed, docs and code in English.
- **S9.** The plan's own rules: a crate owns a distinct reason to change; no file
  over ~400 lines; no `unsafe` outside `azoth-wire` and `azoth-dtls`; no
  environment variables outside a `config` module.

## Tasks

| ID | Specs | Route | State |
| --- | --- | --- | --- |
| T1 | S9 | inline | in progress — branch `feat/azoth-wire-parity`, workspace skeleton |
| T2 | S1, S9 | inline | pending — codecs |
| T3 | S1 | inline | pending — differential harness, 0 mismatches |
| T4 | S2 | inline + live client | pending — transform probe |
| T5 | S3 | inline + live client | pending — sprint |
| T6 | S4 | inline | pending — decoding |
| T7 | S5, S6 | inline | pending — disk check, commit, push, shutdown |

## Log

### L1 — the user's request, verbatim

> Vale peus a ver yo me voy a ir a dormri quiero que estes toda la noche de forma
> autonoma, consiguiendo tener todo paral la 1.460 y asi mañana empezsa el
> servidor de rust ,1. La paridad de azoth-wire, Arreglar el probe de transform y
> Re-medir con sprin y leugo conctinua toda la noche investigando cosas, haciendo
> decoding, con frida, etc lo que necesites y ves monitoreando el disco importante
> no pasarte, cuando acabes todo pushea commitea y apaga el ordenador
