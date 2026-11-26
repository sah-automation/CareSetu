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
- **A single directory-entry refresh** (``refresh_directory_entry``) - the one
  writer of the read-side entry's declared fields, shared by the operator
  approval path and the doctor's own address save (#607). It copies the
  position and the specialties off the profile row and nothing else: the listed
  flag stays activation-owned and no credential row is read or written, so a
  doctor-triggered call can move a listing but can neither list its caller nor
  vouch for its caller's credentials.
- **A single activate transition** (``activate_partner``) - the symmetric
  counterpart of the close-out (#456): operator approval stamps the current
  round's ``partner_credentials`` rows verified, refreshes the partner's
  ``partner_directory_index`` entry through the shared refresh, and flips that
  entry's listed flag. Both directions of visibility change (activate on
  approve, deindex on close-out) travel through this module, so the state
  bookkeeping agrees with the read-side predicates by construction.

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
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
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
from modules.partner.shared import PARTNER_SCHEMA

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

    ``verified`` marks the credential as belonging to an approved round (the
    #456 activation seam stamps the approved round's rows ``verified = true``);
    pending re-verification rows are ``verified = False``.
    """

    id: int
    verified: bool
    expires_at: datetime | None
    revoked_at: datetime | None
    invalidation_reason: str | None


@dataclass(frozen=True)
class EligibilityDecision:
    """The result of :func:`evaluate_eligibility`.

    ``has_any`` is True when the partner holds at least one credential in an
    approved round. ``has_invalid`` is True when any approved-round credential
    has its recorded expiry date in the past or was revoked - matching the SQL
    ``has_invalid_credential`` predicate (ADR-0011 lazy read-hide). Pending
    new-round rows (``verified = False``) are not part of the approved-round
    credential set and never de-list an ``[Active]`` partner. The caller (the
    visibility predicate) combines both to decide directory visibility.
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

    Only credentials stamped ``verified`` (an approved round - the #456
    activation seal) count. A re-verification round's pending rows arrive
    ``verified = False`` and are scoped out, so an ``[Active]`` partner stays
    eligible through the grace window; an unverified row alone never
    establishes eligibility.

    An approved-round credential is **invalid** when:
    - its recorded expiry date has passed (``expires_at <= now``), OR
    - it was revoked (``revoked_at is not None``).

    This is the lazy read-hide contract from ADR-0011: reads must keep
    working while an expired credential has not yet been swept; the pure
    decision reflects "expired counts as not-valid" even before sweep.
    """
    approved = [c for c in credentials if c.verified]
    if not approved:
        return EligibilityDecision(has_any=False, has_invalid=False)
    ts = now or datetime.now(UTC)
    has_invalid = any(
        (c.expires_at is not None and c.expires_at <= ts) or c.revoked_at is not None
        for c in approved
    )
    return EligibilityDecision(has_any=True, has_invalid=has_invalid)


# ---------------------------------------------------------------------------
# Read-side SQL predicates (moved from facade.py)
# ---------------------------------------------------------------------------


def has_any_credential(column: Any) -> Any:
    """Exists-subquery: the partner has at least one approved-round credential.

    Scoped to ``verified = True`` rows - the rows the #456 activation seam
    stamps on approval, and the only rows that count toward the approved-round
    credential set. A re-verification round's pending rows arrive
    ``verified = False`` and are scoped out, so an ``[Active]`` partner stays
    eligible through the grace window.
    """
    return (
        select(1)
        .select_from(partner_credentials)
        .where(
            partner_credentials.c.profile_id == column,
            partner_credentials.c.verified.is_(True),
        )
        .exists()
    )


def has_invalid_credential(column: Any) -> Any:
    """Exists-subquery: the partner has any approved-round credential that is not valid.

    Scoped to the same ``verified = True`` approved-round rows as
    ``has_any_credential``: a credential is invalid when its recorded expiry
    date has passed, or it was revoked. Pending new-round rows
    (``verified = False``) are never counted, so an ``[Active]`` partner who
    re-submits cannot be de-listed before an operator decision (ADR-0011 lazy
    read-hide still applies to approved-round rows - revoked/expired ones hide
    on every read).
    """
    return (
        select(1)
        .select_from(partner_credentials)
        .where(
            partner_credentials.c.profile_id == column,
            partner_credentials.c.verified.is_(True),
            or_(
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
    entry, holds at least one approved-round credential (``verified = True``)
    AND every approved-round credential is unexpired and unrevoked. Both
    ``search_directory`` (which card shows) and ``get_provider_profile``
    (which profile resolves, and whose ``verified`` indicator reads True) use
    this SAME predicate, so the indicator can never claim a partner the search
    hides - one source of truth for "tick gone = card gone". Always derived on
    read from the recorded dates, never a cached ``is_active``-only trust
    (ADR-0011). A pending re-verification round's unverified rows never count
    (grace window, #457) - only an operator decision (approve/reject) changes
    visibility.
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


# ---------------------------------------------------------------------------
# Single directory-entry refresh (shared by activation and the doctor's own
# address save)
# ---------------------------------------------------------------------------


async def refresh_directory_entry(
    connection: AsyncConnection,
    partner_id: int,
) -> None:
    """Re-derive the read-side directory entry from the partner's live profile.

    The ONE writer of ``partner_directory_index``'s declared fields (#607), and
    the second writer of the entry itself since the activation seam stopped
    being its only one. Called by the operator approval path, through
    :func:`activate_partner`; the doctor's own address save (#609) is its second
    caller. A doctor who corrects a wrong sign-up PIN moves their listing;
    nothing else about them moves.

    **What it writes.** The practice position
    (``practice_latitude``/``practice_longitude``) and the specialties (the
    profile's declared selection - #602's closed vocabulary in #606's
    multi-valued storage). The third declared part of the address, the locality,
    lives on the profile row this reads and is persisted by the caller's own
    profile write in the same transaction; the entry carries no locality column,
    so there is nothing for this statement to write there.

    **What it structurally cannot write.** It takes no values at all: every
    refreshed column is read off the profile row by an ``INSERT ... FROM
    SELECT`` (the shape the activation seam already used), so there is no
    parameter a caller could supply, and no route by which a doctor reaches a
    column that is not theirs to set.

    - The listed flag (``is_active``) is named nowhere in this statement, and a
      doctor-triggered call cannot create a row that would take the column's
      server default either, because the write is scoped to a partner whose
      recorded status is ``[Active]`` - the same clause ``provider_visible``
      ANDs with the flag. A profile save can therefore only ever touch a row
      that activation already created, and only move where that row is found.
      Activation owns the flag and sets it explicitly
      (:func:`activate_partner`).
    - No ``partner_credentials`` row is read or written. The ``verified`` stamp
      is round-scoped bookkeeping the activate transition owns, and every clause
      of the verified derivation reads activation state and recorded credential
      dates rather than the entry, so refreshing the entry cannot reach it.
    - ``partner_type`` is a registration-time declared attribute, not a
      doctor-editable field, so an existing entry's value is never re-derived.
      It is in the insert's column list only because the column is NOT NULL and a
      row that does not exist yet has no other source for it.

    **Idempotent by construction.** The conflict target is ``partner_id``
    (ADR-0012: one entry per partner), so re-running refreshes the row that is
    already there instead of inserting a second one. That is not tidiness: a
    doctor indexed before this writer existed carries an entry with no
    specialties on it, and the conflict path is the only thing that can ever
    fill them in.

    **In the caller's transaction.** It takes the caller's connection and opens
    no transaction of its own (ADR-0002 §1), which is what lets the address save
    write the profile and re-derive the entry atomically, or roll both back
    together. Nothing here rolls back on its own either.

    **Flushes the directory search cache.** A cached search row carries the
    doctor's distance as it stood when the row was written, and the cache key
    holds the CALLER's geo point, so no single partner can be addressed by key -
    a moved doctor keeps serving the old distance until the whole namespace is
    flushed. The flush lives inside the operation rather than in each caller
    precisely so that a second caller cannot forget it: the operator approval
    path flushes again after its activation event (both are best-effort
    namespace flushes, cheap and idempotent), and the address save flushes
    exactly once, here. The failure mode if Redis is unavailable is a stale
    distance for one TTL, never a visibility leak (ADR-0011).
    """
    index_stmt = postgresql_insert(partner_directory_index)
    await connection.execute(
        index_stmt.from_select(
            [
                partner_directory_index.c.partner_id,
                partner_directory_index.c.practice_latitude,
                partner_directory_index.c.practice_longitude,
                partner_directory_index.c.partner_type,
                partner_directory_index.c.specialty,
            ],
            select(
                partner_profiles.c.id,
                partner_profiles.c.practice_latitude,
                partner_profiles.c.practice_longitude,
                partner_profiles.c.partner_type,
                partner_profiles.c.specialties,
            ).where(
                partner_profiles.c.id == partner_id,
                # The entry exists for [Active] partners (glossary: one
                # directory entry per [Active] partner), so a profile save for a
                # partner no operator has approved writes nothing at all - it
                # cannot bring an entry row into existence, let alone a listed
                # one. The status is READ here and written by nobody: it is the
                # activation transition's, and the same recorded value
                # ``provider_visible`` derives visibility from.
                partner_profiles.c.status == "Active",
            ),
        ).on_conflict_do_update(
            index_elements=["partner_id"],
            set_={
                "practice_latitude": index_stmt.excluded.practice_latitude,
                "practice_longitude": index_stmt.excluded.practice_longitude,
                "specialty": index_stmt.excluded.specialty,
                "updated_at": func.now(),
            },
        )
    )
    await directory_visibility_changed()


# ---------------------------------------------------------------------------
# Single activate transition (convergent on operator approval)
# ---------------------------------------------------------------------------


async def activate_partner(
    connection: AsyncConnection,
    partner_id: int,
    *,
    round: int,
) -> None:
    """The single activate transition for directory visibility (#456).

    The symmetric counterpart of :func:`close_out_credentials`: operator
    approval is the ONLY path that makes a partner directory-visible, so it
    must not depend on caller-specific row choreography. In one transaction
    it:

    - stamps the current round's ``partner_credentials`` rows ``verified =
      true`` (round-scoped so a re-approval of a re-verification round never
      touches the already-approved round's history; revoked rows are left
      alone - a revoked credential stays invisible regardless),
    - refreshes the partner's ``partner_directory_index`` row through
      :func:`refresh_directory_entry`, the shared projection write the doctor's
      own address save also calls, so the two paths can never disagree about
      which position and specialties the entry carries (the refresh writes only
      for a partner whose recorded status is ``[Active]``, which the status flip
      above has just made true in this same transaction), and
    - flips that entry's listed flag to true.

    The listed flag is the one index column that does NOT move into the shared
    refresh, and the separation is deliberate (#607): the refresh is reachable
    from a doctor's own profile save, and ``is_active`` is one of the four
    AND-ed clauses of ``provider_visible``. It stays here, behind the only path
    to ``[Active]`` that exists (ADR-0008), so a doctor cannot list themselves by
    editing their own profile. The row this transition creates takes the
    column's server default on insert; the statement below is what makes an
    already-deindexed entry listed again on re-approval.

    All writes happen inside the caller's transaction (ADR-0002 §1), matching
    ``close_out_credentials``. The caller (the operator-gate approve path)
    still owns the status flip, the verification decision row and the
    ``partner.activated`` event; this transition owns the credential-verified
    stamp, the listed flag, and the entry bookkeeping that the read-side
    ``provider_visible`` predicate and the directory projection depend on.
    """
    await connection.execute(
        partner_credentials.update()
        .where(
            partner_credentials.c.profile_id == partner_id,
            partner_credentials.c.round == round,
            partner_credentials.c.revoked_at.is_(None),
        )
        .values(verified=True, updated_at=func.now())
    )
    await refresh_directory_entry(connection, partner_id)
    await connection.execute(
        partner_directory_index.update()
        .where(partner_directory_index.c.partner_id == partner_id)
        .values(is_active=True, updated_at=func.now())
    )
