# Server select — server list and selection commit

Build analyzed: pending · Status: open

## Overview

1. Server list request after login queue release.
2. Selection commit -> character select phase.

## UI surfaces (exhaustive)

| Surface | Trigger | Client behavior | Server interaction | Evidence |
| --- | --- | --- | --- | --- |
| (pending) | | | | |

## Client state machine

- `open:` gate that enables the confirm/enter button (likely world status +
  character ownership checks).

## Messages and payloads

- Seed targets already in the campaign: `worlds_info_accessor`,
  `worldtype_mapper`, `worldmetadata_property_table` (all confirmed in
  `../client-functions.json`) — `open:` exact request/response for the list.

## Functions involved

| Function (name tier) | VA (build) | What it expects | What it triggers | Evidence |
| --- | --- | --- | --- | --- |
| worlds_info_accessor (confirmed) | 0x144ad6e70 (8654f01d…) | world list data | UI list render | client-functions.json |
| worldtype_mapper (confirmed) | 0x1417c40a0 | world type id | list typing/labels | client-functions.json |

## Data and assets

- `open:` whether the list comes from a static PAK datasheet plus a live
  status call (`datasheet_path_joiner` may join the rows).

## Open questions

- `open:` full server-list response schema (keys, casing, requiredness) —
  goes into `../models.json` when observed.

## Negative findings

- (none recorded yet)
