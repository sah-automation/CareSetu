"""MOD-010: notify-side mirrors + terminal-status templates (T12, ticket #255).

The notify consumer mirrors the partner terminal events it subscribes to (the
consumer owns the model, cf. iam/audit). ``partner.activated`` and
``partner.rejected`` are consumed by several modules; the payload model for
each is registered once by the module that owns it (MOD-001's iam). The notify
handler therefore revalidates whatever registry-carried model arrives into its
own field-compatible mirror, and this module owns that mirror plus the two
ADR-0009 terminal-status templates that drive the WhatsApp-first / SMS-fallback
send - the only crafted message bodies notify emits for the partner gate.
"""

from __future__ import annotations

from pydantic import BaseModel

PARTNER_ACTIVATED_MESSAGE = (
    "Your CareSetu partner account is now active. You can start offering care on the platform."
)


def build_partner_rejected_message(reason: str) -> str:
    """The rejection body: it MUST carry the specific reason (FEAT-014).

    ``reason`` is the reason the operator gave (or the Step-1 auto-fail code),
    carried verbatim from the ``partner.rejected`` payload so the partner is
    told exactly why they were refused (ADR-0009, spec phase-5).
    """
    return f"Your CareSetu partner registration was not approved. Reason: {reason}"


class PartnerActivatedPayload(BaseModel):
    """Mirror of ``partner.activated`` (published by MOD-002, ticket #247).

    Field-compatible with the producing module's payload so the handler can
    revalidate a registry-carried model without any cross-schema reads.
    ``identity_id`` is the iam identity whose phone resolves the recipient.
    """

    partner_id: int
    identity_id: int
    decision_by: int


class PartnerRejectedPayload(BaseModel):
    """Mirror of ``partner.rejected``: the refusal reason rides the payload.

    Only the two terminal events reach these mirrors. ``Under Verification``
    and re-submission confirmations produce no notification (ADR-0009).
    """

    partner_id: int
    identity_id: int
    reason: str
    round: int
    decision_by: int | None = None
