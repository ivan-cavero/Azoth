# The "Link Account" dialog

How the Amazon Games iD account-link dialog comes to exist, so its text, its
behaviour, or its existence can be changed on purpose instead of by accident.

Everything below is read off the installed client (build 1.460.6033.6024067,
`30fe6461…`) and its PAKs on disk. Nothing here was measured in a live session
yet; the two unverified links are marked **not yet measured**.

## What the dialog actually is

It is a **frontend info-modal**, not an error panel and not a separate screen.
The title string is the proof:

| Loc key | en-us | es-es |
| --- | --- | --- |
| `agid_link_modal_title` | `Link Account` | `Enlazar cuenta` |

Read from `DataStrm-part3.pak`:

- `localization/en-us/versionmodals.loc.xml` — method 15 (Kraken), 7157 B,
  crc `5b3ff8eb`.
- `localization/es-es/versionmodals.loc.xml` — method 15, 7612 B,
  crc `30584512`.

All eleven strings of the modal live in that one file, which is why it is the
single edit target for changing the text:

| Key | Role |
| --- | --- |
| `agid_link_modal_title` | dialog title |
| `agid_link_modal_explanation_text` | body, includes `{url}` and the promo rewards |
| `agid_link_modal_verification_code` | the `VERIFICATION CODE` label |
| `agid_link_modal_share_warning` | "do not share your code" |
| `infomodal_agid_generate_code_button_text` | the Generate button |
| `infomodal_agid_expiration_text` | countdown line, `{expirationTime}` |
| `infomodal_agid_expired_text` | expired state |
| `infomodal_agid_error` | error state |
| `infomodal_agid_rate_limited_tooltip` | button cooldown tooltip, `{timeRemaining}` |
| `agid_link_complete_title` / `agid_link_complete_message` | the success variant |

The body text is a **promotion**: 2 Transmog Tokens, 5 Prime Blue Dyes, 2 Season
XP Boosters, 2 Gathering XP Boosters, 2 Weapon XP Boosters. That is what the
dialog is for — it is not a login gate.

## The UI that draws it

Also in `DataStrm-part3.pak`:

- `lyshineui/infomodal/infomodal.luac` — the modal screen. Its `ROW_TYPES` table
  has an `AGID` entry, and it owns the `ShowAGIDLinkModal` function, which sets
  the four `agid_link_modal_*` strings and the art.
- `lyshineui/infomodal/modalrow_agid.luac` — the row. It owns a `CODE_STATES`
  table (`ungenerated`, `waiting`, `ready`, `expired`, `error`), a `RequestCode`
  path through `GameRequestsBus` → `GetAccountLinkCodeExpiration`, a refresh
  icon, an expiration countdown, and a Generate button with its own cooldown.
- `lyshineui/infomodal/infomodal.dynamicuicanvas` — the canvas.
- `lyshineui/images/modalcontent/agid_linking_prod.dds` and
  `agid_linking_gamma.dds` — the two art variants the modal picks between.

The row subscribes to `AuthBackendNotificationBus` and reacts to
`OnAccountLinkCodeRetrieved` and `OnAccountLinkError`. It reads its button
cooldown from config key `javelin.agid-link-modal-button-cooldown`.

## What decides to show it

### The gate chain, in the client's own UI script

`lyshineui/main menu/landingscreenv2.luac` (also `DataStrm-part3.pak`, method 15,
205191 B, crc `259d7326`) is where the decision lives. It has a `TryShowAGIDLink`
function and a `tryShowAGIDLinkModalNextFrame` scheduler that calls it once the
landing screen has ticked. The checks it performs, in the order they appear in
the file's constant pool:

| # | Check | Meaning |
| --- | --- | --- |
| 1 | `ConfigProviderEventBus.GetBool("javelin.enable-agid-account-linking")` | master switch |
| 2 | `IsCharacterSelectState` | only at character select |
| 3 | `hasShownAGIDLinkThisSession` | at most once per session |
| 4 | `DynamicBus.NewsModals.IsNewsDisplaying` | yields to a news modal |
| 5 | `GameRequestsBus.IsAuthorized` | must be authorized |
| 6 | **`GetIsShadowAccount`** | **the dialog is for shadow accounts** |
| 7 | `IsAGIDLinkModalSuppressed` | final suppression veto |
| 8 | `Debug.Log("Showing AGID account link modal")` then `DynamicBus.InfoModal.Broadcast("ShowAGIDLinkModal")` | it shows |

