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

from bus.events import (
    EVENT_CREDENTIAL_INVALIDATED,
    EVENT_PARTNER_CREDENTIAL_REVIEWED,
    EVENT_PARTNER_REGISTERED,
    is_regulated_act,
)
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


def _partner_uuid(partner_id: int) -> str:
    """Deterministic, reproducible UUID for one partner (int -> UUID)."""
    return str(uuid5(_AUDIT_NAMESPACE, f"partner:{partner_id}"))


class PartnerDecisionPayload(BaseModel):
    """MOD-011's typed mirrors of the partner terminal-decision payloads.

    The dispatcher reconstructs a claimed ``partner.activated`` /
    ``partner.rejected`` outbox row into this model - the registry's registered
    payload model - so its field contract mirrors what MOD-002 publishes (its
    ``PartnerActivatedPayload`` / ``PartnerRejectedPayload``). The mirror lives
    here so MOD-011 consumes the events without importing another module's
    domain (ADR-0003). ``identity_id`` names the iam identity whose ``partner``
    role is granted/suspended - an isolation-safe identifier.
    """

    partner_id: int
    identity_id: int
    reason: str | None = None
    round: int | None = None
    decision_by: int | None = None


class CredentialReviewedPayload(BaseModel):
    """MOD-011's typed mirror of MOD-002's ``partner.credential_reviewed``.

    The dispatcher reconstructs a claimed ``partner.credential_reviewed``
    outbox row into this model - the registry's registered payload model. Its
    field contract mirrors what MOD-002 publishes (its
    ``CredentialReviewedPayload``): the operator who viewed the credentials
    (``actor_id``) and the partner whose documents were seen (``partner_id``).
    One row per credential view - every view is traceable, not just a summary.
    """

    partner_id: int
    actor_id: int


class PartnerRegisteredPayload(BaseModel):
    """MOD-011's typed mirror of MOD-002's ``partner.registered`` payload.

    The dispatcher reconstructs a claimed ``partner.registered`` outbox row
    into this model - the registry's registered payload model. Its field
    contract mirrors what MOD-002 publishes (its ``PartnerRegisteredPayload``):
    the partner, its iam identity, and the credential type submitted.
    ``partner_type`` is the only MOD-002-specific vocabulary the mirror needs;
    it is isolated here so MOD-011 consumes the event without importing
    another module's domain (ADR-0003).
    """

    partner_id: int
    identity_id: int
    partner_type: str


class CredentialInvalidatedPayload(BaseModel):
    """MOD-011's typed mirror of MOD-002's ``credential.invalidated`` payload.

    The dispatcher reconstructs a claimed ``credential.invalidated`` outbox row
    and MOD-001's registered model owns the registry slot, so this mirror is
    used ONLY by ``run_handler`` to re-validate the dispatched payload for the
    chain append - MOD-011 registers no duplicate model with the registry. Its
    field contract mirrors what MOD-002 publishes (its
    ``CredentialInvalidatedPayload``): the partner, its iam identity, the
    optional credential that lost validity, and why.
    """

    partner_id: int
    identity_id: int
    credential_id: int | None = None
    reason: str


def build_partner_registered_row(
    payload: PartnerRegisteredPayload,
    producer: str,
    occurred_at: datetime,
    prev_hash: str,
) -> AuditRow:
    """Compute the ``audit_events`` columns for one ``partner.registered`` act.

    The event type IS the regulated act (``partner.registered`` - T3's
    predicate runs on it directly, no derivation). Registration is a system
    action (the aspiring partner opens the profile, no operator is involved),
    so ``actor_id`` is None and the partner maps to ``target_id`` through the
    deterministic uuid5 namespace. ``metadata`` re-hosts the no-PHI facts
    (producer, ``identity_id``, ``partner_type``) the partner outbox carried,
    so the chain records who registered as which credential type.
    """
    target_id = _partner_uuid(payload.partner_id)
    metadata: dict[str, Any] = {
        "producer": producer,
        "identity_id": payload.identity_id,
        "partner_type": payload.partner_type,
    }
    digest = compute_audit_hash(
        EVENT_PARTNER_REGISTERED,
        None,
        target_id,
        "partner_registration",
        metadata,
        occurred_at,
        prev_hash,
    )
    return AuditRow(
        event_type=EVENT_PARTNER_REGISTERED,
        actor_id=None,
        target_id=target_id,
        scope="partner_registration",
        metadata=metadata,
        timestamp=occurred_at,
        prev_hash=prev_hash,
        hash=digest,
    )


