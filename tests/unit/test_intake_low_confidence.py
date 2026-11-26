"""PHASE-7 T02: low_confidence boundary derivation (ticket #346).

The ``low_confidence`` flag is a *derived* property, never a state. Boundary
tested at the AMB-006 / ADR-0001 0.70 threshold: at-or-above is clean,
strictly-below is flagged, missing (None) is flagged.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from modules.intake.domain.presummary_machine import (
    LOW_CONFIDENCE_THRESHOLD,
    is_low_confidence,
)


def test_missing_confidence_is_flagged() -> None:
    assert is_low_confidence(None) is True


def test_strictly_below_threshold_is_flagged() -> None:
    assert is_low_confidence(Decimal("0.6999")) is True
    assert is_low_confidence(0.69) is True


def test_at_threshold_is_clean() -> None:
    assert is_low_confidence(LOW_CONFIDENCE_THRESHOLD) is False
    assert is_low_confidence(Decimal("0.70")) is False


def test_above_threshold_is_clean() -> None:
    assert is_low_confidence(Decimal("0.7001")) is False
    assert is_low_confidence(0.71) is False
    assert is_low_confidence(1.0) is False


def test_zero_and_below_are_flagged() -> None:
    assert is_low_confidence(Decimal("0.0")) is True
    assert is_low_confidence(0.0) is True


def test_float_and_decimal_agree_at_boundary() -> None:
    assert is_low_confidence(0.70) is False
    assert is_low_confidence(Decimal("0.70")) is False
    assert is_low_confidence(0.6999999999) is True
    assert is_low_confidence(Decimal("0.6999")) is True


@pytest.mark.parametrize(
    "confidence,expected",
    [
        (None, True),
        (Decimal("0.00"), True),
        (Decimal("0.50"), True),
        (Decimal("0.6999"), True),
        (Decimal("0.70"), False),
        (Decimal("0.7001"), False),
        (Decimal("0.85"), False),
        (Decimal("1.00"), False),
    ],
)
def test_low_confidence_matrix(confidence, expected: bool) -> None:
    assert is_low_confidence(confidence) is expected
