"""MOD-005: per-model AI pricing helper - real cost on metered jobs (PHASE-7 T02 #399).

Computes the ``cost_paise`` a completed ``intake_ai_jobs`` row records from the
provider's reported token usage (the metering seam, #398), per the
launch-pricing formula::

    cost_paise = input_tokens * price_in + output_tokens * price_out

The per-model price table (``PRICING_TABLE``) prices PAID models only, in paise
per token. A model with no entry costs 0: free models are simply absent so their
real (zero) usage records 0 naturally, and an unknown model records 0 rather
than inventing a price - a paid model MUST carry an entry or its cost never
reaches the meter. The budget meter (:mod:`modules.intake.budget_meter`)
aggregates ``intake_ai_jobs.cost_paise`` as the authoritative monthly AI spend
(NFR-001), so this helper is what makes metered spend reflect real usage.

Prices are ``Decimal`` paise per token so sub-paise cost fractions survive the
integer ``cost_paise`` column; a fractional paise rounds half-up to the nearest
paise.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

#: Per-model launch prices in paise per token, for PAID models only. Free
#: models carry no entry so their usage records 0 naturally; an unknown model
#: (no entry) also costs 0 - a paid model must carry an entry or it is never
#: metered. The table is deliberately empty at launch (the mock is free):
#: shipping a real paid model's price is deployment configuration, never
#: hardcoded (coding-standards §9.1) - it lands in Settings/env alongside the
#: model's ``AI_MODEL`` knob, mirroring how ``DEFAULT_MONTHLY_BUDGET_PAISE``
#: (budget_meter.py + config.py) is the code-side default until configured.
PRICING_TABLE: Mapping[str, ModelPrice] = {}


@dataclass(frozen=True)
class ModelPrice:
    """Paise-per-token price of one paid model (the launch-pricing formula)."""

    price_in_paise: Decimal
    price_out_paise: Decimal


def compute_cost_paise(model: str, *, input_tokens: int, output_tokens: int) -> int:
    """Cost in paise of one metered call, from the provider's token usage.

    ``input_tokens * price_in + output_tokens * price_out`` off
    ``PRICING_TABLE``; a model with no entry (free, or unknown) costs 0
    naturally rather than inventing a price.
    """
    price = PRICING_TABLE.get(model)
    if price is None:
        return 0
    total = (
        Decimal(input_tokens) * price.price_in_paise
        + Decimal(output_tokens) * price.price_out_paise
    )
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


__all__ = ["PRICING_TABLE", "ModelPrice", "compute_cost_paise"]
