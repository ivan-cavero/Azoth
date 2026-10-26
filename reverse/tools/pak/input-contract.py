#!/usr/bin/env python3
"""Derive the client's own input contract and join it to the message registry.

WHY THIS EXISTS
===============
A live labelled session can say *when* traffic appears, but it cannot say *which key*
produced it unless the key is chosen from the client's own binding table rather than
guessed. And a hand-written list of "surfaces" is a guess about what the game contains:
the first version of this tool carried thirteen of them and missed the map, the journal,
the social panel, guilds, season rewards, tokens, emotes, the warboard, raids, equipment
sets, fishing and housing. The client already knows its own surfaces, so this tool derives
them instead of curating them.

Three shipped sources, joined:

  * `libs/config/defaultprofile.xml` (+ its `<include>` files) -- action maps, and for every
    action the keyboard/gamepad input that fires it;
  * `sharedassets/springboardentitites/playerdata/cage/playerinput_*.actionlist` -- the
    conditions that gate an action on game state (`IfInput InputName="ui_interact"`,
    `IfIsGathering`, `IfShouldCraft`, ...);
  * `research/derived/wire-type-names.json` -- every message this build registers, with its
    wire type. `XComponentServerFacet_M` is what the CLIENT SENDS; `XComponentClientFacet_M`
    is what the SERVER sends.

The join is the client's own naming, not a guess: the action `toggleSeasonsRewardsComponent`
and the family `SeasonsRewardsComponent` are the same word, so a surface derived from the
action can be matched to the messages that serve it.

WHAT IT REPORTS
---------------
`--out` writes one JSON document:

  * `actions`        -- action name -> inputs bound to it, and the maps that bind them;
  * `actionlists`    -- action-list file -> its named conditions, inputs and predicates;
  * `ui_surfaces`    -- every UI surface the client's own action names imply, with its keys;
  * `facet_families` -- component family -> the messages the client sends and the server
                        sends, each with its wire type;
  * `surface_contract` -- surface -> keys + the exact server-side messages that serve it.

A surface whose family does not resolve is reported, not dropped: it means the client has
a UI panel with no matching message family, which is itself a finding.

Usage:
    python ef.py re input-contract --out research/derived/input-contract.json
    python ef.py re input-contract --check
    python ef.py re input-contract --surfaces      # just the surface -> messages table
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import default_paths  # noqa: E402
from pakread import read_entry  # noqa: E402

PROFILE_PAK = "SharedDataStrm-part4.pak"
ACTIONLIST_PAK = "SharedDataStrm-part7.pak"
ROOT_PROFILES = ("libs/config/defaultprofile.xml", "libs/config/advancedprofile.xml")
ACTIONLIST_DIR = "sharedassets/springboardentitites/playerdata/cage/"

REPO = Path(__file__).resolve().parents[3]
NAMES_FILE = REPO / "research" / "derived" / "wire-type-names.json"

# Every action list the client ships for the player. Reading them all is cheaper than
# deciding which ones matter, and the gate is what makes a key press meaningful.
ACTIONLISTS = (
    "playerinput_combat", "playerinput_craft", "playerinput_gather",
    "playerinput_interact", "playerinput_mount", "playerinput_navigation",
    "playerinput_uiaction", "playeractions_postureinput",
)

# A UI surface is an action that opens or closes a panel. These are the client's own
# naming shapes for that, so the derivation follows the binary rather than a list.
_SURFACE_ACTION = re.compile(
    r"^(?:toggle|open)([A-Z].*?)(?:Component|Window|InGame|ComponentF10)?$")
_NOT_A_SURFACE = {"toggleMenuComponentF10", "toggle_headgear", "togglePvpFlag",
                  "toggleMicrophoneOn", "toggleMicrophoneOff", "toggleChatComponent",
                  "toggleChatComponentSlash", "toggleMoveSpeed", "toggleGENA",
                  "toggleGrid", "openStyleGuide", "openWarTutorial", "open_purchase_history",
                  "toggle_respawn_warboard", "toggle_free_cam", "toggleEquipmentSetWindow"}

_INCLUDE = re.compile(r'filename="([^"]+)"')

# Surfaces whose action name does not contain their family name. Two kinds, and the
# difference is the evidence word: `derived` is the client's own word spelled differently
# (Inventory/Inventories); `inferred` is a judgement call from what the family's messages
# do. Each entry records which it is, so a reader can tell a name match from a guess.
ALIASES: dict[str, tuple[list[str], str]] = {
    "Inventory": (["Inventories"], "derived"),
    "MapObjectives": (["Objectives"], "derived"),
    "Journal": (["Objectives", "Contracts"], "inferred"),
    "Skills": (["Ability", "Attribute", "ProgressionPoint", "CategoricalProgression"],
               "inferred"),
    "Token": (["Entitlement"], "inferred"),
    "GearSet": (["Paperdoll"], "inferred"),
    "Map": (["TerritoryInteractor", "Aoi", "Groups"], "inferred"),
    "Warboard": (["TerritoryInteractor", "Groups"], "inferred"),
    "Emote": (["Social"], "inferred"),
    "Raid": (["Groups", "RaidSetup"], "inferred"),
}

# The menus a player names, mapped to the component families that serve them.
#
# WHY THIS TABLE EXISTS AT ALL: a live labelled session shows that a panel emits NO
# traffic, and that fact alone does NOT mean the panel is local. It means the panel had no
# state to ask for. The proof is in this same log: `RequestBatchCreateGuildInvites` was
# sent when the player actually invited somebody, not when the panel was merely opened;
# `RequestExecuteTradingPostTransaction` was sent when the player used the trading post.
# So the surface -> family mapping has to come from the registry, and a silent window is
# reported as "no request while idle", never as "no server contract".
MENU_FAMILIES: dict[str, tuple[list[str], str]] = {
    "compania": (["Guilds"], "crear, gestionar e invitar; RequestBatchCreateGuildInvites"),
    "party-y-marcas": (["Groups"], "RequestPing, RequestTargetPing, raid members"),
    "personaje": (["Paperdoll", "Attribute", "Ability", "Progression",
                   "ProgressionPoint", "CategoricalProgression", "Vitals"],
                  "equipo, atributos, skills de arma, maestria"),
    "montura": (["Mount"], "SummonMount, DismissMount, OnEnableMounts"),
    "temporada-actividades": (["SeasonsRewards", "RewardTrack", "GameModeParticipant"],
                              "tarjetas, reroll, redencion, lobbies de actividad"),
    "tienda-tokens": (["Entitlement", "PlayerAppearance"],
                      "InitializeTransaction, RequestServerGetEntitlements"),
    "subasta": (["CurrencyConversion", "P2PTrade", "PlayerTrade"],
                "RequestExecuteTradingPostTransaction"),
    "diario": (["Objectives", "Contracts", "ObjectiveInteractor"],
               "objetivos, contratos, pinning"),
    "mapa": (["TerritoryInteractor", "TerritoryDetector", "Aoi", "Groups"],
             "territorio, desbloqueo, marcas de party"),
    "inventario-storage": (["Inventories", "GlobalStorage", "Container"],
                           "QueryInventories, GetItems, storage search"),
    "fabricar-salvage": (["Crafting"], "SetCraftingDetails, InitiateSalvage"),
    "social-chat-voz": (["Social", "Chat", "VoiceChat"],
                        "amigos, titulos, chat, voz"),
}


def _pak_entries(pak: str) -> dict[str, str]:
    """Lowercased entry name -> the entry's real, case-sensitive name in the PAK.

    A profile names its include `libs/config/includes/uiShared.inputprofilexml` while the
    shipped entry is `libs/config/includes/uishared.xml`, and a ZIP central directory is
    case-sensitive even on Windows. Resolving through this index keeps the extraction
    working without hand-maintaining a rename table.
    """
    path = default_paths()["install"] / "assets" / pak
    with zipfile.ZipFile(path) as archive:
        return {name.lower(): name for name in archive.namelist()}


def _profile_entries() -> list[str]:
    """Root profiles plus every include they name, resolved to real PAK entries."""
    index = _pak_entries(PROFILE_PAK)
    entries: list[str] = []
    unresolved: list[str] = []
    pending = list(ROOT_PROFILES)
    seen: set[str] = set()
    while pending:
        wanted = pending.pop(0)
        resolved = index.get(wanted.lower())
        if resolved is None:
            unresolved.append(wanted)
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        entries.append(resolved)
        text = read_entry(PROFILE_PAK, resolved)[0].decode("utf-8", "replace")
        for name in _INCLUDE.findall(text):
            pending.append(name if name.endswith(".xml")
                           else name.rsplit(".", 1)[0] + ".xml")
    for name in unresolved:
        print(f"  unresolved include: {name}", file=sys.stderr)
    return entries


def _parse_profile(text: str) -> dict:
    """Return {action name: {maps, keyboard, press, hold, release}} for one profile."""
    actions: dict[str, dict] = {}
    root = ET.fromstring(text)
    for map_node in root.iter("actionmap"):
        map_name = map_node.get("name", "?")
        for action in map_node.findall("action"):
            name = action.get("name")
            if not name:
                continue
            record = actions.setdefault(name, {"maps": [], "keyboard": [],
                                               "press": False, "hold": False,
                                               "release": False})
            if map_name not in record["maps"]:
                record["maps"].append(map_name)
            key = action.get("keyboard")
            if key and key not in record["keyboard"]:
                record["keyboard"].append(key)
            for inputdata in action.findall("./keyboard/inputdata"):
                value = inputdata.get("input")
                if value and value not in record["keyboard"]:
                    record["keyboard"].append(value)
            for flag in ("press", "hold", "release"):
                if action.get(f"on{flag.capitalize()}") == "1":
                    record[flag] = True
    return actions


def _parse_actionlist(text: str) -> list[dict]:
    """Return the named conditions of one action list, with inputs and predicates."""
    conditions: list[dict] = []
    root = ET.fromstring(text)
    holder = root.find("Conditions")
    if holder is None:
        return conditions
    for node in list(holder):
        inputs = [n.get("InputName") for n in node.iter("IfInput") if n.get("InputName")]
        predicates = sorted({child.tag for child in node.iter()
                             if child.tag.startswith("If") and child.tag != "IfInput"})
        conditions.append({"name": node.get("Name") or node.get("name"), "inputs": inputs,
                           "predicates": predicates})
    return conditions


def load_registry(path: Path = NAMES_FILE) -> dict[str, dict]:
    """Component family -> {"server": [...], "client": [...]} from the wire-type registry.

    The split matters and is the whole point of the join: a `ServerFacet` message is one the
    CLIENT sends and the server must answer; a `ClientFacet` message is one the SERVER sends.
    Conflating them is how a "contract" ends up describing the wrong direction.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    families: dict[str, dict] = {}
    pattern = re.compile(r"^(?P<fam>.+?)Component(?P<side>Server|Client)Facet_(?P<method>.+)$")
    for row in document.get("names", []):
        name = row.get("name")
        if not name:
            continue
        match = pattern.match(name)
        if not match:
            continue
        family = match.group("fam")
        side = "server" if match.group("side") == "Server" else "client"
        bucket = families.setdefault(family, {"server": [], "client": []})
        bucket[side].append({"wire_type": f"0x{row['wire_type']:x}",
                             "method": match.group("method"), "name": name})
    for bucket in families.values():
        for side in ("server", "client"):
            bucket[side].sort(key=lambda m: m["method"])
    return families


