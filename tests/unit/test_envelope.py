"""PHASE-1 T2a: Envelope validation contract (ticket #19).

Pins the field rules from issue #16 without a database: UUID ``event_id``,
``domain.action`` ``event_type``, typed (non-dict) ``payload``,
timezone-aware ``occurred_at``, and a named ``producer``.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from bus.envelope import Envelope


class SamplePayload(BaseModel):
    sample_field: int


class OtherPayload(BaseModel):
    sample_field: int


def _envelope(**overrides: object) -> Envelope[SamplePayload]:
    values: dict[str, object] = {
        "event_id": uuid4(),
        "event_type": "phase1.round_trip",
        "schema_version": 1,
        "occurred_at": datetime.now(UTC),
        "producer": "phase1",
        "payload": SamplePayload(sample_field=1),
    }
    values.update(overrides)
    return Envelope[SamplePayload](**values)  # type: ignore[arg-type]


def test_valid_envelope_round_trips_fields() -> None:
    event_id = uuid4()
    occurred_at = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

    envelope = _envelope(event_id=event_id, occurred_at=occurred_at)

    assert envelope.event_id == event_id
    assert envelope.event_type == "phase1.round_trip"
    assert envelope.schema_version == 1
    assert envelope.occurred_at == occurred_at
    assert envelope.producer == "phase1"
    assert isinstance(envelope.payload, SamplePayload)


def test_event_id_must_be_uuid() -> None:
    with pytest.raises(ValidationError):
        _envelope(event_id="not-a-uuid")
    with pytest.raises(ValidationError):
        _envelope(event_id=123)


def test_event_type_must_be_domain_action() -> None:
    for invalid in (
        "no_dot",
        "Domain.action",
        "domain.Action",
        "domain.",
        ".action",
        "9dom.action",
    ):
        with pytest.raises(ValidationError):
            _envelope(event_type=invalid)


def test_event_type_accepts_registry_shapes() -> None:
    for valid in ("patient.registered", "pre_summary.low_confidence", "phase1.round_trip"):
        assert _envelope(event_type=valid).event_type == valid


def test_schema_version_must_be_positive() -> None:
    for invalid in (0, -1):
        with pytest.raises(ValidationError):
            _envelope(schema_version=invalid)


def test_occurred_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        _envelope(occurred_at=datetime(2026, 8, 10, 12, 0))


def test_producer_must_be_non_empty() -> None:
    for invalid in ("", "   "):
        with pytest.raises(ValidationError):
            _envelope(producer=invalid)


def test_payload_must_be_typed_model_not_raw_dict() -> None:
    with pytest.raises(ValidationError):
        _envelope(payload={"sample_field": 1})
    with pytest.raises(ValidationError):
        _envelope(payload="not a model")


def test_payload_must_be_the_declared_payload_model() -> None:
    with pytest.raises(ValidationError):
        _envelope(payload=OtherPayload(sample_field=1))
