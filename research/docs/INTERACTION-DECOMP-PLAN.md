# Interaction decompilation plan

How the 564 client→server messages behind the twelve in-world menus get their fields
named, so a server can compose them instead of forwarding a capture.

Companion files: `../atlas/meanings.md` § *The interaction contract* (what is measured
today), `DECOMP-PLAN.md` (the program), `DECOMPILATION.md` (the command surface),
`../atlas/decomp-campaign.json` (the phase manifest).

---

## 1. Where this plan starts from

The **names** are done. `research/derived/wire-type-names.json` maps 2,559 of this build's
7,052 wire types to a name, and `python ef.py re input-contract --surfaces` derives the
twelve menus and joins them to the 179 component facet families behind them. The message
*identity* — which wire type is `AttributeComponentServerFacet_RequestSpendAttributePoints`
— is settled and regressible.

The **fields** are not. `meanings.md` already records why that gap is not closed by names:
*a field NAME is not a field ENCODING*. Knowing that `0x5de` is "spend attribute points"
does not say where the attribute index and the point count sit, how they are encoded, or
what the server must do to be believed. Out of 185 wire types in the old inventory, 6 were
laid out to the byte. Everything below is about closing that.

Two facts from the measurement shape the whole plan:

1. **A panel's contract is what it sends when the player *acts* inside it.** Opening a
   panel asks nothing; every window in the two labelled sessions was the input stream and
   the heartbeat. So each field cannot be learned by opening a menu — the surface has to
   be driven to the point where it emits.
2. **Most of those paths need state the replay does not have.** A guild has to exist before
   `RequestBatchCreateGuildInvites` is meaningful, a mount has to be enabled before
   `SummonMount` works, an auction listing has to exist before
   `RequestExecuteTradingPostTransaction`. That state is server work, and it is the real
   prerequisite of this plan — not the decompiler.

## 2. The method, per message

Five steps. Steps 1 and 4 are the ones that turn pseudocode into evidence; skipping either
is how a layout ends up wrong in the atlas.

| # | Step | Command / artifact | Why it is required |
| --- | --- | --- | --- |
| 1 | **Anchor the type** | `re pe str <MsgName>` → the registration lambda → the `lea` of the GUID → `typeIndex[n]` | Names the wire type *from the client's own registration*, not from an adjacency scan. Already done for the whole registry. |
| 2 | **Find the writer/reader** | from the registration record's function pointer: `re xref <va>`, `re pe callers <va>` | The registration stores a thunk to the type record; the record carries the serializer. That chain, not a guess from the name. |
| 3 | **Decompile it** | `re decompile --target <va>` (or `--symbol` if named) | Pseudocode gives the field ORDER and the codec call per field. |
| 4 | **Confirm on bytes** | a live session that drives the surface, then `re segment-types --offset` to pull the record, then compare field by field | A layout that has not been matched against a real record is a guess. This step is the evidence word *measured*; without it the row is *partial*. |
| 5 | **File it** | `research/atlas/meanings.md` (row with build SHA-256 and the evidence word) + `client-functions.json` (the function) | The atlas is the contract. A function decompiled and not filed is not understanding. |

The codec per field is the part that bites: each field goes through its own reader, and the
prefix varint (`FUN_14087b760`, recorded as `prefix_varint_reader_1460`) is the marshalling
primitive called from 853 sites. Layouts therefore have to be read as *"varint, then a
16-byte id, then a flag byte"*, not as fixed offsets.

## 3. Per system

Each row: the family, the messages that are already identified as the surface's entry
point with their wire types, **how to make the client emit them**, and what blocks it.

### Chat
- Family `Chat` (15 client→server) + `VoiceChat`.
- Entry points measured: `ChatComponentServerFacet_AddSubscription` `0x55`,
  `SetLanguageEnum` `0x101e`.
- Provoke: type a message in the chat box (Enter, then text, then Enter). The channel
  field is the interesting one — it is what a server needs to route.
- Blocker: none. This is the cheapest system in the plan: a text box needs no world state.

