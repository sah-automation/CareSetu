"""MOD-005: per-model AI pricing helper - real cost on metered jobs (PHASE-7 T02 #399).

Computes the ``cost_paise`` a completed ``intake_ai_jobs`` row records from the
provider's reported token usage (the metering seam, #398), per the
launch-pricing formula::

    cost_paise = input_tokens * price_in + output_tokens * price_out

The per-model price table (``PRICING_TABLE``) is populated from deployment
config (PHASE-14A B1, #699): ``AI_PRICING_TABLE`` / :data:`app.config.DEFAULT_AI_PRICING_TABLE`
carries ``model:price_in:price_out`` rates in paise per token, so a paid model's
rate is an environment edit, never a code change (coding-standards §9.1). A
model with an explicit entry prices at its real rate - 0 for a KNOWN free
model; a model with NO entry is UNKNOWN and also costs 0, but the miss is
logged (warning) so a missing price is visible, never silently zero. The budget
meter (:mod:`modules.intake.budget_meter`) aggregates
``intake_ai_jobs.cost_paise`` as the authoritative monthly AI spend (NFR-001),
so this helper is what makes metered spend reflect real usage.

Prices are ``Decimal`` paise per token so sub-paise cost fractions survive the
integer ``cost_paise`` column; a fractional paise rounds half-up to the nearest
paise.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.config import (
    DEFAULT_AI_PRICING_TABLE,
    get_settings,
    parse_ai_pricing_table,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelPrice:
    """Paise-per-token price of one model (the launch-pricing formula).

    An explicit price of 0 marks a KNOWN free model (metered 0, never flagged);
    a model absent from ``PRICING_TABLE`` is UNKNOWN - also 0, but flagged so a
    missing rate is visible rather than silent.
    """

    price_in_paise: Decimal
    price_out_paise: Decimal


def _to_pricing_table(
    rates: Mapping[str, tuple[Decimal, Decimal]],
) -> dict[str, ModelPrice]:
    return {
        model: ModelPrice(price_in_paise=price_in, price_out_paise=price_out)
        for model, (price_in, price_out) in rates.items()
    }


#: The code-side default per-model table, built from the deployment config
#: constant (``model:price_in:price_out`` paise-per-token entries). Free is an
#: explicit 0 entry so it is a known-free model, never flagged; an unknown
#: model has no entry, prices 0, and is flagged. The effective table is
#: resolved lazily from Settings/env by :func:`resolve_pricing_table` so a
#: deployment's rates apply without a restart-freezing import.
PRICING_TABLE: Mapping[str, ModelPrice] = _to_pricing_table(
    parse_ai_pricing_table(DEFAULT_AI_PRICING_TABLE)
)


def resolve_pricing_table() -> Mapping[str, ModelPrice]:
    """The effective table for this process: config/env rates, code default fallback.

    Read from ``get_settings()`` so an ``AI_PRICING_TABLE`` value takes effect
    without the module import freezing an incomplete table (the pipeline already
    reads Settings at its own call sites this way). An empty configured table
    (``AI_PRICING_TABLE=""``) falls back to the code-side ``PRICING_TABLE`` so
    the free mock stays known-free until a deployment prices a model.
    """
    raw = get_settings().ai_pricing_table.strip()
    if not raw:
        return PRICING_TABLE
    return _to_pricing_table(parse_ai_pricing_table(raw))


def compute_cost_paise(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    table: Mapping[str, ModelPrice] | None = None,
) -> int:
    """Cost in paise of one metered call, from the provider's token usage.

    ``input_tokens * price_in + output_tokens * price_out`` off the resolved
    pricing table (or an injected ``table`` for pure unit testing). A model with
    no entry (unknown) costs 0 naturally rather than inventing a price, and the
    miss is logged as a warning so a missing rate is visible, not silently
    hidden. ``int -> int`` so the ``cost_paise`` column contract is unchanged.
    """
    effective = resolve_pricing_table() if table is None else table
    price = effective.get(model)
    if price is None:
        logger.warning(
            "AI pricing: no rate configured for model %r; metering 0 paise. "
            "Add it to AI_PRICING_TABLE (model:price_in:price_out).",
            model,
        )
        return 0
    total = (
        Decimal(input_tokens) * price.price_in_paise
        + Decimal(output_tokens) * price.price_out_paise
    )
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


__all__ = [
    "PRICING_TABLE",
    "ModelPrice",
    "compute_cost_paise",
    "resolve_pricing_table",
]
