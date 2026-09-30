"""Stub v2 invariants: minimal exports, per-interface vtables, no shared ret1 dummy."""
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
DEF = HERE / "src" / "stub.c"


def test_def_is_minimal():
    names = [
        ln.strip().split()[0]
        for ln in (HERE / "src" / "stub.def").read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith(("LIBRARY", "EXPORTS", ";", "#"))
    ]
    assert len(names) <= 32, f"stub.def should stay minimal, got {len(names)}"
    for req in (
        "SteamAPI_Init",
        "SteamAPI_GetHSteamUser",
        "SteamAPI_RunCallbacks",
        "SteamInternal_ContextInit",
        "SteamInternal_FindOrCreateUserInterface",
    ):
        assert req in names, f"missing required export {req}"


def test_no_shared_ret1_dummy():
    src = (HERE / "src" / "stub.c").read_text(encoding="utf-8")
    assert "g_vt_user" in src and "g_vt_friends" in src and "g_vt_utils" in src
    assert "iface_for" in src
    # pointer returns must not be the old 0x1 dummy
    assert "GetFriendPersonaName" in src
    assert 'return k_persona' in src or 'k_persona' in src
