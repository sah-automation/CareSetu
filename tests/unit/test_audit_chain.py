"""PHASE-4 T2: audit hash chain logic (ticket #236, FEAT-020/NFR-D01).

Pins the deterministic SHA-256 chain contract without a database: the
genesis constant, field-level determinism (including sorted metadata
keys), a valid multi-event chain, and tamper detection on every field.
Prior art: the pure-logic parametrized suites (test_consent_state_machine).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from modules.audit.domain.chain import (
    GENESIS_HASH,
    AuditEventRow,
    compute_audit_hash,
    verify_chain,
)

_ACTOR = "11111111-1111-1111-1111-111111111111"
_TARGET = "22222222-2222-2222-2222-222222222222"
_BASE = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


def _compute(
    *,
    event_type: str = "record.accessed",
    actor_id: str | None = _ACTOR,
    target_id: str | None = _TARGET,
    scope: str | None = "record",
    metadata: dict[str, object] | None = None,
    timestamp: datetime = _BASE,
    prev_hash: str = GENESIS_HASH,
) -> str:
    return compute_audit_hash(
        event_type, actor_id, target_id, scope, metadata, timestamp, prev_hash
    )


def _chained_rows(count: int) -> list[AuditEventRow]:
    """Build ``count`` valid rows chained from the genesis hash."""
    rows: list[AuditEventRow] = []
    prev_hash = GENESIS_HASH
    for index in range(count):
        digest = compute_audit_hash(
            "record.accessed",
            _ACTOR,
            _TARGET,
            "record",
            {"reason": "consultation", "seq": index},
            _BASE + timedelta(seconds=index),
            prev_hash,
        )
        rows.append(
            AuditEventRow(
                event_type="record.accessed",
                actor_id=_ACTOR,
                target_id=_TARGET,
                scope="record",
                metadata={"reason": "consultation", "seq": index},
                timestamp=_BASE + timedelta(seconds=index),
                prev_hash=prev_hash,
                hash=digest,
            )
        )
        prev_hash = digest
    return rows


def test_genesis_hash_is_pinned_digest() -> None:
    assert hashlib.sha256(b"CareSetu-audit-genesis").hexdigest() == GENESIS_HASH


def test_compute_audit_hash_is_deterministic_for_identical_inputs() -> None:
    first = _compute()
    second = _compute()

    assert first == second
    assert len(first) == 64
    assert int(first, 16) >= 0


def test_compute_audit_hash_is_deterministic_across_metadata_key_order() -> None:
    left = _compute(metadata={"reason": "consultation", "seq": 3, "nested": {"b": 1, "a": 2}})
    right = _compute(metadata={"nested": {"a": 2, "b": 1}, "seq": 3, "reason": "consultation"})

    assert left == right


def test_compute_audit_hash_normalizes_actor_uuid_case() -> None:
    upper = _compute(actor_id=_ACTOR.upper())

    assert upper == _compute(actor_id=_ACTOR)


def test_compute_audit_hash_distinguishes_null_metadata_from_empty_dict() -> None:
    assert _compute(metadata=None) != _compute(metadata={})


def test_compute_audit_hash_distinguishes_none_scope_from_empty_string() -> None:
    assert _compute(scope=None) != _compute(scope="")


def test_compute_audit_hash_links_to_previous_hash() -> None:
    first = _compute()
    second = _compute(prev_hash=first, timestamp=_BASE + timedelta(seconds=1))

    assert second != first


def test_verify_chain_accepts_empty_chain() -> None:
    assert verify_chain([])


def test_verify_chain_accepts_single_row_chained_to_genesis() -> None:
    assert verify_chain(_chained_rows(1))


def test_verify_chain_accepts_a_valid_three_event_chain() -> None:
    assert verify_chain(_chained_rows(3))


def test_verify_chain_accepts_out_of_timestamp_order_rows() -> None:
    rows = _chained_rows(3)

    assert verify_chain([rows[2], rows[0], rows[1]])


def test_verify_chain_rejects_first_row_not_chained_to_genesis() -> None:
    row = _chained_rows(1)[0]

    assert not verify_chain([replace(row, prev_hash="0" * 64)])


@pytest.mark.parametrize(
    "tamper",
    [
        ("event_type", lambda r: replace(r, event_type="prescription.approved")),
        (
            "actor_id",
            lambda r: replace(r, actor_id="99999999-9999-9999-9999-999999999999"),
        ),
        ("target_id", lambda r: replace(r, target_id=None)),
        ("scope", lambda r: replace(r, scope="full_record")),
        ("metadata", lambda r: replace(r, metadata={"reason": "forged"})),
        ("timestamp", lambda r: replace(r, timestamp=_BASE + timedelta(hours=1))),
        ("prev_hash", lambda r: replace(r, prev_hash="0" * 64)),
    ],
)
def test_verify_chain_rejects_tampered_field_at_that_row(
    tamper: tuple[str, Callable[[AuditEventRow], AuditEventRow]],
) -> None:
    _, mutate = tamper
    rows = _chained_rows(3)

    tampered = [row if i != 1 else mutate(row) for i, row in enumerate(rows)]

    assert not verify_chain(tampered)


def test_partner_terminal_decisions_and_credential_views_coexist_in_one_chain() -> None:
    """PHASE-5 T13 (#256): the terminal-decision and credential-view appends
    share the same hash chain - both event families chain through one ledger."""
    decision = compute_audit_hash(
        "partner.activated",
        _ACTOR,
        _TARGET,
        "partner_decision",
        {"producer": "partner", "identity_id": 11},
        _BASE,
        GENESIS_HASH,
    )
    view = compute_audit_hash(
        "partner.credential_reviewed",
        _ACTOR,
        _TARGET,
        "partner_credentials",
        {"producer": "partner"},
        _BASE + timedelta(seconds=1),
        decision,
    )
    rejected = compute_audit_hash(
        "partner.rejected",
        _ACTOR,
        _TARGET,
        "partner_decision",
        {"producer": "partner", "identity_id": 11, "reason": "identity mismatch", "round": 1},
        _BASE + timedelta(seconds=2),
        view,
    )

    rows = [
        AuditEventRow(
            event_type="partner.activated",
            actor_id=_ACTOR,
            target_id=_TARGET,
            scope="partner_decision",
            metadata={"producer": "partner", "identity_id": 11},
            timestamp=_BASE,
            prev_hash=GENESIS_HASH,
            hash=decision,
        ),
        AuditEventRow(
            event_type="partner.credential_reviewed",
            actor_id=_ACTOR,
            target_id=_TARGET,
            scope="partner_credentials",
            metadata={"producer": "partner"},
            timestamp=_BASE + timedelta(seconds=1),
            prev_hash=decision,
            hash=view,
        ),
        AuditEventRow(
            event_type="partner.rejected",
            actor_id=_ACTOR,
            target_id=_TARGET,
            scope="partner_decision",
            metadata={
                "producer": "partner",
                "identity_id": 11,
                "reason": "identity mismatch",
                "round": 1,
            },
            timestamp=_BASE + timedelta(seconds=2),
            prev_hash=view,
            hash=rejected,
        ),
    ]

    assert verify_chain(rows)
