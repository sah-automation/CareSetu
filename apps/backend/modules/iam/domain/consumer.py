"""MOD-001: typed mirror payloads for consumed partner lifecycle events.

The iam module owns the payload models for events it consumes (consumer
owns the model, cf. audit's ``register_payload_model``). These are
byte-for-byte mirrors of the partner module's producer payloads - the
dispatcher reconstructs a typed ``Envelope`` from an outbox row by
validating the stored JSONB payload with this model, so a typed payload
- never a raw dict - crosses the async seam (coding-standards §3,
ADR-0002 §2).

Mirrors: ``partner.activated``, ``partner.rejected``,
``credential.invalidated`` from ``modules.partner.domain.events``.
"""

from __future__ import annotations

from pydantic import BaseModel


class PartnerActivatedPayload(BaseModel):
    """Mirror of ``partner.activated``: the step-2 operator approval landed.

    Reached ONLY by explicit operator decision - the no-auto-approve
    guarantee (ADR-0008 §2). ``decision_by`` is the approving operator
    identity; ``identity_id`` is the iam identity to grant the ``partner``
    role to.
    """

    partner_id: int
    identity_id: int
    decision_by: int


class PartnerRejectedPayload(BaseModel):
    """Mirror of ``partner.rejected``: the partner was refused.

    Two emitters (ADR-0008). Step-1 auto-fail (reason ``step1_fail``,
    never queued) and operator rejection (reason the operator gave).
    ``round`` names the verification round that was refused.
    """

    partner_id: int
    identity_id: int
    reason: str
    round: int
    decision_by: int | None = None


class CredentialInvalidatedPayload(BaseModel):
    """Mirror of ``credential.invalidated``: a credential is no longer valid.

    Fires on permanent rejection (document cleanup after 30 days) and
    when an Active partner's re-verification fails / the grace window
    lapses with the credential expired - deindexing the directory and
    revoking the IAM role via MOD-001 (ADR-0008, spec phase-5
    "Deactivation").
    """

    partner_id: int
    identity_id: int
    credential_id: int | None = None
    reason: str