After showing it sets `hasShownAGIDLinkThisSession`, and the button cooldown comes
from `javelin.agid-link-modal-cooldown-secs` (`GetInt`) and
`javelin.agid-link-modal-cooldown-multiplier` (`GetFloat`) combined through
`Math.Pow`.

On success the same file runs `OnAccountLinkSuccess`: it closes the modal,
sets the screen state to `SCREEN_STATE_ATTRACT_SCREEN` with
`SCREEN_TRANSITION_FADE_IN`, and raises an OK popup titled
`@agid_link_complete_title` with body `@agid_link_complete_message`, event id
`ag_id_link_complete`.

**Confidence:** the checks themselves are certain — they are the named calls and
config keys in that function. Their exact boolean wiring is read from constant
order, because the payload is compiled LuaQ bytecode and this repo has no Lua
decompiler yet. Check 6 is the link back to the gateway: `GetIsShadowAccount` is
the same `Full`/`Shadow` distinction the Omni token response carries.

### The trigger behind it

The account-link *session* is driven from the executable, in the Omni auth
backend, not from Lua. The strings sit in one cluster in `NewWorld.exe`
(`0x844b198` onwards), in this order:

```
omni::session::GetAccountLinkActionCode returned code: 
javelin.enable-agid-account-linking
Initializing OmniSDK %d.%d
…
Full          Shadow          Get ags account type result: %s
Get ags account type error: %d
AGS account link code retrieved: %s (expiration: %lld)
agid_account_link_confirmation
persona_id_changed
AGS account link success
AGS account link code expired
agid_link_expired
AGS account link error: %s
agid_link_error
event_payload
AGS account link session ended
```

So:

1. The client asks Omni for the AGS account type and logs
   `Get ags account type result: %s`, which is `Full` or `Shadow`.
2. It opens an account-link session and requests a link code
   (`GetAccountLinkActionCode`, `GetAccountLinkCode`,
   `GetAccountLinkCodeExpiration`; the SDK also carries
   `PollAccountLinkStatusJob`).
3. Depending on the outcome it broadcasts one of four UI events:
   `agid_account_link_confirmation`, `agid_link_code_shown`, `agid_link_error`,
   `agid_link_expired`.
4. `landingscreenv2.luac::TryShowAGIDLink` decides, and
   `infomodal.luac::ShowAGIDLinkModal` draws it, with `modalrow_agid.luac`
   rendering the code, the countdown or the error state.

`Shadow` is the value that starts this flow: it is the unlinked-Steam persona.
The gateway serves `account.type` in the Omni token response and now defaults it
to `"full"`, so `GetIsShadowAccount` is false and the dialog stays away. A
gitignored `<discovery_dir>/tokens.json` override is still served verbatim and
can flip it back to `shadow`, which is why the dialog used to be intermittent;
see `services/docs/GATEWAY.md`.

## Two different dialogs, do not confuse them

There is a second, unrelated set of account messages: the **auth result**
strings. `NewWorld.exe` carries 35 `mm_authresult_*` keys; the client appends a
platform suffix and looks the result up in
`localization/<lang>/frontendcommontext.loc.xml` (also `DataStrm-part3.pak`).
The ones that mention linking are:

| Key | es-es |
| --- | --- |
| `mm_authresult_Error_LinkedAgsAccountRequired_windows` | "Para continuar, debes vincular tu cuenta de Steam a tu iD de Amazon Games…" |
| `mm_authresult_Error_ChildPlatformAccountWithoutAgsAccount_windows` | same text |
| `mm_authresult_Error_Persona` | "Error de autenticación. Error al crear la sesión." |

Those are blocking, one-line notices from the login pipeline. The promo modal is
the one titled **Enlazar cuenta**. If a future report says "the link dialog",
ask which of the two before touching anything: they are edited in different
files and triggered by different code.

## Levers