def derive_surfaces(actions: dict[str, dict], families: dict[str, dict]) -> dict[str, dict]:
    """Every UI surface the client's action names imply, with its keys and its messages.

    The match is the client's own word: `toggleSeasonsRewardsComponent` -> family
    `SeasonsRewards`. A surface that resolves to no family is kept with an empty message
    list and reported, because a panel with no server messages is a real finding.
    """
    surfaces: dict[str, dict] = {}
    for name, record in actions.items():
        if name in _NOT_A_SURFACE:
            continue
        match = _SURFACE_ACTION.match(name)
        if not match:
            continue
        stem = match.group(1)
        family = next((f for f in families
                       if f.lower() == stem.lower()
                       or f.lower().startswith(stem.lower())
                       or stem.lower().startswith(f.lower())), None)
        entry = surfaces.setdefault(stem, {"actions": [], "keys": [], "families": [],
                                           "maps": [], "family_source": "derived"})
        if name not in entry["actions"]:
            entry["actions"].append(name)
        for key in record["keyboard"]:
            if key not in entry["keys"]:
                entry["keys"].append(key)
        for m in record["maps"]:
            if m not in entry["maps"]:
                entry["maps"].append(m)
        if family and family not in entry["families"]:
            entry["families"].append(family)

    # Fill the gaps from the alias table, and say which kind of match each one is.
    for stem, entry in surfaces.items():
        alias = ALIASES.get(stem)
        if alias is None or entry["families"]:
            continue
        names, source = alias
        entry["families"] = [f for f in names if f in families]
        entry["family_source"] = source if entry["families"] else "unresolved"

    for entry in surfaces.values():
        entry["server_messages"] = [
            message for family in entry["families"]
            for message in families[family]["server"]]
        entry["server_message_count"] = len(entry["server_messages"])
    return surfaces


