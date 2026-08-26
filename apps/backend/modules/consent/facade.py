"""MOD-004 Consent management: typed public sync API.

The only legal cross-module import target for the ``consent`` module
(coding-standards §2, ADR-0003). PHASE-3 T3 (#212) lands the patient-driven
lifecycle over real lineages: ``request_consent`` opens a lineage in
``Requested``, ``grant_consent`` is the zero-ask patient-initiated grant
(resolve-or-create the triple's lineage, then mint its next version),
``grant_requested`` promotes an existing request, ``revoke_consent`` stops
all future access (durable-before-inactive: the terminal write commits
before anything treats the grant as inactive), ``decline_consent`` closes a
request without creating any grant, and ``list_consents`` answers the
patient's log - pending asks first, every revoked grant still listed with
its expandable version history.

Every mutating action appends its ``consent_events`` ledger row and writes
its bus envelopes (``consent.requested/granted/revoked`` plus the generic
``audit.event``, KPI-006) into ``consent.consent_outbox`` in the SAME
transaction as the state change (ADR-0002 §1). All decisions come from the
pure :mod:`modules.consent.domain.state_machine`; this layer only persists.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.config import Settings
from bus.outbox_writer import write_outbox
from modules.consent.domain.events import (
    ConsentAuditAction,
    RecordScope,
    consent_audit_envelope,
    consent_granted_envelope,
    consent_requested_envelope,
    consent_revoked_envelope,
)
from modules.consent.domain.exceptions import (
    ConsentAccessDeniedError,
    ConsentError,
    ConsentNotFoundError,
    IllegalConsentTransitionError,
)
from modules.consent.domain.state_machine import (
    RECORD_SCOPES,
    REQUESTED,
    ConsentAction,
    ConsentState,
    ConsentStatus,
    transition,
)
from modules.consent.outbox import CONSENT_OUTBOX_TABLE
from modules.consent.redis_cache import (
    get_cached_decision,
    invalidate_cached_decision,
    set_cached_decision,
)
from modules.consent.schema.models import consent_consents, consent_egress_log, consent_events

CONSENT_SCHEMA = "consent"

CounterpartyTypeLiteral = Literal["doctor", "lab", "chemist"]


class ConsentDecision(BaseModel):
    """The pure, four-field contract of the consent gate (PHASE-3 T4, #213).

    Every PHI share/egress calls this gate. Returns exactly these four fields;
    no side effects, no egress writing (callers disclose then record egress
    separately). Fail-closed on cache miss, DB error, or unknown state.
    """

    allowed: bool
    consent_id: int | None
    version: int | None
    effective_scope: str | None


def _scope_subsumes(requested: str, granted: str) -> bool:
    """Return True if ``granted`` scope subsumes ``requested`` scope.

    ``full_record`` subsumes every KNOWN specific scope (CONTEXT.md glossary).
    Exact match also passes. Unknown requested scopes are denied.
    """
    if requested not in RECORD_SCOPES:
        return False
    if granted == "full_record":
        return True
    return requested == granted


class ConsentEventView(BaseModel):
    """One immutable lifecycle ledger row, newest-first in the list order."""

    kind: str
    version: int
    actor_patient_id: int
    occurred_at: datetime


class ConsentView(BaseModel):
    """The documented typed contract of one consent lineage (FEAT-002).

    ``status`` + ``version`` are the live state; ``events`` is the lineage's
    full immutable history, so a revoked grant stays listed with exactly the
    receipts the audit trail cites.
    """

    consent_id: int
    lineage_ref: str
    patient_id: int
    counterparty_type: str
    counterparty_id: str
    record_scope: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
    events: list[ConsentEventView]


class ConsentLog(BaseModel):
    """The patient's consent log: pending requests first, then recent activity."""

    items: list[ConsentView]


class EgressLogEntry(BaseModel):
    """One egress log row: what left the record, when, to whom, and under which consent version."""

    egress_id: int
    patient_id: int
    consent_id: int | None
    lineage_ref: str
    version: int
    counterparty_type: str
    counterparty_id: str
    record_scope: str
    disclosed_entry_ids: list[int]
    disclosed_at: datetime


class EgressLog(BaseModel):
    """The patient's egress log: every consent-gated disclosure from their record."""

    items: list[EgressLogEntry]


_EVENT_KINDS: dict[ConsentStatus, str] = {
    ConsentStatus.REQUESTED: "requested",
    ConsentStatus.GRANTED: "granted",
    ConsentStatus.REVOKED: "revoked",
    ConsentStatus.DECLINED: "declined",
}

_AUDIT_ACTIONS: dict[ConsentAction, ConsentAuditAction] = {
    ConsentAction.GRANT: "granted",
    ConsentAction.REVOKE: "revoked",
    ConsentAction.DECLINE: "declined",
}

_PENDING_FIRST = case(
    (consent_consents.c.status == ConsentStatus.REQUESTED.value, 0),
    else_=1,
)


@dataclass(frozen=True)
class _Lineage:
    """One consent lineage row, already converted off the driver."""

    consent_id: int
    patient_id: int
    counterparty_type: str
    counterparty_id: str
    record_scope: str
    lineage_ref: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime

    @property
    def state(self) -> ConsentState:
        return ConsentState(status=ConsentStatus(self.status), version=self.version)


def _to_lineage(row: Row[Any]) -> _Lineage:
    # ``lineage_ref`` is briefly NULL inside the creating transaction; the
    # empty-string stand-in keeps the minting check falsy until it is set.
    return _Lineage(
        consent_id=int(row.id),
        patient_id=int(row.patient_id),
        counterparty_type=str(row.counterparty_type),
        counterparty_id=str(row.counterparty_id),
        record_scope=str(row.record_scope),
        lineage_ref=str(row.lineage_ref) if row.lineage_ref is not None else "",
        status=str(row.status),
        version=int(row.version),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


_LINEAGE_COLUMNS = (
    consent_consents.c.id,
    consent_consents.c.patient_id,
    consent_consents.c.counterparty_type,
    consent_consents.c.counterparty_id,
    consent_consents.c.record_scope,
    consent_consents.c.lineage_ref,
    consent_consents.c.status,
    consent_consents.c.version,
    consent_consents.c.created_at,
    consent_consents.c.updated_at,
)


async def _upsert_lineage(
    connection: AsyncConnection,
    patient_id: int,
    counterparty_type: str,
    counterparty_id: str,
    record_scope: str,
) -> tuple[_Lineage, bool]:
    """Return the triple's locked lineage row and whether THIS call created it.

    ``INSERT ... ON CONFLICT DO NOTHING`` then re-read under ``FOR UPDATE``,
    never SELECT-then-INSERT: the unique lineage key converges concurrent
    writers onto the winning row, so racing requests can never fork one
    lineage (the duplicate-resolution rule applied to consents). A row this
    call created mints its human reference ``C-YYYY-NNN`` from its own id
    inside the same transaction. The reference starts life as SQL NULL -
    unlike a shared placeholder, concurrent creations of DIFFERENT triples
    cannot collide on it (Postgres unique indexes treat NULLs as distinct) -
    and a lost race whose winner rolled back retries the insert once before
    giving up.
    """
    for _attempt in range(2):
        inserted = await connection.execute(
            postgresql_insert(consent_consents)
            .values(
                patient_id=patient_id,
                counterparty_type=counterparty_type,
                counterparty_id=counterparty_id,
                record_scope=record_scope,
                status=REQUESTED.status.value,
                version=REQUESTED.version,
                # Minted below from the assigned id + created_at.
                lineage_ref=None,
            )
            .on_conflict_do_nothing(constraint="uq_consent_consents_lineage")
        )
        created = int(inserted.rowcount or 0) == 1
        existing = (
            await connection.execute(
                select(*_LINEAGE_COLUMNS)
                .where(
                    consent_consents.c.patient_id == patient_id,
                    consent_consents.c.counterparty_type == counterparty_type,
                    consent_consents.c.counterparty_id == counterparty_id,
                    consent_consents.c.record_scope == record_scope,
                )
                .with_for_update()
            )
        ).first()
        if existing is None:
            # The winner rolled back between our miss and this read; try again.
            continue
        lineage = _to_lineage(existing)
        if not lineage.lineage_ref:
            minted = f"C-{lineage.created_at.year}-{lineage.consent_id:03d}"
            await connection.execute(
                consent_consents.update()
                .where(consent_consents.c.id == lineage.consent_id)
                .values(lineage_ref=minted)
            )
            lineage = replace(lineage, lineage_ref=minted)
        return lineage, created
    raise ConsentError("could not establish the consent lineage")


async def _lock_by_id(connection: AsyncConnection, patient_id: int, consent_id: int) -> _Lineage:
    """Load one lineage ``FOR UPDATE`` and refuse non-owners (api-standards §6).

    The facade is the authorization boundary - the gateway check is
    convenience - so every id-addressed action re-checks ownership against
    the session subject inside the same transaction that applies the change.
    """
    row = (
        await connection.execute(
            select(*_LINEAGE_COLUMNS).where(consent_consents.c.id == consent_id).with_for_update()
        )
    ).first()
    if row is None:
        raise ConsentNotFoundError(consent_id)
    lineage = _to_lineage(row)
    if lineage.patient_id != patient_id:
        raise ConsentAccessDeniedError("only the owning patient may act on this consent")
    return lineage


def _payload_triple(lineage: _Lineage) -> tuple[CounterpartyTypeLiteral, str, RecordScope]:
    """Narrow the persisted strings onto the closed payload literals."""
    return (
        cast(CounterpartyTypeLiteral, lineage.counterparty_type),
        lineage.counterparty_id,
        cast(RecordScope, lineage.record_scope),
    )


async def _persist_transition(
    connection: AsyncConnection,
    lineage: _Lineage,
    action: ConsentAction,
) -> ConsentState:
    """Decide with the pure machine, persist the flip, ledger, and fan out.

    One transaction carries ALL of: the row's status/version update, the
    append-only ``consent_events`` ledger row, the lifecycle bus event (none
    for decline - the §4.2 registry defines no such event) and the generic
    ``audit.event`` covering EVERY action (KPI-006).
    """
    next_state = transition(lineage.state, action)
    publish_lifecycle = action is not ConsentAction.DECLINE
    await connection.execute(
        consent_consents.update()
        .where(consent_consents.c.id == lineage.consent_id)
        .values(
            status=next_state.status.value,
            version=next_state.version,
            updated_at=func.now(),
        )
    )
    await connection.execute(
        consent_events.insert().values(
            consent_id=lineage.consent_id,
            kind=_EVENT_KINDS[next_state.status],
            version=next_state.version,
            actor_patient_id=lineage.patient_id,
        )
    )
    counterparty_type, counterparty_id, record_scope = _payload_triple(lineage)
    if publish_lifecycle:
        envelope_builders = {
            ConsentAction.GRANT: consent_granted_envelope,
            ConsentAction.REVOKE: consent_revoked_envelope,
        }
        envelope = envelope_builders[action](
            lineage.consent_id,
            lineage.lineage_ref,
            lineage.patient_id,
            counterparty_type,
            counterparty_id,
            record_scope,
            next_state.version,
        )
        await write_outbox(connection, CONSENT_SCHEMA, CONSENT_OUTBOX_TABLE, envelope)
    await write_outbox(
        connection,
        CONSENT_SCHEMA,
        CONSENT_OUTBOX_TABLE,
        consent_audit_envelope(
            action=_AUDIT_ACTIONS[action],
            actor_patient_id=lineage.patient_id,
            consent_id=lineage.consent_id,
            lineage_ref=lineage.lineage_ref,
            record_scope=record_scope,
            version=next_state.version,
        ),
    )
    return next_state


async def _load_history(
    connection: AsyncConnection, consent_ids: list[int]
) -> dict[int, list[ConsentEventView]]:
    """Fetch the named lineages' ledger rows, newest first, grouped by id."""
    if not consent_ids:
        return {}
    rows = (
        await connection.execute(
            select(
                consent_events.c.consent_id,
                consent_events.c.kind,
                consent_events.c.version,
                consent_events.c.actor_patient_id,
                consent_events.c.occurred_at,
            )
            .where(consent_events.c.consent_id.in_(consent_ids))
            .order_by(
                consent_events.c.consent_id,
                consent_events.c.occurred_at.desc(),
                consent_events.c.id.desc(),
            )
        )
    ).all()
    grouped: dict[int, list[ConsentEventView]] = {}
    for row in rows:
        grouped.setdefault(int(row.consent_id), []).append(
            ConsentEventView(
                kind=str(row.kind),
                version=int(row.version),
                actor_patient_id=int(row.actor_patient_id),
                occurred_at=row.occurred_at,
            )
        )
    return grouped


def _to_view(lineage: _Lineage, history: list[ConsentEventView]) -> ConsentView:
    return ConsentView(
        consent_id=lineage.consent_id,
        lineage_ref=lineage.lineage_ref,
        patient_id=lineage.patient_id,
        counterparty_type=lineage.counterparty_type,
        counterparty_id=lineage.counterparty_id,
        record_scope=lineage.record_scope,
        status=lineage.status,
        version=lineage.version,
        created_at=lineage.created_at,
        updated_at=lineage.updated_at,
        events=history,
    )


async def _view_after_write(connection: AsyncConnection, lineage: _Lineage) -> ConsentView:
    """Reload the post-transition lineage and answer its typed view."""
    row = (
        await connection.execute(
            select(*_LINEAGE_COLUMNS).where(consent_consents.c.id == lineage.consent_id)
        )
    ).one()
    fresh = _to_lineage(row)
    history = await _load_history(connection, [fresh.consent_id])
    return _to_view(fresh, history.get(fresh.consent_id, []))


class ConsentFacade:
    """Typed public facade for the consent module's lifecycle surface."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def request_consent(
        self,
        patient_id: int,
        counterparty_type: CounterpartyTypeLiteral,
        counterparty_id: str,
        record_scope: str,
    ) -> ConsentView:
        """Open a consent ask: the lineage enters ``Requested`` (v0).

        A triple already living in ANY state refuses a second ask - the
        binding machine has no edge back into ``Requested`` - so a duplicate
        request answers ``409 CONSENT_INVALID_TRANSITION`` instead of
        silently resetting a live or decided lineage.
        """
        async with self._engine.begin() as connection:
            lineage, created = await _upsert_lineage(
                connection, patient_id, counterparty_type, counterparty_id, record_scope
            )
            if not created:
                raise IllegalConsentTransitionError(
                    f"request is illegal while the consent is {lineage.status}"
                )
            await connection.execute(
                consent_events.insert().values(
                    consent_id=lineage.consent_id,
                    kind="requested",
                    version=REQUESTED.version,
                    actor_patient_id=lineage.patient_id,
                )
            )
            counterparty_typed, counterparty_id_typed, record_scope_typed = _payload_triple(lineage)
            await write_outbox(
                connection,
                CONSENT_SCHEMA,
                CONSENT_OUTBOX_TABLE,
                consent_requested_envelope(
                    lineage.consent_id,
                    lineage.lineage_ref,
                    lineage.patient_id,
                    counterparty_typed,
                    counterparty_id_typed,
                    record_scope_typed,
                ),
            )
            await write_outbox(
                connection,
                CONSENT_SCHEMA,
                CONSENT_OUTBOX_TABLE,
                consent_audit_envelope(
                    action="requested",
                    actor_patient_id=lineage.patient_id,
                    consent_id=lineage.consent_id,
                    lineage_ref=lineage.lineage_ref,
                    record_scope=record_scope_typed,
                    version=REQUESTED.version,
                ),
            )
            return await _view_after_write(connection, lineage)

    async def grant_consent(
        self,
        patient_id: int,
        counterparty_type: CounterpartyTypeLiteral,
        counterparty_id: str,
        record_scope: str,
    ) -> ConsentView:
        """Patient-initiated standing grant on the triple's lineage.

        Resolves or creates the lineage, then mints its next version - v1 on
        a fresh or previously-declined triple, vN+1 on a live or revoked one
        (re-grant never rewrites history). Illegal states reject through the
        pure machine.
        """
        async with self._engine.begin() as connection:
            lineage, _created = await _upsert_lineage(
                connection, patient_id, counterparty_type, counterparty_id, record_scope
            )
            await _persist_transition(connection, lineage, ConsentAction.GRANT)
            view = await _view_after_write(connection, lineage)
        # Invalidate cache after commit (outside transaction)
        await self._invalidate_cache(patient_id, counterparty_type, counterparty_id, record_scope)
        return view

    async def grant_requested(self, patient_id: int, consent_id: int) -> ConsentView:
        """Promote an existing ``Requested`` lineage to its first live grant."""
        async with self._engine.begin() as connection:
            lineage = await _lock_by_id(connection, patient_id, consent_id)
            counterparty_type = lineage.counterparty_type
            counterparty_id = lineage.counterparty_id
            record_scope = lineage.record_scope
            await _persist_transition(connection, lineage, ConsentAction.GRANT)
            view = await _view_after_write(connection, lineage)
        # Invalidate cache after commit (outside transaction)
        await self._invalidate_cache(patient_id, counterparty_type, counterparty_id, record_scope)
        return view

    async def revoke_consent(self, patient_id: int, consent_id: int) -> ConsentView:
        """Revoke the live grant: terminal for that version, durable first.

        The commit below IS the durability point - once it lands, every later
        reader sees ``revoked`` before anything treats the grant as inactive.
        """
        async with self._engine.begin() as connection:
            lineage = await _lock_by_id(connection, patient_id, consent_id)
            # Capture the triple before revoking for cache invalidation
            counterparty_type = lineage.counterparty_type
            counterparty_id = lineage.counterparty_id
            record_scope = lineage.record_scope
            await _persist_transition(connection, lineage, ConsentAction.REVOKE)
            view = await _view_after_write(connection, lineage)
        # Invalidate cache after commit (outside transaction)
        await self._invalidate_cache(patient_id, counterparty_type, counterparty_id, record_scope)
        return view

    async def decline_consent(self, patient_id: int, consent_id: int) -> ConsentView:
        """Close a request without creating any grant (audit-only emission)."""
        async with self._engine.begin() as connection:
            lineage = await _lock_by_id(connection, patient_id, consent_id)
            await _persist_transition(connection, lineage, ConsentAction.DECLINE)
            return await _view_after_write(connection, lineage)

    async def list_consents(self, patient_id: int) -> ConsentLog:
        """Answer the patient's log: pending first, then most-recent activity."""
        async with self._engine.begin() as connection:
            rows = (
                await connection.execute(
                    select(*_LINEAGE_COLUMNS)
                    .where(consent_consents.c.patient_id == patient_id)
                    .order_by(
                        _PENDING_FIRST,
                        consent_consents.c.updated_at.desc(),
                        consent_consents.c.id.desc(),
                    )
                )
            ).all()
            lineages = [_to_lineage(row) for row in rows]
            history = await _load_history(connection, [lineage.consent_id for lineage in lineages])
            return ConsentLog(
                items=[
                    _to_view(lineage, history.get(lineage.consent_id, [])) for lineage in lineages
                ]
            )

    async def list_egress_log(self, patient_id: int) -> EgressLog:
        """Answer the patient's egress log: every consent-gated disclosure from their record.

        Returns all rows from ``consent_egress_log`` for this patient, newest
        disclosure first. Each row cites the consent lineage (consent_id,
        lineage_ref, version), the counterparty (type + id), the scope that
        was disclosed, and the exact entry IDs that were shared.
        """
        async with self._engine.begin() as connection:
            rows = (
                await connection.execute(
                    select(
                        consent_egress_log.c.id,
                        consent_egress_log.c.patient_id,
                        consent_egress_log.c.consent_id,
                        consent_egress_log.c.lineage_ref,
                        consent_egress_log.c.version,
                        consent_egress_log.c.counterparty_type,
                        consent_egress_log.c.counterparty_id,
                        consent_egress_log.c.record_scope,
                        consent_egress_log.c.disclosed_entry_ids,
                        consent_egress_log.c.disclosed_at,
                    )
                    .where(consent_egress_log.c.patient_id == patient_id)
                    .order_by(
                        consent_egress_log.c.disclosed_at.desc(),
                        consent_egress_log.c.id.desc(),
                    )
                )
            ).all()
            return EgressLog(
                items=[
                    EgressLogEntry(
                        egress_id=int(row.id),
                        patient_id=int(row.patient_id),
                        consent_id=int(row.consent_id) if row.consent_id is not None else None,
                        lineage_ref=str(row.lineage_ref),
                        version=int(row.version),
                        counterparty_type=str(row.counterparty_type),
                        counterparty_id=str(row.counterparty_id),
                        record_scope=str(row.record_scope),
                        disclosed_entry_ids=list(row.disclosed_entry_ids)
                        if row.disclosed_entry_ids
                        else [],
                        disclosed_at=row.disclosed_at,
                    )
                    for row in rows
                ]
            )

    async def record_egress_disclosure(
        self,
        patient_id: int,
        consent_id: int | None,
        version: int,
        counterparty_type: str,
        counterparty_id: str,
        record_scope: str,
        disclosed_entry_ids: list[int],
    ) -> None:
        """Record one egress log row in its own transaction (FIX-7, #227).

        Called by HealthFacade after the health transaction commits.  The
        consent module owns the transaction boundary here - the caller
        never passes a connection.  Fetches lineage_ref from the consent
        lineage internally.

        ADR: Two separate transactions (health access-history, then consent
        egress-log) are acceptable because (a) the egress log is an
        append-only audit row whose absence is detectable, and (b) a true
        cross-schema two-phase commit would add disproportionate complexity
        for marginal consistency gain (coding-standards S2, ADR-0003).
        """
        async with self._engine.begin() as connection:
            await self._write_egress_log(
                connection=connection,
                patient_id=patient_id,
                consent_id=consent_id,
                version=version,
                counterparty_type=counterparty_type,
                counterparty_id=counterparty_id,
                record_scope=record_scope,
                disclosed_entry_ids=disclosed_entry_ids,
            )

    async def _write_egress_log(
        self,
        connection: AsyncConnection,
        patient_id: int,
        consent_id: int | None,
        version: int,
        counterparty_type: str,
        counterparty_id: str,
        record_scope: str,
        disclosed_entry_ids: list[int],
    ) -> None:
        """Write one egress log row within an existing transaction (internal)."""
        lineage_ref = ""
        if consent_id is not None:
            lineage_ref = (
                await connection.execute(
                    select(consent_consents.c.lineage_ref).where(
                        consent_consents.c.id == consent_id
                    )
                )
            ).scalar_one_or_none() or ""
        await connection.execute(
            consent_egress_log.insert().values(
                patient_id=patient_id,
                consent_id=consent_id,
                lineage_ref=lineage_ref,
                version=version,
                counterparty_type=counterparty_type,
                counterparty_id=counterparty_id,
                record_scope=record_scope,
                disclosed_entry_ids=disclosed_entry_ids,
            )
        )

    async def seed_egress_log(
        self,
        patient_id: int,
        counterparty_type: str,
        counterparty_id: str,
        record_scope: str,
        disclosed_entry_ids: list[int],
    ) -> int:
        """Insert a synthetic egress log row for test seeding (dev/test only).

        Finds any existing consent for this patient to link the egress row,
        then inserts a row into ``consent_egress_log``. Returns the new row id.
        Used by the ``/v1/test/seed-egress`` endpoint so it does not import
        raw schema models.
        """
        async with self._engine.begin() as connection:
            consent_row = (
                await connection.execute(
                    select(consent_consents.c.id).where(consent_consents.c.patient_id == patient_id)
                )
            ).scalar_one_or_none()
            result = await connection.execute(
                consent_egress_log.insert()
                .values(
                    patient_id=patient_id,
                    consent_id=int(consent_row) if consent_row else 0,
                    lineage_ref="C-E2E-001",
                    version=1,
                    counterparty_type=counterparty_type,
                    counterparty_id=counterparty_id,
                    record_scope=record_scope,
                    disclosed_entry_ids=disclosed_entry_ids,
                )
                .returning(consent_egress_log.c.id)
            )
            return int(result.scalar_one())

    async def check_consent(
        self,
        patient_id: int,
        counterparty_type: CounterpartyTypeLiteral,
        counterparty_id: str,
        record_scope: str,
        settings: Settings | None = None,
    ) -> ConsentDecision:
        """The fail-closed consent gate (PHASE-3 T4, #213).

        Pure for arbitrary inputs: answers ``allowed`` + ``consent_id`` +
        ``version`` + ``effective_scope`` - nothing more. No side effects,
        no egress writing. Redis cache keyed on patient+scope+counterparty
        keeps it invisible (p95 < 50 ms); SQL fallback passes the same
        behavioral suite standing alone. ``full_record`` subsumes every
        specific scope when matching. Fail closed on cache miss, DB error,
        or unknown state.

        Args:
            patient_id: The patient whose record is being accessed.
            counterparty_type: The type of counterparty (doctor, lab, chemist).
            counterparty_id: The identifier of the counterparty.
            record_scope: The requested record scope.
            settings: Optional settings for cache TTL; if None, cache is skipped.

        Returns:
            ConsentDecision with allowed, consent_id, version, effective_scope.
        """
        # Try Redis cache first (if configured)
        if settings is not None:
            cached = await get_cached_decision(
                patient_id, counterparty_type, counterparty_id, record_scope
            )
            if cached is not None:
                allowed, consent_id, version, effective_scope = cached
                return ConsentDecision(
                    allowed=allowed,
                    consent_id=consent_id,
                    version=version,
                    effective_scope=effective_scope,
                )

        # SQL fallback: find the best matching GRANTED lineage
        decision = await self._check_consent_sql(
            patient_id, counterparty_type, counterparty_id, record_scope
        )

        # Write back to cache (best-effort)
        if settings is not None and decision.allowed:
            await set_cached_decision(
                patient_id=patient_id,
                counterparty_type=counterparty_type,
                counterparty_id=counterparty_id,
                record_scope=record_scope,
                allowed=decision.allowed,
                consent_id=decision.consent_id or 0,
                version=decision.version or 0,
                effective_scope=decision.effective_scope or "",
                ttl_seconds=settings.redis_consent_ttl_seconds,
            )

        return decision

    async def _check_consent_sql(
        self,
        patient_id: int,
        counterparty_type: str,
        counterparty_id: str,
        record_scope: str,
    ) -> ConsentDecision:
        """SQL fallback for consent check - pure, fail-closed."""
        async with self._engine.begin() as connection:
            # Find all GRANTED lineages for this patient+counterparty
            rows = (
                await connection.execute(
                    select(*_LINEAGE_COLUMNS).where(
                        consent_consents.c.patient_id == patient_id,
                        consent_consents.c.counterparty_type == counterparty_type,
                        consent_consents.c.counterparty_id == counterparty_id,
                        consent_consents.c.status == ConsentStatus.GRANTED.value,
                    )
                )
            ).all()

            if not rows:
                return ConsentDecision(
                    allowed=False,
                    consent_id=None,
                    version=None,
                    effective_scope=None,
                )

            # Check if any granted scope subsumes the requested scope
            for row in rows:
                lineage = _to_lineage(row)
                if _scope_subsumes(record_scope, lineage.record_scope):
                    return ConsentDecision(
                        allowed=True,
                        consent_id=lineage.consent_id,
                        version=lineage.version,
                        effective_scope=lineage.record_scope,
                    )

            # No matching scope found
            return ConsentDecision(
                allowed=False,
                consent_id=None,
                version=None,
                effective_scope=None,
            )

    async def _invalidate_cache(
        self,
        patient_id: int,
        counterparty_type: str,
        counterparty_id: str,
        record_scope: str,
    ) -> None:
        """Best-effort cache invalidation after a consent write."""
        await invalidate_cached_decision(
            patient_id, counterparty_type, counterparty_id, record_scope
        )
