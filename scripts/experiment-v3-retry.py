#!/usr/bin/env python3
"""A/B the V3-retry answer: retry bodies want the 88B response AGAIN.

Live evidence 2026-09-19 19:20-19:26: the client re-registers (V3 retry
tagged format, 1115B chunked x2 + 161B) every ~90s right after each
InGame timeout. Our handle_app_data skips V3 when v3_done=True, so the
retries go unanswered; the client then restarts the whole login cycle
(UI shows queue position cycling 0<->1).

This experiment: answer EVERY ch0>64 V3-shaped record with a fresh 88B
RegistrationResponseMsg (new session token echo each time) + CT_ACKS.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "world" / "src"))

# The change is in services/world/src/azoth_world/rep.py handle_app_data:
# replace `if not v3_done and any(...)` with always answering V3-shaped
# records but at most once per ~5s (retries are 1/s at handshake, but the
# post-InGame retries are 90s apart; a 5s throttle stops the old 700-reply
# storm while always answering genuine re-registrations).
print(__doc__)
