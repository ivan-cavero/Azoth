# Ontology glossary

| Term | Meaning |
| --- | --- |
| **Facet** | Client/server component surface exposed over REP (AZ type). |
| **Record** | State-bundle unit keyed by `record_id`; contains fragments. |
| **Fragment** | Typed payload slice inside a record (`key` + `type` + bytes). |
| **Carrier** | REP reliable/unreliable framing around application payloads. |
| **AOI** | Area of interest — which entities an observer should receive. |
| **Authority** | Who may change the canonical value (`server` preferred for wealth/position). |
| **Ladder** | Ordered entry messages that take a peer to InGame. |
| **Ticket** | One-time region→world admission token. |
| **Command** | Typed operator/player mutation on the command bus (not a wire synonym). |
| **Confidence** | Evidence ladder: bytes → layout → semantics → authoritative. |
