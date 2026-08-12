"""MOD-001: phone normalization (PHASE-2 T3, ticket #54, FEAT-001).

The +91-only launch scope normalizes a caller's local phone forms to the
Indian E.164 ``+91XXXXXXXXXX`` (spec #51 §2.2). The country code is derived
server-side from the normalized number and never trusted from the client.

Accepted input shapes (matching the PWA prototype's ``normalizePhone``):
a bare 10-digit national number, or the same with the 91 country prefix.
Everything else - foreign numbers, short/long forms, landlines - is rejected
with ``InvalidPhoneError`` so the gateway answers a clear validation error.
"""

from __future__ import annotations

import re

from modules.iam.domain.exceptions import InvalidPhoneError

_INDIA_COUNTRY_CODE = "91"
_NATIONAL_LENGTH = 10
_MOBILE_FIRST_DIGITS = frozenset("6789")

_NATIONAL_ONLY = re.compile(rf"^[0-9]{{{_NATIONAL_LENGTH}}}$")
_COUNTRY_PREFIXED = re.compile(rf"^91[0-9]{{{_NATIONAL_LENGTH}}}$")

_INVALID_MESSAGE = (
    "phone must be a valid 10-digit Indian mobile number starting with 6-9; "
    "it is normalized to +91 E.164 server-side and the country code is never "
    "trusted from the client"
)


def normalize_phone(raw: str) -> str:
    """Normalize a local phone form to E.164 ``+91XXXXXXXXXX``.

    Accepts ``9876543210`` (10 national digits starting with 6-9) and
    ``919876543210`` (with the 91 country prefix); non-digit characters are
    ignored (matching the PWA prototype's ``normalizePhone``). Raises
    ``InvalidPhoneError`` for anything else so callers get one clear
    validation error.
    """
    digits = "".join(ch for ch in raw if ch.isdigit())
    if _COUNTRY_PREFIXED.fullmatch(digits) is not None:
        digits = digits[2:]
    if _NATIONAL_ONLY.fullmatch(digits) is None or digits[0] not in _MOBILE_FIRST_DIGITS:
        raise InvalidPhoneError(_INVALID_MESSAGE)
    return f"+{_INDIA_COUNTRY_CODE}{digits}"
