"""PHASE-14B T01 (#762): shared plain-text normalizer and write boundaries.

The normalizer is the only free-text write treatment: NFKC normalization,
control-character removal, whitespace collapse, and a maximum length. It is
not an HTML sanitizer; React escaping remains the display rule. These tests
also pin the operator decision reason, partner registration fields, directory
pick source, and care draft-rejection reason at their request-model boundaries.
"""

from __future__ import annotations

import pytest

from app.gateway.plain_text import DEFAULT_MAX_LENGTH, normalize_plain_text
from modules.care.adapters.routes import RxRejectRequest
from modules.partner.adapters.routes import (
    OperatorDecisionRequest,
    PartnerSelectRequest,
    RegisterPartnerRequest,
)


def test_nfkc_normalizes_compatibility_characters() -> None:
    full_width = "\uff26\uff55\uff4c\uff4c\uff0d\uff37\uff49\uff44\uff54\uff48"

    assert normalize_plain_text(full_width) == "Full-Width"
    assert normalize_plain_text("e\u0301") == "\u00e9"
    assert normalize_plain_text("\ufb01ne") == "fine"


def test_control_characters_are_removed() -> None:
    assert normalize_plain_text("a\x00b\x07c\x1fd") == "abcd"


def test_invisible_format_characters_are_removed() -> None:
    assert normalize_plain_text("a\u200bb\u202ec\ufeff") == "abc"
    assert normalize_plain_text(" \u200b\u202e ") == ""


def test_indic_zero_width_joiners_are_preserved() -> None:
    value = "\u0915\u200d\u0937"

    assert normalize_plain_text(value) == value


def test_whitespace_control_characters_become_word_separators() -> None:
    assert normalize_plain_text("one\ntwo\tthree\r\nfour") == "one two three four"


def test_whitespace_is_collapsed_and_trimmed() -> None:
    assert normalize_plain_text("  too   many \t spaces \n here  ") == "too many spaces here"
    assert normalize_plain_text("   \t\n  ") == ""


def test_maximum_length_truncates_after_normalization() -> None:
    assert normalize_plain_text("  abcdefghij  ", max_length=5) == "abcde"
    assert normalize_plain_text("short", max_length=10) == "short"


def test_default_maximum_length_is_enforced() -> None:
    normalized = normalize_plain_text("x" * (DEFAULT_MAX_LENGTH + 25))

    assert len(normalized) == DEFAULT_MAX_LENGTH


def test_max_length_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_length must be at least 1"):
        normalize_plain_text("text", max_length=0)


def test_normalization_is_idempotent() -> None:
    messy = "  \uff26\uff49\uff4e\uff45\x00\n\n  text\twith   spaces  "

    once = normalize_plain_text(messy)
    twice = normalize_plain_text(once)

    assert twice == once


def test_operator_decision_reason_is_normalized_at_the_request_boundary() -> None:
    request = OperatorDecisionRequest(approve=False, reason="  forged\x00 document \n ")

    assert request.reason == "forged document"


def test_operator_decision_reason_stays_none_when_absent() -> None:
    request = OperatorDecisionRequest(approve=True)

    assert request.reason is None


def test_invisible_only_operator_reason_normalizes_to_blank() -> None:
    request = OperatorDecisionRequest(approve=False, reason=" \u200b\u202e ")

    assert request.reason == ""


def test_care_rejection_reason_is_normalized_at_the_request_boundary() -> None:
    request = RxRejectRequest(reason="  wrong\x00 dosage \n please re-check ")

    assert request.reason == "wrong dosage please re-check"


def test_partner_registration_free_text_is_normalized() -> None:
    request = RegisterPartnerRequest(
        phone="9876543210",
        partner_type="doctor",
        practice_name="  Shanti\x00 Clinic ",
        practice_address="  Station  Road,\n Daltonganj ",
        practice_latitude=24.04,
        practice_longitude=84.06,
    )

    assert request.practice_name == "Shanti Clinic"
    assert request.practice_address == "Station Road, Daltonganj"


def test_directory_select_source_is_normalized() -> None:
    request = PartnerSelectRequest(partner_id=1, source="  search\x00 card ")

    assert request.source == "search card"