| Want | Lever | Status |
| --- | --- | --- |
| Turn the whole link flow off, cleanly | Serve `javelin.enable-agid-account-linking` as `false` in the S3 remote-config document (`services/gateway/src/azoth_gateway/routes/s3.py`, `JAVELIN`) — this is check 1 of `TryShowAGIDLink` | **Implemented** in the gateway; pinned by `test_s3_disables_agid_account_linking`. The live client A/B is still owed: the key is read by the landing screen's `ConfigProviderEventBus.GetBool`, but whether it comes from our remote-config layer is unmeasured (the sibling `javelin.offline-id-version` is proven to be read there) |
| Turn it off at the source | Serve `account.type: "full"` in the Omni token response — check 6, `GetIsShadowAccount`, then fails | **Implemented**: `routes/omni.py` now defaults to `"full"`, pinned by `test_omni_tokens_mock`. Note the gitignored `<discovery_dir>/tokens.json` override is served verbatim and can still flip it back to `shadow`; see `services/docs/GATEWAY.md` |
| Change the modal text | Edit `localization/<lang>/versionmodals.loc.xml`, repack as a patch pak with `reverse/tools/pak/pakwrite.py`, put it first in `PaksList.lst` | Tooling proven (`pakwrite.py selftest` round-trips a real localization edit); the **lookup priority claim is not yet measured** — one line change + one launch decides it |
| Change the blocking auth notice | Same method, `localization/<lang>/frontendcommontext.loc.xml` | same |
| Replace the dialog's content entirely | `infomodal.luac::ShowAGIDLinkModal` + `modalrow_agid.luac` (row type `AGID`) | needs a Lua bytecode edit path; the repo has no Lua decompiler yet |
| Make the modal stop showing an error state | Give `/auth/platform/user/code` the shape OmniSDK expects so `GetAccountLinkActionCode` stops returning 203 | Our stub currently 203s; the correct shape is unknown |
| Change which art shows | `agid_linking_prod.dds` / `agid_linking_gamma.dds` | not investigated |
| Tune the Generate-button cooldown | `javelin.agid-link-modal-button-cooldown`, `-cooldown-multiplier`, `-cooldown-secs` | keys known, values not measured |

## What to measure next, in order

1. **The live A/B for the two server-side switches — VERIFIED 2026-10-25.** With
   `account.type: "full"` and `javelin.enable-agid-account-linking: false`
   served by the gateway, a clean launch (no `-Watch`) reached **character
   select** — the state the gate's second check (`IsCharacterSelectState`)
   requires — and the modal did not appear. Log evidence:
   `Get ags account type result: Full` at 18:15:53, `Showing AGID account link
   modal` **0 occurrences** in the whole 57 KB log, and a screenshot of the
   character-select screen (`ELEGIR PERSONAJE`, character `Azoth_Dev`) with no
   modal over it. So both switches reach the client and the dialog is suppressed.
   Not measured: whether *either* switch alone is sufficient (both were on), and
   whether a `shadow` response still shows the dialog (that would be the reverse
   A/B, and it needs the gitignored `tokens.json` override to force it).
2. **Does a patch pak actually win?** One edited `versionmodals.loc.xml`, one
   launch, read the dialog title on screen. That settles text editing forever.
3. **What shape does `GetAccountLinkActionCode` want?** 203 is a parse error, so
   it is a shape bug on our side, not a semantic refusal.

## Launch notes measured during that A/B

- **The splash gate is Space, not Enter.** `scripts/session/private-run.py`
  already encodes it: `hold-key.py "New World" 0x39 0.15` (scan 0x39 = Space).
  With Space the client reached character select in ~20 s. Enter (VK 0x0D by
  window message, or scan 0x1C by SendInput) did nothing. That script also
  refuses to send keys when the window rejects focus — keep that guard.
- `ef.py game` runs `Start-NwPrivate.ps1 -Watch`, and the `-Watch` patch set
  applies the world-phase patches ~40 s after launch. Both `-Watch` runs hung at
  `Responding: False` with 104 threads, log frozen right after
  `Failure in initializing Fuel::Iap::IapClient: 14` — the known
  `WaitingForQueuedLogin` failure. A raw
  `powershell -File services/launcher/src/Start-NwPrivate.ps1` (no `-Watch`)
  reached auth, character select and stayed responsive.
- `scripts/gui/post-input.py` (window messages, no focus steal) does not move
  this client through the splash; real SendInput with a scan code does.
