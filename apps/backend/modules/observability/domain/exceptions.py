"""MOD-013: domain errors for the ``observability`` module (coding-standards §3).

B3 (#701) carries the module base error; the hierarchy grows with the tickets
that introduce real validation (the B4 consumer and B5 rollup read paths).

B5 (#735) adds the two the alert acknowledgement can fail on. Both are EXPECTED
outcomes of a call an operator made deliberately - they say the alert they named
is not in a state that can be acknowledged - so they answer through the module's
own envelope rather than falling to the app catch-all as a 5xx.

B4e (#739) adds the one the product-ledger writer can fail on. It is a
PROGRAMMER error rather than an expected outcome - a registry entry that records an
outcome it never declared is a defect in this module, caught at boot by
``register_product_step`` and again at write time - so it deliberately does not
answer through the module's envelope.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from collections.abc import Sequence

    from modules.observability.domain.product import ProductOutcome


class ObservabilityError(Exception):
    """Base error for the observability module."""


class AlertNotFoundError(ObservabilityError):
    """No alert row carries the given identifier.

    A stale console tab, or a feed page opened before the alert was purged. It is
    a 404 rather than an empty 200: an operator who pressed "acknowledge" on a row
    that is gone needs to be told the row is gone.
    """

    def __init__(self, alert_id: UUID) -> None:
        super().__init__(f"no alert exists with id {alert_id}")
        self.alert_id = alert_id


class AlertAlreadyResolvedError(ObservabilityError):
    """The alert is ``resolved``, which is closed rather than standing.

    Acknowledging one would move it back to ``acknowledged``, re-opening a problem
    a later pass had already established as cleared. Refusing is the honest answer:
    a 200 here would report an acknowledgement the row does not carry.
    """

    def __init__(self, alert_id: UUID) -> None:
        super().__init__(f"alert {alert_id} is already resolved and cannot be acknowledged")
        self.alert_id = alert_id


class ProductOutcomeNotAllowed(ObservabilityError):
    """A funnel step asked to record an outcome it does not declare.

    ``#717`` decision 24 (a degraded fallback is ``errored``, never a quiet
    abandonment) and decision 25 (a re-record is its own outcome rather than a
    failure of the original) are RULES, and this is where they are enforced: a step
    that records ``abandoned`` for a degraded path, or scores a re-record as a
    failure of the original, is silently corrupting the funnel - and a funnel that
    cannot tell a broken path from a drop-off is worse than no funnel, because it
    looks like data.
    """

    def __init__(self, step: str, outcome: str, allowed_outcomes: Sequence[ProductOutcome]) -> None:
        super().__init__(
            f"step {step} may not record outcome {outcome}; "
            f"it declares {', '.join(allowed_outcomes)}"
        )
        self.step = step
        self.outcome = outcome
        self.allowed_outcomes = tuple(allowed_outcomes)
