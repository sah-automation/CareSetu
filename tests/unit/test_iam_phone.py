"""PHASE-2 T3: +91 E.164 phone normalization (ticket #54, spec #51 §2.2).

The server normalizes to E.164 ``+91XXXXXXXXXX``; anything else is rejected
with a clear validation error and the country code is never trusted from the
client. Accepted shapes mirror the PWA prototype's ``normalizePhone``.
"""

from __future__ import annotations

import pytest

from modules.iam.domain.exceptions import InvalidPhoneError
from modules.iam.domain.phone import normalize_phone


def test_normalize_accepts_bare_national_number() -> None:
    assert normalize_phone("9876543210") == "+919876543210"


def test_normalize_accepts_country_prefixed_number() -> None:
    assert normalize_phone("919876543210") == "+919876543210"


def test_normalize_accepts_plus_e164_form() -> None:
    assert normalize_phone("+919876543210") == "+919876543210"


def test_normalize_strips_whitespace_and_dashes() -> None:
    assert normalize_phone(" 91-98765 43210 ") == "+919876543210"


def test_normalize_rejects_non_indian_number() -> None:
    with pytest.raises(InvalidPhoneError):
        normalize_phone("14445556666")


def test_normalize_rejects_landline_first_digit() -> None:
    with pytest.raises(InvalidPhoneError):
        normalize_phone("01234567890")


@pytest.mark.parametrize("bad", ["", "12345", "987654321", "98765432101", "abcd", "00919876543210"])
def test_normalize_rejects_malformed_lengths(bad: str) -> None:
    with pytest.raises(InvalidPhoneError):
        normalize_phone(bad)


def test_normalize_rejects_starting_digit_under_six() -> None:
    with pytest.raises(InvalidPhoneError):
        normalize_phone("5876543210")


def test_error_message_is_human_safe() -> None:
    with pytest.raises(InvalidPhoneError, match="valid 10-digit Indian mobile number"):
        normalize_phone("14445556666")
