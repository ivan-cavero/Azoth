"""Javelin wire library (Carrier framing + V3 registration).

Derived from the AzCore/Javelin decompilation; see research/docs/REP-PROTOCOL.md.
Only the world service imports this: the gateway never interprets Carrier.
"""

from .alc import (
    AlcInput,
    TYPE_ALC_INPUT,
    alc_body_from_record,
    parse_alc_input,
)
from .bitstream import BitStream, BitStreamError, BitStreamWriter
from .frame import (
    CarrierEnvelope,
    MessageFlags,
    MessageRecord,
    MarshalState,
    SystemMessageId,
    marshal_datagram,
    marshal_record,
    parse_datagram,
    parse_envelope,
)
from .v3 import (
    V3RegistrationRequest,
    V3RegistrationResponse,
    parse_v3_request,
    parse_v3_request_or_lenient,
    parse_v3_request_retry,
    parse_v3_request_lenient,
    serialize_v3_request,
)

__all__ = [
    "AlcInput",
    "TYPE_ALC_INPUT",
    "alc_body_from_record",
    "parse_alc_input",
    "BitStream",
    "BitStreamError",
    "BitStreamWriter",
    "CarrierEnvelope",
    "MessageFlags",
    "MessageRecord",
    "MarshalState",
    "SystemMessageId",
    "marshal_datagram",
    "marshal_record",
    "parse_datagram",
    "parse_envelope",
    "V3RegistrationRequest",
    "V3RegistrationResponse",
    "parse_v3_request",
    "parse_v3_request_or_lenient",
    "parse_v3_request_retry",
    "parse_v3_request_lenient",
    "serialize_v3_request",
]
