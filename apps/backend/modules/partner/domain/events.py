"""MOD-002: canonical partner lifecycle event payloads and envelope builders.

Event names follow the registry dot-notation in ``internal-modules.md`` §4.2
(ADR-0008 two-step gate, ticket #247); payloads are typed Pydantic models
(coding-standards §3) and carry only lifecycle facts - identity, round, actor,
reason - never credential artifact bytes or any other sensitive document
content. Every builder answers an :class:`~bus.envelope.Envelope` the partner
facade writes into ``partner.partner_outbox`` in the SAME transaction as the
state change (ADR-0002 §1).
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from bus.envelope import Envelope
from bus.events import (
    EVENT_CREDENTIAL_INVALIDATED,
    EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_CREDENTIAL_REVIEWED,
    EVENT_PARTNER_REGISTERED,
    EVENT_PARTNER_REJECTED,
    EVENT_PARTNER_VERIFICATION_STARTED,
)

PRODUCER_MODULE = "partner"

PartnerType = Literal["doctor", "lab", "chemist"]


class PartnerRegisteredPayload(BaseModel):
    """Subject of ``partner.registered``: the partner profile just opened.

    The iam side emits a separate ``partner.registered``-keyed envelope when it
    creates the credential account (ADR-0010, ticket #245); this module emits
    its own same-key envelope when the profile row is opened. The two payloads
    name the same partner from each module's own storage.
    """

    partner_id: int
    identity_id: int
    partner_type: PartnerType


class VerificationStartedPayload(BaseModel):
    """Subject of ``partner.verification_started``: a round began.

    Emitted per round (first-time and every re-submission / re-verification),
    carrying ``round`` so the audit trail and the operator queue distinguish
    rounds (ADR-0008, spec phase-5 "Verification rounds").
    """

    partner_id: int
    round: int


class PartnerActivatedPayload(BaseModel):
    """Subject of ``partner.activated``: the step-2 operator approval landed.

    Reached ONLY by explicit operator decision - the no-auto-approve guarantee
    (ADR-0008 §2). ``decision_by`` is the approving operator identity.
    ``identity_id`` is the iam identity the ``partner`` role is granted to
    (MOD-001 consumes this event to flip the role on activation); it was fixed
    at registration (ADR-0010) and rides the payload so the consuming iam
    module never reads this schema (ADR-0003 isolation).
    """

    partner_id: int
    identity_id: int
    decision_by: int


class PartnerRejectedPayload(BaseModel):
    """Subject of ``partner.rejected``: the partner was refused.

    Two emitters (ADR-0008). Step-1 auto-fail (reason ``step1_fail``, never
    queued) and operator rejection (reason the operator gave). ``round`` names
    the verification round that was refused. ``identity_id`` is the iam
    identity whose ``partner`` role is suspended (MOD-001 consumes this to deny
    the role on rejection) - the isolation-safe identifier, never a cross-schema
    read.
    """

    partner_id: int
    identity_id: int
    reason: str
    round: int
    decision_by: int | None = None


class CredentialReviewedPayload(BaseModel):
    """Subject of ``partner.credential_reviewed``: who saw the documents.

    Emitted when an operator views a partner's credentials during review,
    carrying actor + partner + timestamp (ADR-0008, spec phase-5 "Operator
    audit depth"). This is the read-trail event that makes regulated decisions
    traceable back to the operator who actually looked.
    """

    partner_id: int
    actor_id: int


class CredentialInvalidatedPayload(BaseModel):
    """Subject of ``credential.invalidated``: a credential is no longer valid.

    Fires on permanent rejection (document cleanup after 30 days) and when an
    Active partner's re-verification fails / the grace window lapses with the
    credential expired - deindexing the directory and revoking the IAM role
    via MOD-001 (ADR-0008, spec phase-5 "Deactivation"). ``identity_id`` is
    the iam identity whose ``partner`` role is suspended on deactivation
    (MOD-001 consumes this event) - the isolation-safe identifier.
    """

    partner_id: int
    identity_id: int
    credential_id: int | None = None
    reason: str


def partner_registered_envelope(
    partner_id: int, identity_id: int, partner_type: PartnerType
) -> Envelope[PartnerRegisteredPayload]:
    """Build the ``partner.registered`` envelope for the partner outbox."""
    return Envelope[PartnerRegisteredPayload](
        event_id=uuid4(),
        event_type=EVENT_PARTNER_REGISTERED,
        producer=PRODUCER_MODULE,
        payload=PartnerRegisteredPayload(
            partner_id=partner_id, identity_id=identity_id, partner_type=partner_type
        ),
    )


def verification_started_envelope(
    partner_id: int, round: int
) -> Envelope[VerificationStartedPayload]:
    """Build the ``partner.verification_started`` envelope for the partner outbox."""
    return Envelope[VerificationStartedPayload](
        event_id=uuid4(),
        event_type=EVENT_PARTNER_VERIFICATION_STARTED,
        producer=PRODUCER_MODULE,
        payload=VerificationStartedPayload(partner_id=partner_id, round=round),
    )


def partner_activated_envelope(
    partner_id: int, identity_id: int, decision_by: int
) -> Envelope[PartnerActivatedPayload]:
    """Build the ``partner.activated`` envelope for the partner outbox."""
    return Envelope[PartnerActivatedPayload](
        event_id=uuid4(),
        event_type=EVENT_PARTNER_ACTIVATED,
        producer=PRODUCER_MODULE,
        payload=PartnerActivatedPayload(
            partner_id=partner_id, identity_id=identity_id, decision_by=decision_by
        ),
    )


def partner_rejected_envelope(
    partner_id: int,
    identity_id: int,
    reason: str,
    round: int,
    decision_by: int | None = None,
) -> Envelope[PartnerRejectedPayload]:
    """Build the ``partner.rejected`` envelope for the partner outbox."""
    return Envelope[PartnerRejectedPayload](
        event_id=uuid4(),
        event_type=EVENT_PARTNER_REJECTED,
        producer=PRODUCER_MODULE,
        payload=PartnerRejectedPayload(
            partner_id=partner_id,
            identity_id=identity_id,
            reason=reason,
            round=round,
            decision_by=decision_by,
        ),
    )


def credential_reviewed_envelope(
    partner_id: int, actor_id: int
) -> Envelope[CredentialReviewedPayload]:
    """Build the ``partner.credential_reviewed`` envelope for the partner outbox."""
    return Envelope[CredentialReviewedPayload](
        event_id=uuid4(),
        event_type=EVENT_PARTNER_CREDENTIAL_REVIEWED,
        producer=PRODUCER_MODULE,
        payload=CredentialReviewedPayload(partner_id=partner_id, actor_id=actor_id),
    )


def credential_invalidated_envelope(
    partner_id: int,
    identity_id: int,
    reason: str,
    credential_id: int | None = None,
) -> Envelope[CredentialInvalidatedPayload]:
    """Build the ``credential.invalidated`` envelope for the partner outbox."""
    return Envelope[CredentialInvalidatedPayload](
        event_id=uuid4(),
        event_type=EVENT_CREDENTIAL_INVALIDATED,
        producer=PRODUCER_MODULE,
        payload=CredentialInvalidatedPayload(
            partner_id=partner_id,
            identity_id=identity_id,
            credential_id=credential_id,
            reason=reason,
        ),
    )
