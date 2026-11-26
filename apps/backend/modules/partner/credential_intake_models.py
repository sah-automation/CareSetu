"""Result models for partner credential intake sub-facade."""

from datetime import datetime

from pydantic import BaseModel

from modules.partner.domain.credentials import CredentialType


class CredentialSubmission(BaseModel):
    """One credential a partner submits for Step-1 review (ADR-0008).

    ``credential_type`` is the closed per-partner-type type (a doctor's medical
    registration, a lab's lab license, a chemist's drug license, or a supporting
    document). ``artifacts`` are the encrypted-document source bytes the facade
    AES-encrypts into the ``partner/`` object-storage prefix; the refs, not the
    bytes, are persisted in ``partner_credentials.artifact_refs``.
    """

    credential_type: CredentialType
    artifacts: list[bytes] = []


class CredentialSubmissionResult(BaseModel):
    """The typed outcome of a credential submission.

    ``status`` is ``Under Verification`` on a Step-1 pass (a round opened,
    ``partner.verification_started``); ``Rejected`` on a Step-1 auto-fail with
    ``reason`` naming the specific pre-filter failure (never queued - ADR-0008).
    ``reason`` is present only on the auto-fail path.
    """

    partner_id: int
    status: str
    round: int
    reason: str | None = None


class RejectionReasonView(BaseModel):
    """The specific failure reason surfaced to a rejected partner (PHASE-5 T09).

    Read back from the latest ``[Rejected]`` round's ``decision_reason`` (the
    operator's reason or the Step-1 pre-filter auto-fail reason recorded by
    T08/T06). Meaningful only for a ``[Rejected]`` partner - the facade raises
    :class:`PartnerNotRejectedError` otherwise so the partner is never asked to
    re-apply against a status they are not in.
    """

    partner_id: int
    rejection_reason: str
    round: int


class PartnerVerificationStatusView(BaseModel):
    """The partner's own credential review status for the current round (US-7, P3 #271).

    Surfaces whether the partner's credentials are under review, and on a
    decided round the outcome (``decision``/``decision_reason``/``decided_at``),
    without exposing the operator's artifact refs or audit chain. For a
    ``[Registered]`` partner who has not entered a round ``round`` is 0 and the
    round fields are ``None`` - a meaningful "no submission yet" response.
    """

    partner_id: int
    round: int
    status: str | None
    decision: str | None
    decision_reason: str | None
    decided_at: datetime | None
