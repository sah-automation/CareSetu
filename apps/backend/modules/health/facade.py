"""MOD-003 Health data: typed public sync API.

The only legal cross-module import target for the ``health``
module (coding-standards S2, ADR-0003). PHASE-3 T2 (#211) lands the
longitudinal-record core: ``create_record`` (the idempotent shell creation
the ``patient.registered`` subscriber calls), and the owner-only record
reads - ``get_own_record`` resolves the caller's identity,
``get_record_as_owner`` reads an addressed record and refuses non-owners.
Every read attempt - owner or not, allowed or denied - is recorded in the
``health_record_access_history`` ledger in the same transaction as the read
(MOD-003 NFR: KPI-006, 100% of record accesses logged). PHASE-3 T5 (#214)
adds ``read_consented_history`` for partner reads gated by MOD-004's
``check_consent`` and dual-ledger writes (access history + egress log).

FIX-7 (#227): The egress log write is delegated to
``ConsentFacade.record_egress_disclosure`` which runs in its own
transaction.  This preserves the module boundary (no consent schema
imports) while accepting two-transaction eventual consistency for the
append-only egress audit row (see inline ADR in ``read_consented_history``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

# Type-only import to avoid circular dependency at runtime
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.config import Settings
from bus.outbox_writer import write_outbox
from modules.health.domain.events import record_accessed_envelope, record_denied_envelope
from modules.health.domain.exceptions import (
    HealthBackgroundAcknowledgmentRequiredError as HealthBackgroundAcknowledgmentRequiredError,
)
from modules.health.domain.exceptions import (
    RecordAccessDeniedError as RecordAccessDeniedError,
)
from modules.health.domain.exceptions import (
    RecordNotFoundError as RecordNotFoundError,
)
from modules.health.outbox import HEALTH_OUTBOX_TABLE
from modules.health.schema.models import (
    health_background_metrics,
    health_background_snapshots,
    health_patient_records,
    health_record_access_history,
    health_record_entries,
)

if TYPE_CHECKING:
    from modules.care.facade import CaseConsoleFacade
    from modules.consent.facade import ConsentFacade

HEALTH_SCHEMA = "health"

# The default page size for the patient's height/weight series list (api-standards
# §4: default 25, max 100). ONE named constant owned by the module, read by both
# the route's query default and the facade method's own default, so the two
# spellings of the page size can never drift.
DEFAULT_HEALTH_BACKGROUND_PER_PAGE: Final[int] = 25

# The default scope for an owner's own read of their complete record; matches
# the consent ``RecordScope`` vocabulary ("full_record").
_OWNER_SCOPE = "full_record"

# The consent record scope the acknowledged first health-background save auto-
# grants to live-relationship doctors (ADR-0018, #534). Matches the consent
# vocabulary ("health_background"); ``full_record`` subsumes it when gated.
_HEALTH_BACKGROUND_SCOPE = "health_background"

_ACTOR_TYPE_PATIENT = "patient"

_ACTOR_TYPE_DOCTOR: Literal["doctor", "lab", "chemist"] = "doctor"

# The access-history scope marker for the doctor-console Patients list
# (MOD-012, ADR-0019). A list row has no single record entry or consent
# scope - the ledger's scope column is deliberately caller-supplied, so this
# marker keeps the "doctor saw this patient's list row" signal distinct from
# any record-entry disclosure, without pretending a consent scope was read.
_DOCTOR_PATIENTS_LIST_SCOPE = "doctor_patients_list"

# The consent counterparty type the first acknowledged health-background save
# targets for auto-grant (#534) - matches the consent vocabulary.
_COUNTERPARTY_TYPE_DOCTOR: Literal["doctor", "lab", "chemist"] = "doctor"

# Result payload type of a consent-gated record read (the spine in
# ``_consent_gated_read``); keeps the shared helper sound under --strict.
_T = TypeVar("_T")

# Explicit ceilings on the free-form health-background list areas (US-21/22,
# #534). The columns are unbounded JSONB, so a PHI write would otherwise have no
# cap at all; these bounds are enforced at the typed boundary so an overrun is a
# 422, never a stored unbounded payload. Both are generous enough for real
# clinical history (a decade of chronic conditions, or a full immunisation
# record) while still bounding one snapshot.
_HEALTH_BACKGROUND_MAX_LIST_ITEMS = 50
_HEALTH_BACKGROUND_MAX_ITEM_LENGTH = 200

#: One bounded free-text entry in a list area (a single condition, allergy, ...).
_HealthBackgroundItem = Annotated[str, Field(max_length=_HEALTH_BACKGROUND_MAX_ITEM_LENGTH)]


class HealthBackground(BaseModel):
    """The patient-authored health-background snapshot (#534, US-21/US-22).

    Blood group as a single value plus the free-form list areas - conditions,
    allergies, current medications, immunizations, family history - each an
    ordered list of the patient's own entries. The wire contract of the
    ``/v1/me/health-background`` GET/PUT surface; height/weight time series
    live in a separate ticket. Every field is explicitly bounded and extra
    fields are refused (``extra="forbid"``), matching ``HealthBackgroundMetric``:
    a patient-authored PHI write has a ceiling on size as well as on shape.
    """

    model_config = ConfigDict(extra="forbid")

    blood_group: str | None = Field(default=None, max_length=16)
    conditions: list[_HealthBackgroundItem] = Field(
        default_factory=list, max_length=_HEALTH_BACKGROUND_MAX_LIST_ITEMS
    )
    allergies: list[_HealthBackgroundItem] = Field(
        default_factory=list, max_length=_HEALTH_BACKGROUND_MAX_LIST_ITEMS
    )
    medications: list[_HealthBackgroundItem] = Field(
        default_factory=list, max_length=_HEALTH_BACKGROUND_MAX_LIST_ITEMS
    )
    immunizations: list[_HealthBackgroundItem] = Field(
        default_factory=list, max_length=_HEALTH_BACKGROUND_MAX_LIST_ITEMS
    )
    family_history: list[_HealthBackgroundItem] = Field(
        default_factory=list, max_length=_HEALTH_BACKGROUND_MAX_LIST_ITEMS
    )


class HealthBackgroundView(BaseModel):
    """Typed read-back of the health-background snapshot surface (#534).

    ``set`` discriminates a stored snapshot (``background`` populated) from
    the typed "not recorded" answer the PWA hydrates from before its local
    draft - the same discriminator shape as the profile read (#533). ``acknowledged``
    tells the client whether the one-time first-save confirmation has already
    been given, so it only prompts before that first acknowledged save (later
    edits never re-prompt). The same shape answers GET and PUT so the client
    handles one contract.
    """

    set: bool
    acknowledged: bool
    background: HealthBackground | None = None


class HealthBackgroundMetric(BaseModel):
    """One timestamped height/weight measurement the patient appends (#535, US-23).

    Height in cm and weight in kg, each with a plausible range matching the
    column CHECKs; at least one of the two must be present. ``recorded_at`` is
    the patient-authored measurement timestamp - the trend anchor the series
    orders on - and is required. The row id is never client-supplied: extra
    fields (``extra="forbid"``) and server-minted ids keep the client from
    choosing its own identity for a series row.
    """

    model_config = ConfigDict(extra="forbid")

    height_cm: float | None = Field(default=None, ge=30, le=250)
    weight_kg: float | None = Field(default=None, ge=1, le=500)
    recorded_at: datetime

    @model_validator(mode="after")
    def _require_at_least_one_value(self) -> HealthBackgroundMetric:
        if self.height_cm is None and self.weight_kg is None:
            raise ValueError("at least one of height_cm or weight_kg is required")
        return self


class HealthBackgroundMetricEntry(BaseModel):
    """One stored measurement on the series, newest-first in the list order."""

    entry_id: int
    height_cm: float | None
    weight_kg: float | None
    recorded_at: datetime


class HealthBackgroundMetricList(BaseModel):
    """One page of the height/weight series, newest-first (api-standards §4).

    ``items`` is the bounded page ordered by ``(recorded_at, id)`` descending;
    ``total`` is the full series length so the caller can page through the rest
    (offset pagination is the natural precedent in this module tree - the audit
    ledger read). A patient with no measurements answers an empty page.
    """

    items: list[HealthBackgroundMetricEntry]
    total: int


class RecordEntryView(BaseModel):
    """One clinical entry on the timeline, newest-first in the list order."""

    entry_id: int
    entry_type: str
    payload: dict[str, object]
    occurred_at: datetime
    created_at: datetime


class RecordTimeline(BaseModel):
    """The documented typed contract of the own-record view (FEAT-002/003).

    ``entries`` is reverse-chronological by clinical time (``occurred_at``);
    a freshly registered patient owns an empty timeline - zero setup.
    """

    record_id: int
    patient_id: int
    created_at: datetime
    entries: list[RecordEntryView]


class AccessHistoryEntry(BaseModel):
    """One read attempt on the patient's record as the trust view answers it.

    Every row of ``health_record_access_history`` becomes one entry: who read
    (``actor_id`` + ``actor_type``), over which scope, when, and whether the
    attempt was refused - with the ``denial_reason`` when it was (FEAT-003
    "who / how / why"). The health ledger is the fast patient-facing source;
    the hash-chained copy of the same acts lives in MOD-011's ``audit_events``.
    """

    actor_id: int
    actor_type: str | None
    scope: str | None
    accessed_at: datetime
    denied: bool
    denial_reason: str | None


class AccessHistoryView(BaseModel):
    """The typed contract of the patient access-history view (FEAT-003).

    ``entries`` is reverse-chronological by ``accessed_at``. A record no one
    has touched yet answers an empty list - never an error (zero-setup trust
    view for a freshly registered patient).
    """

    entries: list[AccessHistoryEntry]


async def _ensure_record_shell(connection: AsyncConnection, patient_id: int) -> int:
    """Resolve the patient's record id, creating the empty shell if absent.

    ``INSERT ... ON CONFLICT DO NOTHING`` then re-read, never SELECT-then-
    INSERT: the unique ``identity_id`` index converges concurrent creators
    (subscriber delivery racing a lazy owner read) onto the winning row, so
    at-least-once event replay can never duplicate a shell. Returns the
    existing or freshly created record id.
    """
    await connection.execute(
        postgresql_insert(health_patient_records)
        .values(identity_id=patient_id)
        .on_conflict_do_nothing(index_elements=["identity_id"])
    )
    record_id = (
        await connection.execute(
            select(health_patient_records.c.id).where(
                health_patient_records.c.identity_id == patient_id
            )
        )
    ).scalar_one()
    return int(record_id)


async def _log_access(
    connection: AsyncConnection,
    record_id: int,
    accessor_identity_id: int,
    outcome: str,
    *,
    actor_type: str,
    scope: str,
    denial_reason: str | None = None,
) -> None:
    """Record one read attempt in BOTH the access-history ledger and the outbox.

    Dual write (FEAT-003, KPI-006) in the caller's transaction: the
    ``health_record_access_history`` row feeds the fast patient view, and the
    ``record.accessed`` / ``record.denied`` event drives MOD-011's hash
    chain. The caller commits or rolls both back together.
    """
    accessed_at = datetime.now(UTC)
    # actor_type / scope / denial_reason persist next to the ledger row too
    # (PHASE-4 T7, #241) so the fast patient view answers who/how/why without
    # joining the outbox payload; denial_reason stays NULL for allowed reads.
    await connection.execute(
        health_record_access_history.insert().values(
            record_id=record_id,
            accessor_identity_id=accessor_identity_id,
            outcome=outcome,
            actor_type=actor_type,
            scope=scope,
            denial_reason=denial_reason,
        )
    )
    if outcome == "allowed":
        envelope = record_accessed_envelope(
            record_id=record_id,
            actor_id=accessor_identity_id,
            actor_type=actor_type,
            scope=scope,
            accessed_at=accessed_at,
        )
    else:
        envelope = record_denied_envelope(
            record_id=record_id,
            actor_id=accessor_identity_id,
            actor_type=actor_type,
            scope=scope,
            accessed_at=accessed_at,
            denial_reason=denial_reason or "access denied",
        )
    await write_outbox(connection, HEALTH_SCHEMA, HEALTH_OUTBOX_TABLE, envelope)


async def _load_timeline(
    connection: AsyncConnection, record_id: int, patient_id: int
) -> RecordTimeline:
    """Read the shell metadata plus its entries, newest clinical event first."""
    record_row = (
        await connection.execute(
            select(health_patient_records.c.created_at).where(
                health_patient_records.c.id == record_id
            )
        )
    ).one()
    entry_rows = (
        await connection.execute(
            select(
                health_record_entries.c.id,
                health_record_entries.c.entry_type,
                health_record_entries.c.payload,
                health_record_entries.c.occurred_at,
                health_record_entries.c.created_at,
            )
            .where(health_record_entries.c.record_id == record_id)
            .order_by(health_record_entries.c.occurred_at.desc(), health_record_entries.c.id.desc())
        )
    ).all()
    return RecordTimeline(
        record_id=record_id,
        patient_id=patient_id,
        created_at=record_row.created_at,
        entries=[
            RecordEntryView(
                entry_id=int(row.id),
                entry_type=str(row.entry_type),
                payload=dict(row.payload),
                occurred_at=row.occurred_at,
                created_at=row.created_at,
            )
            for row in entry_rows
        ],
    )


async def _load_health_background(
    connection: AsyncConnection, patient_id: int
) -> HealthBackgroundView:
    """Read the patient's snapshot on the caller's connection, or "not set".

    Owner-read (``get_health_background``) and consent-gated doctor-read
    (``read_consented_health_background``) paths share this; running inside
    the caller's connection keeps each read single-transaction and testable
    without a database.
    """
    row = (
        await connection.execute(
            select(
                health_background_snapshots.c.blood_group,
                health_background_snapshots.c.conditions,
                health_background_snapshots.c.allergies,
                health_background_snapshots.c.medications,
                health_background_snapshots.c.immunizations,
                health_background_snapshots.c.family_history,
                health_background_snapshots.c.acknowledged_at,
            ).where(health_background_snapshots.c.identity_id == patient_id)
        )
    ).first()
    if row is None:
        return HealthBackgroundView(set=False, acknowledged=False, background=None)
    return HealthBackgroundView(
        set=True,
        acknowledged=row.acknowledged_at is not None,
        background=HealthBackground(
            blood_group=row.blood_group,
            conditions=list(row.conditions),
            allergies=list(row.allergies),
            medications=list(row.medications),
            immunizations=list(row.immunizations),
            family_history=list(row.family_history),
        ),
    )


async def query_access_history(connection: AsyncConnection, patient_id: int) -> AccessHistoryView:
    """Read every access-history row for a patient's record, newest first.

    Resolves the patient's single record shell via ``health_patient_records``
    and selects every ``health_record_access_history`` row bound to it - owner
    reads, partner reads, and denied attempts alike - concretizing the
    ``denied`` flag from the ``outcome`` column. A patient whose record has
    never been touched answers an empty list. Running inside the caller's
    connection keeps the read single-transaction and testable without a
    database (same seam shape as MOD-011's ``query_audit_events``).
    """
    rows = (
        await connection.execute(
            select(
                health_record_access_history.c.accessor_identity_id,
                health_record_access_history.c.actor_type,
                health_record_access_history.c.scope,
                health_record_access_history.c.accessed_at,
                health_record_access_history.c.outcome,
                health_record_access_history.c.denial_reason,
            )
            .select_from(
                health_record_access_history.join(
                    health_patient_records,
                    health_record_access_history.c.record_id == health_patient_records.c.id,
                )
            )
            .where(health_patient_records.c.identity_id == patient_id)
            .order_by(
                health_record_access_history.c.accessed_at.desc(),
                health_record_access_history.c.id.desc(),
            )
        )
    ).all()
    return AccessHistoryView(
        entries=[
            AccessHistoryEntry(
                actor_id=int(row.accessor_identity_id),
                actor_type=row.actor_type,
                scope=row.scope,
                accessed_at=row.accessed_at,
                denied=row.outcome == "denied",
                denial_reason=row.denial_reason,
            )
            for row in rows
        ]
    )


def _metric_entry_from_row(row: Row[Any]) -> HealthBackgroundMetricEntry:
    """Concretize one ``health_background_metrics`` row as the typed entry.

    A ``Row[Any]`` proxy is genuinely required here (the columns are read off
    the driver row by attribute), typed explicitly rather than left a bare
    ``Any`` (coding-standards §3) - the same row alias the consent module's
    row mappers use.

    Height/weight arrive as ``Decimal`` from the ``Numeric`` columns; they are
    emitted as JSON numbers, never Decimal-backed strings (Pydantic v2
    serializes Decimal to string by default - see the intake confidence note).
    """
    return HealthBackgroundMetricEntry(
        entry_id=int(row.id),
        height_cm=float(row.height_cm) if row.height_cm is not None else None,
        weight_kg=float(row.weight_kg) if row.weight_kg is not None else None,
        recorded_at=row.recorded_at,
    )


class HealthFacade:
    """Typed public facade for the health module's record surface."""

    def __init__(
        self,
        engine: AsyncEngine,
        consent_facade: ConsentFacade | None = None,
        care_facade: CaseConsoleFacade | None = None,
    ) -> None:
        self._engine = engine
        self._consent_facade = consent_facade
        self._care_facade = care_facade

    async def create_record(self, patient_id: int) -> int:
        """Create the patient's record shell; a no-op returning the existing id.

        The seam the ``patient.registered`` subscriber drives: zero-setup
        ownership means every identity ends up with exactly one shell, and a
        redelivered event resolves to the same row instead of failing.
        """
        async with self._engine.begin() as connection:
            return await _ensure_record_shell(connection, patient_id)

    async def get_own_record(self, patient_id: int) -> RecordTimeline:
        """Owner read resolved by identity; records an allowed access.

        The shell is lazily ensured here as a safety net (a patient registered
        before the subscriber ran, or while its delivery is still in flight),
        so an owner never sees anything but their - possibly empty - timeline.
        The access lands in the ledger in the same transaction as the read.
        """
        async with self._engine.begin() as connection:
            record_id = await _ensure_record_shell(connection, patient_id)
            await _log_access(
                connection,
                record_id,
                patient_id,
                "allowed",
                actor_type=_ACTOR_TYPE_PATIENT,
                scope=_OWNER_SCOPE,
            )
            return await _load_timeline(connection, record_id, patient_id)

    async def get_record_as_owner(self, patient_id: int, record_id: int) -> RecordTimeline:
        """Addressed owner-only read: deny and RECORD any non-owner attempt.

        A caller whose identity does not own the addressed record gets the
        403 envelope (mapped from ``RecordAccessDeniedError`` by the routes)
        AND a ``denied`` row naming them in the access history. The denial
        row is COMMITTED first - raising inside the transaction would roll it
        back - so a refused read is always auditable before the error leaves
        the facade. An unknown record id answers 404 with nothing to record.
        """
        denial_recorded = False
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    select(health_patient_records.c.identity_id).where(
                        health_patient_records.c.id == record_id
                    )
                )
            ).first()
            if row is None:
                # No record to key a history row against: 404, nothing logged.
                pass
            elif row.identity_id != patient_id:
                await _log_access(
                    connection,
                    record_id,
                    patient_id,
                    "denied",
                    actor_type=_ACTOR_TYPE_PATIENT,
                    scope=_OWNER_SCOPE,
                    denial_reason="only the record owner may read this record",
                )
                denial_recorded = True
            else:
                await _log_access(
                    connection,
                    record_id,
                    patient_id,
                    "allowed",
                    actor_type=_ACTOR_TYPE_PATIENT,
                    scope=_OWNER_SCOPE,
                )
                return await _load_timeline(connection, record_id, patient_id)
        if denial_recorded:
            raise RecordAccessDeniedError("only the record owner may read this record")
        raise RecordNotFoundError(f"no record exists with id {record_id}")

    async def get_access_history(self, patient_id: int) -> AccessHistoryView:
        """Return the patient's record access history, newest first (FEAT-003).

        A pure read of ``health_record_access_history`` for every row keyed to
        the patient's record - owner reads, partner reads, and denied attempts
        alike. A record no one has touched yet answers an empty list, not an
        error. The ledger is a trust read, not a record access itself, so it
        is not logged back into the ledger.
        """
        async with self._engine.begin() as connection:
            return await query_access_history(connection, patient_id)

    async def log_doctor_patient_view(
        self,
        *,
        patient_id: int,
        doctor_id: int,
        scope: str = _DOCTOR_PATIENTS_LIST_SCOPE,
    ) -> None:
        """Ledger a doctor seeing one patient in the console Patients list (ADR-0019).

        MOD-012 owns no ledger or outbox, so the doctor console delegates its
        "every read attempt" bookkeeping here: the record shell is resolved
        (lazily ensured) and an allowed doctor access lands in BOTH the
        access-history ledger and the outbox ``record.accessed`` envelope in
        the same transaction. The scope marker names the console surface, not
        a record entry - revoking the underlying consent does not rewind the
        historical "viewed where" signal. The detail read (#540) passes its
        own surface marker to ``scope`` for the contact/photo block, which is
        gated on any live grant rather than one record scope.
        """
        async with self._engine.begin() as connection:
            record_id = await _ensure_record_shell(connection, patient_id)
            await _log_access(
                connection,
                record_id,
                doctor_id,
                "allowed",
                actor_type=_ACTOR_TYPE_DOCTOR,
                scope=scope,
            )

    async def log_doctor_patient_view_denied(
        self,
        *,
        patient_id: int,
        doctor_id: int,
        denial_reason: str,
        scope: str = _DOCTOR_PATIENTS_LIST_SCOPE,
    ) -> None:
        """Ledger a REFUSED doctor view of one patient (KPI-006, security-phii-standards §3).

        The denial twin of ``log_doctor_patient_view``, same shape as the
        module's other self-ledging refusals (``get_record_as_owner``,
        ``_consent_gated_read``): a denied attempt is a Security-class event
        (error-handling-observability §1), so it lands in BOTH the
        access-history ledger (``outcome=denied`` plus the reason, so the
        patient's trust view answers who/why) and the outbox ``record.denied``
        envelope, in one committed transaction.

        Callers MUST await this BEFORE raising their own refusal, so the row is
        durable before the error leaves the facade - raising inside the
        transaction would roll it back. A consent denial discloses no PHI, but
        the attempt is still a regulated act: the KPI-006 promise is 100% of
        read attempts, not 100% of served reads.
        """
        async with self._engine.begin() as connection:
            record_id = await _ensure_record_shell(connection, patient_id)
            await _log_access(
                connection,
                record_id,
                doctor_id,
                "denied",
                actor_type=_ACTOR_TYPE_DOCTOR,
                scope=scope,
                denial_reason=denial_reason,
            )

    async def _discover_live_relationship_counterparty_ids(self, patient_id: int) -> set[str]:
        """Return the counterparty ids of every live relationship the patient has.

        A counterparty is live-relationship when EITHER it holds a live standing
        consent grant of any scope from this patient (MOD-004, any ``granted``
        ``doctor`` lineage) OR it is the assigned doctor on one of the patient's
        open care cases (MOD-006, ``stage != closed``). Both reads go through
        their module facades - never across schemas (ADR-0003) - and the union is
        deduplicated. This is the set the first acknowledged health-background
        save auto-grants to (ADR-0018).

        Ids are OPAQUE TEXT, never integers: the consent lineage stores
        ``counterparty_id`` as a Text column with no format constraint, so a
        granted ``doctor`` namespace carries ids an integer coercion does not
        survive (``intake-ai``, the AI egress pseudo-counterparty, is a live
        one - its own grant is what satisfies the intake consent gate). Consent
        rows contribute their id verbatim; the care seam reports integer doctor
        ids, which are stringified into the same namespace. Callers pass each
        discovered id through UNCHANGED - re-deriving one raises here, and even
        where it does not (``007`` -> ``7``) it would write the grant onto a
        re-derived lineage triple no doctor read ever matches.
        """
        if self._consent_facade is None:
            raise RuntimeError("ConsentFacade not configured on HealthFacade")
        if self._care_facade is None:
            raise RuntimeError("CareFacade not configured on HealthFacade")
        consent_log = await self._consent_facade.list_consents(patient_id)
        granted_counterparty_ids = {
            item.counterparty_id
            for item in consent_log.items
            if item.counterparty_type == _COUNTERPARTY_TYPE_DOCTOR and item.status == "granted"
        }
        open_case_doctor_ids = await self._care_facade.list_open_case_doctor_ids(
            patient_id=patient_id
        )
        return granted_counterparty_ids | {str(doctor_id) for doctor_id in open_case_doctor_ids}

    async def get_health_background(self, patient_id: int) -> HealthBackgroundView:
        """Owner read of the patient's health-background snapshot, or "not set".

        Resolves the snapshot by the patient identity (never client input);
        a patient who has not saved one yet answers the typed "not recorded"
        view (zero-setup, mirroring the profile read goal of #482). This
        surface only serves the owning patient - a doctor read is gated by a
        later consent check on a doctor-facing surface (#540), never here.
        """
        async with self._engine.begin() as connection:
            return await _load_health_background(connection, patient_id)

    async def save_health_background(
        self,
        patient_id: int,
        background: HealthBackground,
        *,
        acknowledge_phi: bool,
    ) -> HealthBackgroundView:
        """Persist the patient's health-background snapshot (#534, US-21/US-22).

        The snapshot is patient-owned health-schema data keyed to the patient
        identity - never a care-generated record entry. The FIRST save must
        carry the explicit ``acknowledge_phi`` acknowledgment that the snapshot
        becomes visible to the patient's verified-relationship doctors; a first
        save without it is refused before anything is persisted. On that
        acknowledged first save a standing ``health_background`` consent grant
        is recorded to every live-relationship doctor (a live grant of any
        scope, or an open care case), atomically with the snapshot write in ONE
        transaction and durably committed. Later edits idempotently converge on
        the single row (INSERT ... ON CONFLICT DO UPDATE, mirroring the profile
        upsert of #482) and never re-prompt or re-grant. The returned
        ``acknowledged`` echoes the stamp the row now carries, so the answer
        never claims a confirmation that was not persisted.
        """
        if self._consent_facade is None:
            raise RuntimeError("ConsentFacade not configured on HealthFacade")
        if self._care_facade is None:
            raise RuntimeError("CareFacade not configured on HealthFacade")

        granted_counterparty_ids: set[str] = set()
        is_first_save = False
        # The acknowledgement as it will stand after this write: the stored
        # stamp on a later edit (never overwritten), the fresh stamp on the
        # first acknowledged save. The answer echoes it rather than asserting a
        # constant, so a client never reads a confirmation the row lacks.
        acknowledged_at: datetime | None = None
        async with self._engine.begin() as connection:
            existing = (
                await connection.execute(
                    select(health_background_snapshots.c.acknowledged_at).where(
                        health_background_snapshots.c.identity_id == patient_id
                    )
                )
            ).first()
            is_first_save = existing is None
            if is_first_save and not acknowledge_phi:
                raise HealthBackgroundAcknowledgmentRequiredError(
                    "the first health-background save must acknowledge that the "
                    "snapshot becomes visible to your doctors"
                )
            if existing is None:
                granted_counterparty_ids = await self._discover_live_relationship_counterparty_ids(
                    patient_id
                )
            else:
                acknowledged_at = existing.acknowledged_at

            values: dict[str, object] = {
                "identity_id": patient_id,
                "blood_group": background.blood_group,
                "conditions": background.conditions,
                "allergies": background.allergies,
                "medications": background.medications,
                "immunizations": background.immunizations,
                "family_history": background.family_history,
            }
            if is_first_save:
                acknowledged_at = datetime.now(UTC)
                values["acknowledged_at"] = acknowledged_at
            upsert = (
                postgresql_insert(health_background_snapshots)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["identity_id"],
                    set_={
                        "blood_group": background.blood_group,
                        "conditions": background.conditions,
                        "allergies": background.allergies,
                        "medications": background.medications,
                        "immunizations": background.immunizations,
                        "family_history": background.family_history,
                        # ``acknowledged_at`` is never overwritten: it records
                        # the one-time first-save confirmation.
                        "updated_at": func.now(),
                    },
                )
            )
            await connection.execute(upsert)
            for counterparty_id in sorted(granted_counterparty_ids):
                await self._consent_facade.grant_consent_on(
                    connection,
                    patient_id,
                    _COUNTERPARTY_TYPE_DOCTOR,
                    counterparty_id,
                    _HEALTH_BACKGROUND_SCOPE,
                )

        # Cache invalidation lands only after the commit is visible (same
        # discipline as the intake pick-doctor write, #443).
        for counterparty_id in sorted(granted_counterparty_ids):
            await self._consent_facade.invalidate_consent_cache(
                patient_id,
                _COUNTERPARTY_TYPE_DOCTOR,
                counterparty_id,
                _HEALTH_BACKGROUND_SCOPE,
            )
        return HealthBackgroundView(
            set=True,
            acknowledged=acknowledged_at is not None,
            background=background,
        )

    async def append_health_background_metric(
        self,
        patient_id: int,
        metric: HealthBackgroundMetric,
    ) -> HealthBackgroundMetricEntry:
        """Append one timestamped height/weight row to the patient's series.

        Owner-only authoring resolved from the session subject (never client
        input): the row is keyed to ``patient_id`` and its id is minted by the
        table - the request model carries no id field, so a client never picks
        a series identity. Append-only in v1: no UPDATE/DELETE on this surface
        (the trend view extends naturally over this time series instead). The
        writer returns the stored entry with its server id in one round trip.
        """
        async with self._engine.begin() as connection:
            result = await connection.execute(
                health_background_metrics.insert()
                .values(
                    identity_id=patient_id,
                    height_cm=metric.height_cm,
                    weight_kg=metric.weight_kg,
                    recorded_at=metric.recorded_at,
                )
                .returning(
                    health_background_metrics.c.id,
                    health_background_metrics.c.height_cm,
                    health_background_metrics.c.weight_kg,
                    health_background_metrics.c.recorded_at,
                )
            )
            row = result.one()
            return _metric_entry_from_row(row)

    async def list_health_background_metrics(
        self,
        patient_id: int,
        *,
        page: int = 1,
        per_page: int = DEFAULT_HEALTH_BACKGROUND_PER_PAGE,
    ) -> HealthBackgroundMetricList:
        """Read one page of the patient's height/weight series, newest-first.

        Scoped to the session patient's identity (the caller's rows only,
        resolved from the token subject - this surface is owner-only). Ordered
        by ``(recorded_at, id)`` descending so ties resolve deterministically;
        ``total`` counts the full series while ``items`` returns at most
        ``per_page`` rows (api-standards §4). A patient with no measurements
        answers an empty page, never an error.
        """
        async with self._engine.begin() as connection:
            scoped = health_background_metrics.c.identity_id == patient_id
            total = (
                await connection.scalar(
                    select(func.count()).select_from(health_background_metrics).where(scoped)
                )
                or 0
            )
            rows = (
                await connection.execute(
                    select(
                        health_background_metrics.c.id,
                        health_background_metrics.c.height_cm,
                        health_background_metrics.c.weight_kg,
                        health_background_metrics.c.recorded_at,
                    )
                    .where(scoped)
                    .order_by(
                        health_background_metrics.c.recorded_at.desc(),
                        health_background_metrics.c.id.desc(),
                    )
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                )
            ).all()
            return HealthBackgroundMetricList(
                items=[_metric_entry_from_row(row) for row in rows],
                total=int(total),
            )

    async def seed_record_entries(self, patient_id: int) -> tuple[list[int], list[str]]:
        """Return entry IDs and types for a patient's record (test-only seed helper).

        Ensures the record shell exists, then reads back all entries. Used by
        the ``/v1/test/seed`` endpoint so it does not import raw schema models.
        """
        async with self._engine.begin() as connection:
            record_id = await _ensure_record_shell(connection, patient_id)
            rows = (
                await connection.execute(
                    select(
                        health_record_entries.c.id,
                        health_record_entries.c.entry_type,
                    ).where(health_record_entries.c.record_id == record_id)
                )
            ).all()
            entry_ids = [int(r.id) for r in rows]
            entry_types = [r.entry_type for r in rows]
            return entry_ids, entry_types

    async def _consent_gated_read(
        self,
        *,
        patient_id: int,
        counterparty_type: str,
        counterparty_id: int,
        scope: str,
        settings: Settings | None,
        loader: Callable[[AsyncConnection, int], Awaitable[_T]],
        disclosed_entry_ids: Callable[[_T], list[int]],
    ) -> _T:
        """Shared two-ledger spine for consent-gated partner record reads.

        The consent gate is checked via MOD-004's ``check_consent`` for the
        given record ``scope``. If allowed, the payload is loaded and exactly
        ONE row is written to EACH ledger: ``health_record_access_history``
        (outcome=allowed) and ``consent_egress_log`` (citing consent_id,
        version, and the entry IDs the loader surfaced). If denied, only the
        access-history ledger receives a row (outcome=denied) and
        ``RecordAccessDeniedError`` is raised after the transaction commits -
        the caller renders the section locked, never an error (ADR-0019).
        The EGRESS write is delegated to ``ConsentFacade`` in its own
        transaction (FIX-7, #227): the health transaction commits above, then
        the consent facade opens a separate one for the audit row.  Two-phase
        commit is rejected as disproportionate for an append-only ledger whose
        absence is detectable (coding-standards S2).
        """
        if self._consent_facade is None:
            raise RuntimeError("ConsentFacade not configured on HealthFacade")

        decision = await self._consent_facade.check_consent(
            patient_id=patient_id,
            counterparty_type=counterparty_type,  # type: ignore[arg-type]
            counterparty_id=str(counterparty_id),
            record_scope=scope,
            settings=settings,
        )

        # Ensure record shell exists so access-history rows attach to the
        # patient's record.
        denied = not decision.allowed
        async with self._engine.begin() as connection:
            record_id = await _ensure_record_shell(connection, patient_id)

            if denied:
                await _log_access(
                    connection,
                    record_id,
                    counterparty_id,
                    "denied",
                    actor_type=counterparty_type,
                    scope=scope,
                    denial_reason="consent check failed",
                )
            else:
                await _log_access(
                    connection,
                    record_id,
                    counterparty_id,
                    "allowed",
                    actor_type=counterparty_type,
                    scope=scope,
                )
                result = await loader(connection, record_id)

        if denied:
            raise RecordAccessDeniedError("consent check failed")

        consent_version = decision.version if decision.version is not None else 0
        await self._consent_facade.record_egress_disclosure(
            patient_id=patient_id,
            consent_id=decision.consent_id,
            version=consent_version,
            counterparty_type=counterparty_type,
            counterparty_id=str(counterparty_id),
            record_scope=scope,
            disclosed_entry_ids=disclosed_entry_ids(result),
        )

        return result

    async def read_consented_history(
        self,
        *,
        patient_id: int,
        scope: str,
        counterparty_type: str,
        counterparty_id: int,
        settings: Settings | None = None,
    ) -> RecordTimeline:
        """Partner read gated by consent; writes to both ledgers on success.

        Delegates to the shared two-ledger spine (``_consent_gated_read``):
        allowed reads surface the scoped entries and egress-cite their IDs;
        denied reads fail closed. Owner reads bypass this gate entirely - use
        ``get_own_record``. Keyword-only (coding-standards §3): a
        consent-gated read takes five same-typed-ish arguments, so a positional
        call is a silent scope/counterparty mix-up waiting to happen.
        """
        return await self._consent_gated_read(
            patient_id=patient_id,
            counterparty_type=counterparty_type,
            counterparty_id=counterparty_id,
            scope=scope,
            settings=settings,
            loader=lambda connection, record_id: _load_timeline(connection, record_id, patient_id),
            disclosed_entry_ids=lambda timeline: [entry.entry_id for entry in timeline.entries],
        )

    async def read_consented_health_background(
        self,
        patient_id: int,
        counterparty_type: str,
        counterparty_id: int,
        settings: Settings | None = None,
    ) -> HealthBackgroundView:
        """Partner read of the health-background snapshot gated by consent (#540).

        Uses the same fail-closed, two-ledger spine as ``read_consented_history``
        with the ``health_background`` scope (which ``full_record`` subsumes).
        The snapshot is not entry-keyed, so ``disclosed_entry_ids`` stays
        empty. Owner reads bypass this gate entirely - use
        ``get_health_background``.
        """
        return await self._consent_gated_read(
            patient_id=patient_id,
            counterparty_type=counterparty_type,
            counterparty_id=counterparty_id,
            scope=_HEALTH_BACKGROUND_SCOPE,
            settings=settings,
            loader=lambda connection, _record_id: _load_health_background(connection, patient_id),
            disclosed_entry_ids=lambda _background: [],
        )