### Groups and party marks
- Family `Groups` (54 client→server).
- Entry points: `GroupsComponentServerFacet_RequestPing` `0x967`,
  `RequestTargetPing` `0xda2`, `CancelPing` `0xd9e`, `CancelTargetPing` `0xda3`,
  `RequestRemoveRaidMember` `0x1557` (measured in a live session),
  `RequestAllActivityJoinableLobbyCounts` `0x1555`.
- Provoke: form a party, then place a target tag on the map (`b` + a tag while a party
  exists). The 8-byte target id and the tag enum are the fields to earn.
- Blocker: a party must exist. The client will not ping into a group of one.

### Store and tokens
- Families `Entitlement` (18) + `PlayerAppearance`.
- Entry points: `EntitlementComponentServerFacet_InitializeTransaction` `0xc36`,
  `ClientInitializeTransaction` `0x382`, `RequestServerGetEntitlements` `0xc2e`,
  `RequestServerSyncEntitlements` `0xc30`, `PlayerAppearance…PurchaseAppearanceChange`
  `0x1914`.
- Provoke: open the store panel (`f11` for tokens) and attempt a purchase.
- Blocker: the transaction needs the client to believe a store backend exists. Expect this
  to be gated on entitlement state the server must first grant.

### Mount
- Family `Mount` (12 client→server, 10 server→client).
- Entry points: `MountComponentServerFacet_SummonMount` `0x1676`, `DismissMount` `0x1677`,
  `OnRequestChangeMount` `0x15f3`, and `OnEnableMounts` `0xacc` / `OnEnableMounts`
  `0xabd` (client facet, the server→client side).
- Provoke: `x` to summon. Measured: the client sends `OnMountDashToggleChanged` `0x187c`
  and `OnMountSlowWalkChanged` `0x187f` already, so the mount facet is live in a plain
  session — but only its toggles.
- Blocker: `OnEnableMounts` is the gate. "Having a mount" is the server enabling it, so the
  order is: send the enable, then read what the summon asks for.

### Auction (trading post)
- Families `CurrencyConversion` + `P2PTrade` (16) + `PlayerTrade`.
- Entry points: `CurrencyConversionComponentServerFacet_RequestExecuteTradingPostTransaction`
  `0x1b7` (measured, 19:42), `P2PTradeComponentServerFacet_UpdateOfferedCoin` `0x7a`
  (measured, 17:48), `LockInOffer` `0x106a`, `ConfirmTrade` `0x1ef`.
- Provoke: interact with a trading post terminal and buy or list one item.
- Blocker: `0x1b7` carried a transaction the server must validate; its fields are the
  item/price/quantity triple and are the highest-value unknown here after equipment.

### Character: equipment, attributes, weapon mastery, skill points
- Families `Paperdoll` (24), `Attribute` (5), `Ability` (6), `Progression` (5),
  `ProgressionPoint` (9), `CategoricalProgression` (13), `Vitals` (21).
- Entry points: `PaperdollComponentServerFacet_ServerEquipItem` `0xf37`,
  `ServerUnequipItem` `0x658`, `UnequipAllItems` `0x1743`,
  `RequestSwitchToLoadout` `0x160`, `ToggleSheath` `0xf3b`;
  `AttributeComponentServerFacet_RequestSpendAttributePoints` `0x5de`;
  `AbilityComponentServerFacet_RequestApplyAbilityPoints` `0xb29`,
  `RequestChangeMappedAbility` `0xa8d`;
  `ProgressionPointComponentServerFacet_RequestAssignPoolPoints` `0x458`.
- Provoke: the character panel already renders **239 attribute points available** with `+`
  buttons, so `0x5de` is one click away in a session that already runs.
- Blocker: **none for `0x5de`.** This is the plan's first target precisely because it needs
  no world state to provoke.

### Journal, map, crafting, inventory, social
- Long tails, same method. `Objectives` (27) + `Contracts` (14);
  `TerritoryInteractor` (43) + `TerritoryDetector`; `Crafting` (11);
  `Inventories` (11) + `GlobalStorage` (15); `Social` (45).
