"""MOD-001: MFA sub-facade for the operator second factor (T07, ticket #250).

The operator session is minted only after the MFA second factor completes
(``session_facade.issue_operator_session`` refuses without an enrolled,
verified ``iam_operator_mfa`` row). This sub-facade records that a
successful second-factor verification happened: it marks the operator's MFA
enrolled and stamps ``last_verified_at``, so the session seam can admit them.

The TOTP code check itself (validating a live code against the encrypted
secret) is the operator console's login surface - a later ticket in Phase 5.
This seam is the session-facing contract that the "second factor completed"
flag is durable and attributed before a session can be minted.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.iam.domain.exceptions import SessionIssuanceError
from modules.iam.domain.phone import normalize_phone
from modules.iam.schema.models import iam_identities, iam_operator_mfa


class VerifyMfaResult(BaseModel):
    """Outcome of recording a successful operator MFA second factor (T07, #250).

    ``enrolled`` is True when the operator's MFA factor was already enrolled
    and this call recorded a fresh ``last_verified_at``; ``newly_enrolled``
    marks the first enrollment (no prior MFA row existed). Either way, after
    this call the operator satisfies the ``issue_operator_session`` MFA gate.
    """

    identity_id: int
    phone_e164: str
    enrolled: bool
    newly_enrolled: bool


def _default_clock() -> datetime:
    return datetime.now(UTC)


class MfaFacade:
    """MFA enrollment/verification recording for the operator second factor."""

    def __init__(
        self,
        engine: AsyncEngine,
        clock: Callable[[], datetime] = _default_clock,
    ) -> None:
        self._engine = engine
        self._clock = clock

    async def record_mfa_verified(self, phone: str) -> VerifyMfaResult:
        """Record a successful operator MFA verification (T07, #250).

        Marks the identity's ``iam_operator_mfa`` row enrolled (``mfa_enabled``)
        and stamps ``last_verified_at`` with ``now``, idempotently upserting on
        the unique ``identity_id``. A phone with no identity (never invited) is
        refused with ``SessionIssuanceError`` - there is no self-registration,
        so an operator MFA can only be recorded against a phone that an
        existing operator invited.
        """
        phone_e164 = normalize_phone(phone)

        async with self._engine.begin() as connection:
            identity_id = (
                await connection.execute(
                    select(iam_identities.c.id).where(iam_identities.c.phone_e164 == phone_e164)
                )
            ).scalar_one_or_none()
            if identity_id is None:
                raise SessionIssuanceError(
                    f"no identity for {phone_e164}; invite the operator before MFA"
                )
            now = self._clock()
            existing = (
                await connection.execute(
                    select(iam_operator_mfa.c.id).where(
                        iam_operator_mfa.c.identity_id == identity_id
                    )
                )
            ).scalar_one_or_none()
            newly_enrolled = existing is None
            await connection.execute(
                postgresql_insert(iam_operator_mfa)
                .values(
                    identity_id=identity_id,
                    # The TOTP secret is populated by the operator console's
                    # enrollment surface (a later Phase 5 ticket); this seam only
                    # records that the second factor completed, so the schema's
                    # non-null secret column holds an unused placeholder.
                    secret="",  # nosec B106 - schema-required placeholder, not a real TOTP secret
                    mfa_enabled=True,
                    last_verified_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["identity_id"],
                    set_={
                        "mfa_enabled": True,
                        "last_verified_at": now,
                        "enrolled_at": now,
                    },
                )
            )

        return VerifyMfaResult(
            identity_id=int(identity_id),
            phone_e164=phone_e164,
            enrolled=not newly_enrolled,
            newly_enrolled=newly_enrolled,
        )
