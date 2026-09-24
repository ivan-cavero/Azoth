"""Canonical local-player identity shared by every login surface.

The client carries the same persona and character from Omni token exchange
through getlogininfo, the queue handoff and Javelin V3 registration. Keeping
separate placeholders on those surfaces makes the selected character differ
from the one handed to the world server.
"""

from __future__ import annotations

AZOTH_CHARACTER_ID = "11111111-1111-1111-1111-111111111111"
AZOTH_PERSONA = "amzn1.developerPersonaId.fc906c07-42a2-2dd1-f59f-9c56cf4f212c"
AZOTH_STEAM_ID = "76561197960287930"
AZOTH_STEAM_APP_ID = 1063730
