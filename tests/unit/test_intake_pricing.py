"""PHASE-7 T02 (#399) + PHASE-14A B1 (#699): per-model AI pricing helper.

The helper computes ``cost_paise`` from the provider's reported token usage
(the metering seam, #398) off a per-model price table. Pins:

- The formula: ``cost_paise = input_tokens * price_in + output_tokens * price_out``.
- Sub-paise cost fractions round half-up so a call costing any fraction of a
  paise still meters at least 1 paise.
- A KNOWN free model (an explicit 0 entry) records real 0 on non-zero usage and
  is never flagged.
- An UNKNOWN model records 0 and is flagged (a warning), so a missing rate is
  visible rather than silently hidden.
- ``PRICING_TABLE`` is populated from the config default (the free mock is an
  explicit entry), and the effective table resolves lazily from
  ``AI_PRICING_TABLE`` env - a paid model's rate is deployment configuration.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest

from app.config import (
    DEFAULT_AI_PRICING_TABLE,
    Settings,
    get_settings,
    parse_ai_pricing_table,
)
from modules.intake.pricing import PRICING_TABLE, ModelPrice, compute_cost_paise

_PAID = "paid-structurer"


def _table() -> dict[str, ModelPrice]:
    return {
        _PAID: ModelPrice(
            price_in_paise=Decimal("0.02"),
            price_out_paise=Decimal("0.06"),
        ),
    }


def test_unknown_model_costs_zero_and_is_flagged(caplog: pytest.LogCaptureFixture) -> None:
    """An unlisted model costs 0 - the helper never fabricates a price - and the
    miss is logged (warning), never silently hidden. An injected empty table pins
    the branch without depending on the process environment."""
    with caplog.at_level(logging.WARNING, logger="modules.intake.pricing"):
        assert compute_cost_paise(_PAID, input_tokens=800, output_tokens=200, table={}) == 0
    assert any("no rate configured" in record.message for record in caplog.records)


def test_formula_computes_paise_from_a_table_entry() -> None:
    """cost_paise = input_tokens * price_in + output_tokens * price_out."""
    assert (
        compute_cost_paise(_PAID, input_tokens=800, output_tokens=200, table=_table())
        == 800 * Decimal("0.02") + 200 * Decimal("0.06")
        == 28
    )


def test_input_only_and_output_only_calls_bill_their_own_leg() -> None:
    assert compute_cost_paise(_PAID, input_tokens=1_000, output_tokens=0, table=_table()) == 20
    assert compute_cost_paise(_PAID, input_tokens=0, output_tokens=500, table=_table()) == 30


def test_sub_paise_fraction_rounds_half_up() -> None:
    """A fractional paise rounds half-up to the nearest paise - at least half a
    paise meters 1 paise, just under half meters 0 (never a fabricated charge)."""
    cheap = {
        "cheap": ModelPrice(price_in_paise=Decimal("0.0001"), price_out_paise=Decimal("0.0001"))
    }
    assert compute_cost_paise("cheap", input_tokens=3_000, output_tokens=2_000, table=cheap) == 1
    assert compute_cost_paise("cheap", input_tokens=4_999, output_tokens=0, table=cheap) == 0


def test_known_free_model_with_explicit_zero_prices_zero_and_is_not_flagged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A known free model (explicit 0 entry) records real 0 on non-zero usage and
    is never flagged - unlike an unknown model, its 0 is expected."""
    free = {"mock-model": ModelPrice(price_in_paise=Decimal("0"), price_out_paise=Decimal("0"))}
    with caplog.at_level(logging.WARNING, logger="modules.intake.pricing"):
        assert (
            compute_cost_paise("mock-model", input_tokens=900, output_tokens=150, table=free) == 0
        )
    assert caplog.records == []


def test_pricing_table_is_populated_from_config_default_not_hardcoded_empty() -> None:
    """``PRICING_TABLE`` comes from config: the free mock is an explicit entry
    (known-free, never flagged), not an absent row - so it is populated config,
    not a hardcoded empty table."""
    assert PRICING_TABLE != {}
    assert PRICING_TABLE["mock-model"] == ModelPrice(
        price_in_paise=Decimal("0"), price_out_paise=Decimal("0")
    )


def test_resolved_table_reads_ai_pricing_table_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The effective table resolves lazily from Settings/env per call, so a paid
    model's rate is a deployment edit that takes effect without an import freeze."""
    monkeypatch.setenv("AI_PRICING_TABLE", "paid-structurer:0.02:0.06,mock-model:0:0")
    assert compute_cost_paise("paid-structurer", input_tokens=800, output_tokens=200) == 28
    assert compute_cost_paise("mock-model", input_tokens=900, output_tokens=150) == 0


def test_price_fields_are_decimal_paise_per_token() -> None:
    """Price fields are Decimal paise-per-token so sub-paise fractions survive
    the integer ``cost_paise`` column."""
    price = ModelPrice(price_in_paise=Decimal("0.02"), price_out_paise=Decimal("0.06"))
    assert isinstance(price.price_in_paise, Decimal)
    assert isinstance(price.price_out_paise, Decimal)


def test_parse_ai_pricing_table_parses_model_rates() -> None:
    table = parse_ai_pricing_table("a:0.02:0.06, b:0:0 ")
    assert table == {
        "a": (Decimal("0.02"), Decimal("0.06")),
        "b": (Decimal("0"), Decimal("0")),
    }


def test_parse_ai_pricing_table_skips_empty_entries() -> None:
    assert parse_ai_pricing_table("a:1:2, , b:3:4") == {
        "a": (Decimal("1"), Decimal("2")),
        "b": (Decimal("3"), Decimal("4")),
    }


def test_parse_ai_pricing_table_rejects_malformed_entries() -> None:
    with pytest.raises(ValueError, match="malformed AI pricing entry"):
        parse_ai_pricing_table("a:1")
    with pytest.raises(ValueError, match="malformed AI pricing entry"):
        parse_ai_pricing_table("a:x:1")
    with pytest.raises(ValueError, match="non-negative"):
        parse_ai_pricing_table("a:-1:1")


def test_settings_default_ai_pricing_table_matches_config_constant() -> None:
    assert Settings().ai_pricing_table == DEFAULT_AI_PRICING_TABLE


def test_settings_reads_ai_pricing_table_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PRICING_TABLE", "paid-structurer:0.02:0.06")
    assert get_settings().ai_pricing_table == "paid-structurer:0.02:0.06"


def test_settings_rejects_malformed_ai_pricing_table() -> None:
    with pytest.raises(ValueError, match="malformed AI pricing entry"):
        Settings(ai_pricing_table="paid")
