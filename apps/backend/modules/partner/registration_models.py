"""Result models for partner registration sub-facade."""

from datetime import datetime

from pydantic import BaseModel


class RegisterPartnerResult(BaseModel):
    """The outcome of open partner registration (FEAT-014, T05).

    ``partner_id`` and ``status`` name the partner profile - a freshly opened
    ``[Registered]`` profile on first registration, or the pre-existing
    profile on a duplicate phone (accepted criterion 6: duplicate phone
    resolves to the existing identity). ``identity_id`` is the iam gateway
    principal the account was created/resolved for, and ``created`` tells the
    caller whether this call introduced a new profile (``True``) or resolved
    an existing one (``False``).
    """

    partner_id: int
    identity_id: int
    partner_type: str
    status: str
    round: int
    created: bool


class PartnerMeView(BaseModel):
    """The partner's own self-service onboarding status (US-6, P2 #271).

    A thin, partner-scoped read-only projection: ``status`` is the current
    lifecycle state ([Registered]/[Under Verification]/[Active]/[Rejected]),
    ``partner_type`` the registered type, ``round`` the latest verification
    round (0 = never entered a round), and ``created_at`` the registration
    time. None of the operator-scoped queue/credential detail is exposed -
    the restricted pre-activation scope (spec) shows status only.
    """

    partner_id: int
    status: str
    partner_type: str
    round: int
    created_at: datetime | None
