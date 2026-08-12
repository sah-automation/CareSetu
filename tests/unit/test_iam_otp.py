"""PHASE-2 T3: OTP challenge primitives (ticket #54, spec #51 §2.4).

The stored value is a memory-hard hash of the 6-digit code with a per-challenge
random salt - values are hashed at rest, never logged, and a leaked hash column
cannot be brute-forced offline. Tests pin the format, the round-trip, and the
tamper/wrong-code rejections without touching a database.
"""

from __future__ import annotations

import re

from modules.iam.domain.otp import (
    MAX_ATTEMPTS,
    OTP_LENGTH,
    OTP_TTL_SECONDS,
    RESEND_COOLDOWN_SECONDS,
    generate_otp,
    hash_otp,
    verify_otp,
)

_STORED_PATTERN = re.compile(r"^scrypt\$16384\$8\$1\$[0-9a-f]{32}\$[0-9a-f]{64}$")


def test_challenge_contract_constants() -> None:
    assert OTP_LENGTH == 6
    assert OTP_TTL_SECONDS == 300
    assert RESEND_COOLDOWN_SECONDS == 60
    assert MAX_ATTEMPTS == 5


def test_generate_otp_is_six_numeric_digits() -> None:
    otp = generate_otp()

    assert re.fullmatch(r"[0-9]{6}", otp) is not None


def test_generate_otp_produces_different_codes() -> None:
    codes = {generate_otp() for _ in range(50)}

    assert len(codes) > 1


def test_hash_otp_never_stores_the_plaintext() -> None:
    otp = "123456"

    stored = hash_otp(otp)

    assert otp not in stored


def test_hash_otp_shape_carries_parameters_and_salt() -> None:
    stored = hash_otp("123456")

    assert _STORED_PATTERN.match(stored) is not None


def test_hash_otp_is_salted_so_identical_codes_differ() -> None:
    assert hash_otp("123456") != hash_otp("123456")


def test_verify_otp_accepts_the_right_code() -> None:
    stored = hash_otp("654321")

    assert verify_otp("654321", stored) is True


def test_verify_otp_rejects_a_wrong_code() -> None:
    stored = hash_otp("654321")

    assert verify_otp("654320", stored) is False


def test_verify_otp_rejects_malformed_stored_values() -> None:
    assert verify_otp("654321", "not-a-hash") is False
    assert verify_otp("654321", "sha256$aaaa$bbbb") is False
    assert verify_otp("654321", "scrypt$16384$8$1$zzzz$ffff") is False


def test_verify_otp_rejects_truncated_hash() -> None:
    stored = hash_otp("654321")

    assert verify_otp("654321", stored[:-4]) is False