def build() -> dict:
    actions: dict[str, dict] = {}
    profiles: list[str] = []
    for entry in _profile_entries():
        profiles.append(entry)
        for name, record in _parse_profile(read_entry(PROFILE_PAK, entry)[0]
                                           .decode("utf-8", "replace")).items():
            merged = actions.setdefault(name, {"maps": [], "keyboard": [],
                                               "press": False, "hold": False,
                                               "release": False})
            for key in ("maps", "keyboard"):
                for value in record[key]:
                    if value not in merged[key]:
                        merged[key].append(value)
            for flag in ("press", "hold", "release"):
                merged[flag] = merged[flag] or record[flag]

    actionlists: dict[str, list[dict]] = {}
    index = _pak_entries(ACTIONLIST_PAK)
    for stem in ACTIONLISTS:
        entry = index.get(f"{ACTIONLIST_DIR}{stem}.actionlist".lower())
        if entry is None:
            print(f"  missing action list: {stem}", file=sys.stderr)
            continue
        actionlists[stem] = _parse_actionlist(
            read_entry(ACTIONLIST_PAK, entry)[0].decode("utf-8", "replace"))

    families = load_registry()
    menus = {
        name: {
            "families": [f for f in fams if f in families],
            "note": note,
            "server_message_count": sum(len(families[f]["server"]) for f in fams
                                        if f in families),
        }
        for name, (fams, note) in MENU_FAMILIES.items()
    }
    return {
        "$comment": "The client's own input contract and the message families that serve it, "
                    "derived from the shipped PAK profiles, action lists and wire-type "
                    "registry. Regenerate with `python ef.py re input-contract`. 'keys' are "
                    "raw keyboard names, not scan codes; scan codes live in "
                    "scripts/gui/hold-key.py. In `surface_contract`, server_messages are what "
                    "the CLIENT sends (XComponentServerFacet_M); the server's answers are "
                    "XComponentClientFacet_M and are listed under facet_families.",
        "profiles": profiles,
        "actions": actions,
        "actionlists": actionlists,
        "facet_families": families,
        "surface_contract": derive_surfaces(actions, families),
        "menu_contract": menus,
    }


