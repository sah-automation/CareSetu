"""MOD-011: pure logic for the ``audit.event`` consumer (PHASE-4 T4, #239).

The consumer handler's decision - which regulated act a payload names and
whether it enters the hash chain - and the row's hash computation are pure
logic with no SQL or I/O (coding-standards §2), so they are unit-testable
without a database. The adapter owns the DB I/O (prev_hash read + insert);
the facade exposes the event-appending helper it calls. Prior art: the
pure-logic core of ``chain.py`` (T2) that this builds on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import NAMESPACE_DNS, uuid5

from pydantic import BaseModel, Field

from bus.events import is_regulated_act
from modules.audit.domain.chain import compute_audit_hash

#: Canonical ``audit.event`` payload actions from the consent producer
#: (``ConsentAuditAction``). Declared locally so MOD-011 consumes without
#: importing another module's domain (ADR-0003).
ConsentAuditAction = Literal["requested", "granted", "revoked", "declined"]

#: The ``record_scope`` vocabulary carried by consent audit payloads.
RecordScope = Literal["consultations", "prescriptions", "lab_results", "metrics", "full_record"]

#: Stable namespace for the deterministic int->UUID derivation. Fixed so the
#: same consent int id always maps to the same ``audit_events`` actor/target
#: UUID, DB-free and reproducible across runs.
_AUDIT_NAMESPACE = uuid5(NAMESPACE_DNS, "caresetu.audit")


class AuditEventPayload(BaseModel):
    """MOD-011's typed mirror of the generic ``audit.event`` payload.

    The dispatcher reconstructs a claimed ``audit.event`` outbox row into this
    model - the registry's registered payload model for ``audit.event`` - so
    its field contract is a byte-for-byte mirror of what producers publish;
    today that is MOD-004's ``ConsentAuditPayload``. The mirror lives here so
    MOD-011 consumes ``audit.event`` without importing another module's domain
    (ADR-0003, module isolation rule).
    """

    action: ConsentAuditAction
    actor_patient_id: int
    consent_id: int
    lineage_ref: str
    record_scope: RecordScope
    version: int


def audit_act_type(action: ConsentAuditAction) -> str:
    """Derive the regulated-act event type for one ``audit.event`` payload action.

    Today every producer is MOD-004 (consent), so the act type is its registry
    ``consent.<action>`` name. ``declined`` deliberately resolves to
    ``consent.declined``, which ``is_regulated_act`` rejects (a decline is a
    null grant with no ``consent.*`` bus event), so the consumer skips it
    exactly like any other operational act.
    """
    return f"consent.{action}"


def is_appended_act(payload: AuditEventPayload) -> bool:
    """Return True when the payload's regulated act enters the audit chain.

    Exact check via T3's predicate on the derived act type: only an explicitly
    whitelisted act is appended; operational and unknown acts are silently
    skipped. ``audit.event`` itself is never whitelisted, which is why the
    check runs on the derived act type, not the carrier event type.
    """
    return is_regulated_act(audit_act_type(payload.action))


def _actor_uuid(patient_id: int) -> str:
    """Deterministic, reproducible UUID for one patient identity (int -> UUID).

    The consent producer carries integer ids while ``audit_events.actor_id`` is
    a UUID column, so the int is mapped through a stable namespace. ``uuid5``
    is deterministic (same id -> same UUID), DB-free, and keeps the actor index
    useful for the operator ``query_audit(actor_id=...)`` filter.
    """
    return str(uuid5(_AUDIT_NAMESPACE, f"actor:{patient_id}"))


def _target_uuid(consent_id: int) -> str:
    """Deterministic, reproducible UUID for one consent lineage (int -> UUID)."""
    return str(uuid5(_AUDIT_NAMESPACE, f"consent:{consent_id}"))


def _record_uuid(record_id: int) -> str:
    """Deterministic, reproducible UUID for one health record (int -> UUID)."""
    return str(uuid5(_AUDIT_NAMESPACE, f"record:{record_id}"))


class RecordAccessAuditPayload(BaseModel):
    """MOD-011's typed mirror of MOD-003's record-access payload.

    The dispatcher reconstructs a claimed ``record.accessed`` / ``record.denied``
    outbox row into this model - the registry's registered payload model - so
    its field contract is a byte-for-byte mirror of what MOD-003 publishes
    (its ``RecordAccessedPayload``). The mirror lives here so MOD-011 consumes
    the events without importing another module's domain (ADR-0003).
    """

    record_id: int
    actor_id: int
    actor_type: str
    scope: str
    accessed_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_record_access_row(
    event_type: str,
    payload: RecordAccessAuditPayload,
    producer: str,
    prev_hash: str,
) -> AuditRow:
    """Compute the ``audit_events`` columns for one record-access audit event.

    The event type IS the regulated act (``record.accessed`` / ``record.denied``
    - T3's predicate runs on it directly, no derivation). The accessor identity
    maps to ``actor_id`` and the accessed record to ``target_id`` through the
    deterministic uuid5 namespace; ``metadata`` re-hosts the no-PHI facts
    (producer, ``actor_type``, optional ``denied`` / ``denial_reason``) the
    health outbox carried, so the operator view answers the same who/how/why as
    the patient view without reading across schemas. ``timestamp`` mirrors the
    payload's ``accessed_at`` so the hash chain and the ``record_access_history``
    ledger agree exactly on when the read happened.
    """
    actor_id = _actor_uuid(payload.actor_id)
    target_id = _record_uuid(payload.record_id)
    metadata: dict[str, Any] = {
        "producer": producer,
        "actor_type": payload.actor_type,
        **payload.metadata,
    }
    digest = compute_audit_hash(
        event_type,
        actor_id,
        target_id,
        payload.scope,
        metadata,
        payload.accessed_at,
        prev_hash,
    )
    return AuditRow(
        event_type=event_type,
        actor_id=actor_id,
        target_id=target_id,
        scope=payload.scope,
        metadata=metadata,
        timestamp=payload.accessed_at,
        prev_hash=prev_hash,
        hash=digest,
    )


class TamperDetectedPayload(BaseModel):
    """MOD-011's payload model for the ``audit.tamper_detected`` outbox event.

    The tamper guard trigger writes this into ``audit.audit_outbox`` when an
    UPDATE/DELETE on ``audit.audit_events`` is attempted and blocked (PHASE-4
    #234 user story 11). Telemetry only - deliberately never appended to the
    hash chain; real-time alert delivery is deferred, so MOD-011's consumer
    logs the attempt and does not touch ``audit_events``.
    """

    attempted_operation: str
    target_event_id: str | None
    details: dict[str, Any] = Field(default_factory=dict)
    attempted_at: datetime


@dataclass(frozen=True)
class AuditRow:
    """The pure decision + column values the consumer appends (DB-free)."""

    event_type: str
    actor_id: str
    target_id: str
    scope: str
    metadata: dict[str, Any]
    timestamp: datetime
    prev_hash: str
    hash: str


def build_audit_row(
    payload: AuditEventPayload,
    producer: str,
    occurred_at: datetime,
    prev_hash: str,
) -> AuditRow:
    """Compute the ``audit_events`` columns for one regulated ``audit.event``.

    Call only after ``is_appended_act`` returned True (operational acts are
    skipped upstream). Every column value is computed purely: the derived act
    type, the deterministic actor/target UUIDs, the record scope, a
    no-PHI ``metadata`` map (producer + consent lineage facts), the UTC
    timestamp, and the digest that T2's ``compute_audit_hash`` produces chained
    from ``prev_hash`` - the most recent row's hash, or ``GENESIS_HASH`` for
    the first row.
    """
    event_type = audit_act_type(payload.action)
    actor_id = _actor_uuid(payload.actor_patient_id)
    target_id = _target_uuid(payload.consent_id)
    scope = payload.record_scope
    metadata: dict[str, Any] = {
        "producer": producer,
        "consent_id": payload.consent_id,
        "lineage_ref": payload.lineage_ref,
        "version": payload.version,
    }
    digest = compute_audit_hash(
        event_type,
        actor_id,
        target_id,
        scope,
        metadata,
        occurred_at,
        prev_hash,
    )
    return AuditRow(
        event_type=event_type,
        actor_id=actor_id,
        target_id=target_id,
        scope=scope,
        metadata=metadata,
        timestamp=occurred_at,
        prev_hash=prev_hash,
        hash=digest,
    )
