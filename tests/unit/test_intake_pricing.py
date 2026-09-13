"""PHASE-7 T02 (#399): per-model AI pricing helper - real cost on metered jobs.

The helper computes ``cost_paise`` from the provider's reported token usage
(the metering seam, #398) off a per-model price table. Pins:

- The formula: ``cost_paise = input_tokens * price_in + output_tokens * price_out``.
- Sub-paise cost fractions round half-up so a call costing any fraction of a
  paise still meters at least 1 paise.
- A free model (no table entry) records real 0 on top of a non-zero usage.
- An unknown model records 0 rather than inventing a price.
- ``PRICING_TABLE`` starts paid-only/empty so the mock's real 0 usage records 0.
"""

from __future__ import annotations

from decimal import Decimal

from modules.intake.pricing import PRICING_TABLE, ModelPrice, compute_cost_paise

_PAID = "paid-structurer"


def _table() -> dict[str, ModelPrice]:
    return {
        _PAID: ModelPrice(
            price_in_paise=Decimal("0.02"),
            price_out_paise=Decimal("0.06"),
        ),
    }


def test_unknown_model_costs_zero_never_an_invented_price() -> None:
    """An unlisted model costs 0 - a paid model must carry an entry to be
    metered; the helper never fabricates one."""
    assert compute_cost_paise(_PAID, input_tokens=800, output_tokens=200) == 0


def test_formula_computes_paise_from_a_table_entry(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """cost_paise = input_tokens * price_in + output_tokens * price_out."""
    monkeypatch.setattr("modules.intake.pricing.PRICING_TABLE", _table())
    assert (
        compute_cost_paise(_PAID, input_tokens=800, output_tokens=200)
        == 800 * Decimal("0.02") + 200 * Decimal("0.06")
        == 28
    )


def test_input_only_and_output_only_calls_bill_their_own_leg(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("modules.intake.pricing.PRICING_TABLE", _table())
    assert compute_cost_paise(_PAID, input_tokens=1_000, output_tokens=0) == 20
    assert compute_cost_paise(_PAID, input_tokens=0, output_tokens=500) == 30


def test_sub_paise_fraction_rounds_half_up(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A fractional paise rounds half-up to the nearest paise - at least half a
    paise meters 1 paise, just under half meters 0 (never a fabricated charge)."""
    monkeypatch.setattr(
        "modules.intake.pricing.PRICING_TABLE",
        {"cheap": ModelPrice(price_in_paise=Decimal("0.0001"), price_out_paise=Decimal("0.0001"))},
    )
    assert compute_cost_paise("cheap", input_tokens=3_000, output_tokens=2_000) == 1
    assert compute_cost_paise("cheap", input_tokens=4_999, output_tokens=0) == 0


def test_free_model_with_no_table_entry_costs_zero() -> None:
    """A free model is simply absent from the table, so even a non-zero reported
    usage records 0 - the table never needs a 0-price entry."""
    assert compute_cost_paise("mock-model", input_tokens=0, output_tokens=0) == 0
    assert compute_cost_paise("mock-model", input_tokens=900, output_tokens=150) == 0


def test_pricing_table_starts_paid_only_so_mock_usage_is_real_zero() -> None:
    """The table is documented paid-only and empty at launch - the mock's real
    0 usage records 0; a fabricated constant would be a regression."""
    assert PRICING_TABLE == {}
    assert compute_cost_paise("mock-model", input_tokens=0, output_tokens=0) == 0


def test_price_fields_are_decimal_paise_per_token() -> None:
    """Price fields are Decimal paise-per-token so sub-paise fractions survive
    the integer ``cost_paise`` column."""
    price = ModelPrice(price_in_paise=Decimal("0.02"), price_out_paise=Decimal("0.06"))
    assert isinstance(price.price_in_paise, Decimal)
    assert isinstance(price.price_out_paise, Decimal)