# Measured facts this extraction must keep reproducing. Each was read off the shipped
# profile by hand before the tool existed; if a client update moves a binding, the
# self-test fails instead of the lab silently pressing the wrong key.
CHECKS: list[tuple[str, str, str]] = [
    ("tab", "toggleInventoryWindow", "inventory opens on tab"),
    ("k", "toggleSkillsComponent", "skills panel opens on k"),
    ("m", "toggleMapComponent", "the map opens on m"),
    ("j", "toggleJournalComponent", "the journal opens on j"),
    ("o", "toggleSocialWindow", "the social panel opens on o"),
    ("f4", "toggleGuildComponent", "guilds open on f4"),
    ("f9", "toggleSeasonsRewardsComponent", "season rewards open on f9"),
    ("f11", "toggleTokenWindow", "the token window opens on f11"),
    ("p", "toggleEmoteWindow", "emotes open on p"),
    ("n", "toggleWarboardInGame", "the warboard opens on n"),
    ("l", "toggleRaidWindow", "the raid window opens on l"),
    ("comma", "toggleEquipmentSetWindow", "equipment sets open on comma"),
    ("e", "ui_interact", "the interact action is bound to e"),
    ("q", "ability1", "first ability is q"),
    ("r", "ability2", "second ability is r"),
    ("f", "ability3", "third ability is f"),
    ("x", "mount_summon", "the mount is summoned on x"),
    ("f3", "fishing_activate", "fishing starts on f3"),
    ("y", "makeCampOn", "camp is made on y"),
    ("u", "togglePvpFlag", "the pvp flag toggles on u"),
    ("1", "dialogueOption1", "dialogue option 1 is the 1 key"),
    ("0", "dialogueOption10", "dialogue option 10 is the 0 key"),
    ("np_1", "equipLoadout1", "loadout 1 is numpad 1"),
    ("tilde", "sheathe_hold", "sheathe is a hold on tilde"),
    ("lshift", "dodge", "dodge is left shift"),
    ("g", "rune_ability", "the rune ability is g"),
]


