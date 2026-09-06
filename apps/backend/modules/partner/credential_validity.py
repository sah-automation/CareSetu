"""Credential-validity deep module: eligibility predicates, pure decision, and
the single close-out transition (ticket #331, WI-1 of parent #330).

Concentrates the partner directory-eligibility concept into one module-level
deep module that owns:

- **Read-side SQL predicates** (``has_any_credential``,
  ``has_invalid_credential``, ``provider_visible``) used by search, profile,
  and cached-visibility re-derivation. These were previously free functions in
  the facade.
- **A pure eligibility decision** (``evaluate_eligibility``) evaluated over
  credential records, unit-testable without a database - mirrors the partner
  state-machine pure-domain suite pattern.
- **A single close-out transition** (``close_out_credentials``) that, per
  invalidated credential, writes the ``credential.invalidated`` event, removes
  the directory entry, and performs the best-effort cache flush. The four
  close-out paths (operator reject of an active partner, credential
  revocation, credential expiry close-out, credential purge) converge on this
  module so a change to credential-expiry semantics (ADR-0011) is defined once
  and all paths emit an identical outcome.

ADR-0011 semantics are absorbed unchanged: lazy read-hide (an expired
credential is never displayed even minutes after the date passes) and the
daily sweep contract (the recorded close-out fires exactly once). No schema
changes, no new events, no new dependencies, no behaviour change. Each caller
performs its own credential-row mutation (stamp ``revoked_at``/``reason`` or
delete the row) before calling :func:`close_out_credentials`; the transition
owns the convergent close-out outcome, not the caller-specific row write.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from bus.outbox_writer import write_outbox
from modules.partner.directory_cache import directory_visibility_changed
from modules.partner.domain.events import credential_invalidated_envelope
from modules.partner.outbox import PARTNER_OUTBOX_TABLE
from modules.partner.schema.models import (
    partner_credentials,
    partner_directory_index,
    partner_profiles,
)

PARTNER_SCHEMA = "partner"


# ---------------------------------------------------------------------------
# Pure eligibility decision (unit-testable without a database)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CredentialRecord:
    """One credential row, stripped of DB-mapping concerns.

    Carries only the fields the eligibility decision needs so the pure
    function can be tested with plain dataclasses - no SQLAlchemy row, no
    connection. Mirrors the partner state-machine pure-domain pattern
    (``tests/unit/test_partner_state_machine.py``).
    """

    id: int
    verified: bool
    expires_at: datetime | None
    revoked_at: datetime | None
    invalidation_reason: str | None


@dataclass(frozen=True)
class EligibilityDecision:
    """The result of :func:`evaluate_eligibility`.

    ``has_any`` is True when the partner holds at least one submitted
    credential. ``has_invalid`` is True when any credential was never
    verified, its recorded expiry date has passed, or it was revoked - the
    same three predicates the SQL ``has_invalid_credential`` tests (ADR-0011
    lazy read-hide). The caller (the visibility predicate) combines both to
    decide directory visibility.
    """

    has_any: bool
    has_invalid: bool


def evaluate_eligibility(
    credentials: list[CredentialRecord],
    *,
    now: datetime | None = None,
) -> EligibilityDecision:
    """Pure credential eligibility decision - no database required.

    Evaluates the same predicates as the SQL subqueries
    (``has_any_credential`` / ``has_invalid_credential``) against an
    in-memory list of credential records. ``now`` defaults to
    ``datetime.now(UTC)`` when omitted; tests inject a fixed clock.

    A credential is **invalid** when:
    - it was never verified (``verified is False``), OR
    - its recorded expiry date has passed (``expires_at <= now``), OR
    - it was revoked (``revoked_at is not None``).

    This is the lazy read-hide contract from ADR-0011: reads must keep
    working while an expired credential has not yet been swept; the pure
    decision reflects "expired counts as not-valid" even before sweep.
    """
    if not credentials:
        return EligibilityDecision(has_any=False, has_invalid=False)
    ts = now or datetime.now(UTC)
    has_invalid = any(
        not c.verified
        or (c.expires_at is not None and c.expires_at <= ts)
        or c.revoked_at is not None
        for c in credentials
    )
    return EligibilityDecision(has_any=True, has_invalid=has_invalid)


# ---------------------------------------------------------------------------
# Read-side SQL predicates (moved from facade.py)
# ---------------------------------------------------------------------------


def has_any_credential(column: Any) -> Any:
    """Exists-subquery: the partner has at least one submitted credential.

    Mirrors the directory backfill's ``EXISTS (SELECT 1 FROM credentials)``
    guard so search and the index agree on the "verified on record" baseline.
    """
    return (
        select(1)
        .select_from(partner_credentials)
        .where(partner_credentials.c.profile_id == column)
        .exists()
    )


def has_invalid_credential(column: Any) -> Any:
    """Exists-subquery: the partner has any credential that is not valid.

    The lazy read-hide (ADR-0011): a credential is invalid when it was never
    verified, its recorded expiry date has passed, or it was revoked. Search
    derives visibility from these recorded dates on every read - it never
    trusts a cached ``is_active`` flag for the validity decision (T02b wraps
    the cache later; correctness stays here).
    """
    return (
        select(1)
        .select_from(partner_credentials)
        .where(
            partner_credentials.c.profile_id == column,
            or_(
                partner_credentials.c.verified.is_(False),
                and_(
                    partner_credentials.c.expires_at.is_not(None),
                    partner_credentials.c.expires_at <= func.now(),
                ),
                partner_credentials.c.revoked_at.is_not(None),
            ),
        )
        .exists()
    )


def provider_visible(column: Any) -> Any:
    """The single provider-visibility predicate (REQ-028 + ADR-0011).

    ``True`` iff the partner is ``[Active]``, has a ``directory_index``
    entry, holds at least one submitted credential AND every credential is
    verified, unexpired and unrevoked. Both ``search_directory`` (which card
    shows) and ``get_provider_profile`` (which profile resolves, and whose
    ``verified`` indicator reads True) use this SAME predicate, so the
    indicator can never claim a partner the search hides - one source of
    truth for "tick gone = card gone". Always derived on read from the
    recorded dates, never a cached ``is_active``-only trust (ADR-0011).
    """
    return and_(
        partner_directory_index.c.is_active.is_(True),
        partner_profiles.c.status == "Active",
        has_any_credential(column),
        ~has_invalid_credential(column),
    )


# ---------------------------------------------------------------------------
# Single close-out transition (convergent across all four paths)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CloseOutCredential:
    """One credential to close out, with the context the transition needs.

    Each caller (operator reject, revocation, expiry sweep, purge) builds
    these from the rows it holds after its own row mutation. The close-out
    transition emits one ``credential.invalidated`` event per record and
    deindexes the directory. The credential-row mutation (stamp
    ``revoked_at`` / ``invalidation_reason`` or delete the row) is performed
    by the caller before calling :func:`close_out_credentials` (ADR-0011
    recorded close-out).
    """

    credential_id: int | None
    partner_id: int
    identity_id: int
    reason: str


async def close_out_credentials(
    connection: AsyncConnection,
    credentials: list[CloseOutCredential],
) -> list[int]:
    """The single close-out transition for credential invalidation.

    For every invalidated credential in ``credentials``:
    - deindexes the affected partner(s)' directory entry (``is_active =
      False``) once per partner; and
    - writes exactly one ``credential.invalidated`` envelope to the partner
      outbox (ADR-0002 atomic outbox).

    After all credentials are processed, flushes the directory cache once
    (best-effort, silent on failure; the lazy read-hide is correct
    regardless).

    All writes happen inside the caller's transaction so a crash cannot
    leave an event without its state change or vice versa (ADR-0002 S1). The
    credential-row mutation (stamping ``revoked_at`` / ``invalidation_reason``
    or deleting the row) is the caller's responsibility before calling this -
    the transition owns the convergent close-out outcome only.

    Returns the credential ids that were closed out.
    """
    if not credentials:
        return []

    affected_partners = {cred.partner_id for cred in credentials}
    await connection.execute(
        partner_directory_index.update()
        .where(partner_directory_index.c.partner_id.in_(affected_partners))
        .values(is_active=False, updated_at=func.now())
    )
    closed: list[int] = []
    for cred in credentials:
        await write_outbox(
            connection,
            PARTNER_SCHEMA,
            PARTNER_OUTBOX_TABLE,
            credential_invalidated_envelope(
                cred.partner_id,
                identity_id=cred.identity_id,
                credential_id=cred.credential_id,
                reason=cred.reason,
            ),
        )
        if cred.credential_id is not None:
            closed.append(cred.credential_id)

    # PHASE-6 T02b (#314): the close-out deindexes every affected partner,
    # making each cached search result potentially stale. Flush the namespace
    # once per pass (best-effort, silent on failure).
    await directory_visibility_changed()

    return closed