- Provoke: journal needs a real objective; the map needs territory; crafting needs a
  recipe and materials; the inventory needs items the server granted.
- These come after the cheap ones. They are the ones that most need server state first.

## 4. The asymmetry that sets the server's shape

Measured from the registry, and it is the plan's most important constraint:

| Family | Client sends | Server replies | What the server must do |
| --- | --- | --- | --- |
| `Attribute` | 5 | **0** | handle `0x5de`, then change replicated state |
| `Progression` | 5 | **0** | same |
| `ProgressionPoint` | 9 | **0** | same |
| `CategoricalProgression` | 13 | **0** | same |
| `Conversation` | 7 | **0** | same |
| `Ability` | 6 | 1 | `MasteryTreeRespecResponse` `0xb2a` is the only typed reply |
| `P2PTrade` | 6 | 9 | genuinely request/response |
| `Contracts` | 14 | 16 | genuinely request/response |

For five families there is **no reply message to send**. A server that "answers" those
requests waits forever; a server that only replays state without handling `0x5de` or
`0xb29` discards the player's spend silently. So the deliverable per system is not "the
response we send" but **which replicated state the request must change**.

## 5. Order, with the reason

Cost is decompiler work; value is "unblocks the first server crate". Sorted by value per
cost:

1. **`Attribute.RequestSpendAttributePoints` `0x5de`.** One message, provokable today from
   a panel already on screen, and the confirmation path is replicated state rather than a
   reply. It is the first contract that can be closed end to end.
2. **`Paperdoll.ServerEquipItem` `0xf37` / `ServerUnequipItem` `0x658`.** Equipment is the
   most requested behaviour and the largest family after the map.
3. **`Groups.RequestTargetPing` `0xda2`.** Party marks; small, and it proves the party
   state model.
4. **`ChatComponentServerFacet_AddSubscription` `0x55`.** Cheap, no world state, and it
   gives the server a working text channel early.
5. **`Mount.OnEnableMounts` → `SummonMount` `0x1676`.** Small family, and the enable/summon
   order is a clean test of "server grants, client then asks".
6. **`CurrencyConversion.RequestExecuteTradingPostTransaction` `0x1b7`.** High value, but it
   needs a listing and currency state first.
7. **Journal, map/territory, crafting, inventory, social.** Each needs its server state
   before its bytes mean anything.

## 6. Running it

```powershell
# the phase that holds this work
python ef.py re campaign add interaction --target <va> --note "0x5de writer, AttributeComponent"
python ef.py re campaign expand interaction <va>      # + its callers
python ef.py re campaign run --phase interaction --batch 10
python ef.py re campaign status

# anchors
python ef.py re pe str RequestSpendAttributePoints
python ef.py re xref <va>
python ef.py re decompile --target <va>

# the byte side of step 4
python ef.py run capture-segments --plan interact --out .azoth/tmp/segments-interact.json
python ef.py re segment-types --corpus .azoth/logs/world.log --segments .azoth/tmp/segments-interact.json --offset <N>
python ef.py re field-differential --type 0x5de --corpus .azoth/logs/world.log --segments .azoth/tmp/segments-interact.json
```

Two measurement rules learned the hard way and worth repeating here, because both cost a
pass:

- **Group `0x635` bodies by shape before comparing them.** The ALC body is variable-length
  (283 bytes idle, 298 with a panel open) and the position marker shifts by 3. A naive
  byte map reported 133 "fields" that were one shifted region.
- **A client record's type marker sits at offset 24, not 0.** It is wrapped in the client's
  own container. Reading only offset 0 reported zero records for a type present 20 times.

## 7. Done, per system

A system is done when, for each of its entry-point messages, the atlas holds: the wire
type, the field layout with each field's codec, **which replicated state the server must
change**, the client build SHA-256, and the evidence word. Not when the decompiler has been
run over it.