def check() -> int:
    document = build()
    actions = document["actions"]
    families = document["facet_families"]
    surfaces = document["surface_contract"]
    results: list[tuple[str, bool]] = []
    for key, action, why in CHECKS:
        record = actions.get(action, {})
        results.append((f"{action} <- {key} ({why})", key in record.get("keyboard", [])))

    # The join must resolve the surfaces that carry real gameplay traffic. Surfaces are
    # named by the ACTION stem (`Skills`, `GearSet`), families by the COMPONENT name
    # (`Ability`, `Paperdoll`), so the two are asserted separately -- asserting a family
    # name against the surface table is how this check first reported nine false failures.
    for surface in ("SeasonsRewards", "Inventory", "FishingBait", "Guild", "Social",
                    "MapObjectives", "Transmog", "ChatComponentUI", "Raid"):
        entry = surfaces.get(surface)
        resolved = bool(entry and entry["families"])
        results.append((f"surface {surface} resolves to a facet family", resolved))
        if resolved:
            results.append((f"  {surface} has server messages ({entry['server_message_count']})",
                            entry["server_message_count"] > 0))

    # And the families behind the gameplay surfaces the request named must exist and carry
    # client->server messages, whatever the surface stem happens to be called.
    for family in ("Paperdoll", "Ability", "Attribute", "Crafting", "P2PTrade",
                   "PlayerTrade", "Conversation", "Mount", "TerritoryInteractor",
                   "ProgressionPoint", "CategoricalProgression", "Entitlement",
                   "Guilds", "Groups"):
        entry = families.get(family)
        results.append((f"family {family} exists with server messages",
                        bool(entry and entry["server"])))

    # The architectural asymmetry this feature measured: five families answer nothing.
    for family in ("Attribute", "Progression", "ProgressionPoint", "CategoricalProgression",
                   "Conversation"):
        entry = families.get(family) or {"server": [], "client": []}
        results.append((f"{family} is confirmed state-only (no client reply)",
                        bool(entry["server"]) and not entry["client"]))

    results.append(("the facet registry splits server and client directions",
                    all("server" in f and "client" in f for f in families.values())))
    results.append((f"registry covers >100 component families (got {len(families)})",
                    len(families) > 100))
    interact = document["actionlists"].get("playerinput_interact", [])
    inputs = [i for condition in interact for i in condition["inputs"]]
    results.append(("actionlist playerinput_interact gates on ui_interact",
                    "ui_interact" in inputs))
    gather = document["actionlists"].get("playerinput_gather", [])
    results.append(("actionlist playerinput_gather carries IfIsGathering",
                    any("IfIsGathering" in c["predicates"] for c in gather)))

    ok = all(value for _, value in results)
    for name, value in results:
        print(f"{'PASS' if value else 'FAIL'} {name}")
    print(f"input-contract check: {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


def print_surfaces(document: dict) -> None:
    surfaces = document["surface_contract"]
    rows = sorted(surfaces.items(), key=lambda kv: -kv[1]["server_message_count"])
    print(f"{len(rows)} UI surfaces derived from the client's own action names\n")
    print(f"{'surface':26} {'keys':16} {'msgs':>5}  {'source':9} families")
    print("-" * 104)
    for stem, entry in rows:
        keys = ",".join(entry["keys"]) or "(gamepad only)"
        fams = ",".join(entry["families"]) or "(no family)"
        print(f"{stem:26} {keys:16} {entry['server_message_count']:5}  "
              f"{entry['family_source']:9} {fams}")
    unresolved = [s for s, e in surfaces.items() if not e["families"]]
    print(f"\n{len(unresolved)} surface(s) with no message family: "
          f"{', '.join(sorted(unresolved)) or 'none'}")


def print_menus(document: dict) -> None:
    """The menu -> families table, which is the question a player actually asks."""
    menus = document["menu_contract"]
    print(f"\n{len(menus)} player-facing menus -> the families that serve them\n")
    print(f"{'menu':24} {'msgs':>5}  families")
    print("-" * 96)
    for name, entry in sorted(menus.items(), key=lambda kv: -kv[1]["server_message_count"]):
        fams = ", ".join(entry["families"]) or "(none resolved)"
        print(f"{name:24} {entry['server_message_count']:5}  {fams}")
        print(f"{'':24}        {entry['note']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", help="write the JSON document here")
    parser.add_argument("--check", action="store_true", help="run the measured self-test")
    parser.add_argument("--surfaces", action="store_true",
                        help="print the surface -> message table")
    args = parser.parse_args()
    if args.check:
        return check()

    document = build()
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {out}: {len(document['actions'])} actions, "
              f"{len(document['actionlists'])} action lists, "
              f"{len(document['facet_families'])} facet families, "
              f"{len(document['surface_contract'])} UI surfaces")
    if args.surfaces or not args.out:
        print_surfaces(document)
        print_menus(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
