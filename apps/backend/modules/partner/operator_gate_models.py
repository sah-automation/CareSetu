"""Result models for partner operator gate sub-facade."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PartnerQueueItem(BaseModel):
    """One partner on the operator verification queue (FEAT-015, T08).

    ``created_at`` is the registration time the age-prioritized default sort
    orders by (KPI-004: oldest registrations first so the activation-cycle
    median stays within 48 h). ``round`` is the partner's latest verification
    round (0 = never entered a round).
    """

    partner_id: int
    identity_id: int
    partner_type: str
    status: str
    practice_name: str | None
    practice_address: str
    created_at: datetime
    round: int
    audit_link: str | None = None


class PartnerQueue(BaseModel):
    """The operator's verification queue view."""

    items: list[PartnerQueueItem]


class CredentialDetail(BaseModel):
    """One submitted credential in the operator's per-partner detail view."""

    credential_id: int
    credential_type: str
    verified: bool
    expires_at: datetime | None
    artifact_refs: dict[str, str]


class VerificationRound(BaseModel):
    """One verification round in the operator's history view."""

    round: int
    status: str
    decision: str | None
    decision_reason: str | None
    decision_by: int | None
    decided_at: datetime | None
    created_at: datetime


class AuditEventDetail(BaseModel):
    """One ``audit_events`` row in the partner's verification detail view (S7).

    A typed, read-only projection of a ledger row surfaced alongside the
    profile/credentials/history so the operator can see the partner's full
    audit chain (who-what-when + hash links) while making a decision. This is
    the primary-schema read of the existing audit seam - no new write path.
    """

    id: UUID
    event_type: str
    actor_id: UUID | None
    target_id: UUID | None
    scope: str | None
    metadata: dict[str, object]
    timestamp: datetime
    prev_hash: str
    hash: str


class PartnerVerificationDetail(BaseModel):
    """The full per-partner review: profile + credentials + verification history.

    What the operator sees when they open a queue item (FEAT-015 user story 17)
    to make a defensible approve/reject decision. ``credentials`` are the
    submitted documents (artifact refs, never bytes); ``verification_history``
    is the per-round queue/decision trail; ``audit_events`` is the partner's
    ledger chain (S7 read-only augmentation).
    """

    partner_id: int
    identity_id: int
    partner_type: str
    status: str
    practice_name: str | None
    practice_address: str
    service_area_id: int | None
    created_at: datetime
    credentials: list[CredentialDetail]
    verification_history: list[VerificationRound]
    audit_events: list[AuditEventDetail] = Field(default_factory=list)
    audit_link: str | None = None
