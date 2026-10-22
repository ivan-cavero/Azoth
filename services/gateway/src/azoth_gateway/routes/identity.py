"""Canonical local-player identity shared by every login surface.

The client carries the same persona and character from Omni token exchange
through getlogininfo, the queue handoff and Javelin V3 registration. Keeping
separate placeholders on those surfaces makes the selected character differ
from the one handed to the world server.
"""

from __future__ import annotations

import hashlib

AZOTH_CHARACTER_ID = "11111111-1111-1111-1111-111111111111"
AZOTH_PERSONA = "amzn1.developerPersonaId.fc906c07-42a2-2dd1-f59f-9c56cf4f212c"
AZOTH_STEAM_ID = "76561197960287930"
AZOTH_STEAM_APP_ID = 1063730

# PER-CLIENT IDENTITY (two clients, one world server).
#
# Every login used to get the same character, so two private clients were the same
# player on the wire and neither could ever be "the other peer". A client now asks for
# its own identity with the `X-Azoth-Instance` header, which the launcher sets from its
# own instance number. Instance 1 (and any request without the header) keeps the
# historical id, so a single-client run is byte-identical to before.
#
# The derived ids are deterministic on purpose: a restart must return the SAME
# character, or the client's savedata and the world's session disagree.
def character_for_instance(instance: str | int | None) -> str:
    """The character id this client instance should use."""
    try:
        n = int(instance or 0)
    except (TypeError, ValueError):
        return AZOTH_CHARACTER_ID
    if n <= 1:
        return AZOTH_CHARACTER_ID
    digest = hashlib.sha256(f"azoth-character-{n}".encode()).hexdigest()
    # Keep the RFC-4122 v4 shape the client already accepts, but derive every group
    # from the instance so the value is stable and unmistakably synthetic.
    return f"{digest[0:8]}-{digest[8:12]}-4{digest[13:16]}-8{digest[17:20]}-{digest[20:32]}"

def persona_for_instance(instance: str | int | None) -> str:
    """The persona id this client instance should use."""
    try:
        n = int(instance or 0)
    except (TypeError, ValueError):
        return AZOTH_PERSONA
    if n <= 1:
        return AZOTH_PERSONA
    return f"amzn1.developerPersonaId.instance{n}"