def build_credential_invalidated_row(
    payload: CredentialInvalidatedPayload,
    producer: str,
    occurred_at: datetime,
    prev_hash: str,
) -> AuditRow:
    """Compute the ``audit_events`` columns for one ``credential.invalidated`` act.

    The event type IS the regulated act (``credential.invalidated`` - T3's
    predicate runs on it directly, no derivation). A credential losing validity
    is a system action (grace lapse, failed re-verification, the 30-day
    cleanup), so ``actor_id`` is None and the partner maps to ``target_id``
    through the deterministic uuid5 namespace. ``metadata`` re-hosts the
    no-PHI facts (producer, ``identity_id``, optional ``credential_id``,
    ``reason``) the partner outbox carried.
    """
    target_id = _partner_uuid(payload.partner_id)
    metadata: dict[str, Any] = {
        "producer": producer,
        "identity_id": payload.identity_id,
        "reason": payload.reason,
    }
    if payload.credential_id is not None:
        metadata["credential_id"] = payload.credential_id
    digest = compute_audit_hash(
        EVENT_CREDENTIAL_INVALIDATED,
        None,
        target_id,
        "partner_credentials",
        metadata,
        occurred_at,
        prev_hash,
    )
    return AuditRow(
        event_type=EVENT_CREDENTIAL_INVALIDATED,
        actor_id=None,
        target_id=target_id,
        scope="partner_credentials",
        metadata=metadata,
        timestamp=occurred_at,
        prev_hash=prev_hash,
        hash=digest,
    )


def build_partner_decision_row(
    event_type: str,
    payload: PartnerDecisionPayload,
    producer: str,
    occurred_at: datetime,
    prev_hash: str,
) -> AuditRow:
    """Compute the ``audit_events`` columns for one partner terminal decision.

    The event type IS the regulated act (``partner.activated`` /
    ``partner.rejected`` - T3's predicate runs on it directly, no derivation).
    The deciding operator maps to ``actor_id`` and the partner to ``target_id``
    through the deterministic uuid5 namespace; ``metadata`` re-hosts the
    no-PHI facts (producer, ``identity_id``, optional ``reason`` / ``round``)
    the partner outbox carried, so the operator view answers who decided and
    why without reading across schemas.
    """
    actor_id = _actor_uuid(payload.decision_by) if payload.decision_by is not None else None
    target_id = _partner_uuid(payload.partner_id)
    metadata: dict[str, Any] = {
        "producer": producer,
        "identity_id": payload.identity_id,
    }
    if payload.reason is not None:
        metadata["reason"] = payload.reason
    if payload.round is not None:
        metadata["round"] = payload.round
    digest = compute_audit_hash(
        event_type,
        actor_id,
        target_id,
        "partner_decision",
        metadata,
        occurred_at,
        prev_hash,
    )
    return AuditRow(
        event_type=event_type,
        actor_id=actor_id,
        target_id=target_id,
        scope="partner_decision",
        metadata=metadata,
        timestamp=occurred_at,
        prev_hash=prev_hash,
        hash=digest,
    )


def build_credential_reviewed_row(
    payload: CredentialReviewedPayload,
    producer: str,
    occurred_at: datetime,
    prev_hash: str,
) -> AuditRow:
    """Compute the ``audit_events`` columns for one credential view.

    The event type IS the regulated act (``partner.credential_reviewed`` - T3's
    predicate runs on it directly). The operator who looked maps to ``actor_id``
    and the partner whose documents were seen to ``target_id`` through the
    deterministic uuid5 namespace. ``timestamp`` mirrors the event's
    ``occurred_at`` so the "who saw this document" trail is exact.
    """
    actor_id = _actor_uuid(payload.actor_id)
    target_id = _partner_uuid(payload.partner_id)
    scope = "partner_credentials"
    metadata: dict[str, Any] = {"producer": producer}
    digest = compute_audit_hash(
        EVENT_PARTNER_CREDENTIAL_REVIEWED,
        actor_id,
        target_id,
        scope,
        metadata,
        occurred_at,
        prev_hash,
    )
    return AuditRow(
        event_type=EVENT_PARTNER_CREDENTIAL_REVIEWED,
        actor_id=actor_id,
        target_id=target_id,
        scope=scope,
        metadata=metadata,
        timestamp=occurred_at,
        prev_hash=prev_hash,
        hash=digest,
    )


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
    actor_id: str | None
    target_id: str | None
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
