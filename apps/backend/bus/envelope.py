"""Typed event envelope for the async seam (ADR-0002, PHASE-1 T2a #19).

The ``Envelope`` is the typed unit of data carried across the outbox/dispatcher
seam. No raw dicts cross module boundaries (coding-standards §3): every field
is validated at construction and ``payload`` is a Pydantic model instance,
never a plain dict.

Field contract (issue #16): ``event_id`` (UUID - the at-least-once dedupe
key), ``event_type`` (registry ``domain.action``), ``schema_version``,
``occurred_at``, ``producer``, ``payload`` (typed).
"""

import re
from datetime import UTC, datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")

PayloadT = TypeVar("PayloadT", bound=BaseModel, covariant=True)


def is_valid_event_type(value: str) -> bool:
    """Return True when ``value`` matches the registry ``domain.action`` shape.

    Single source of truth for the event-type grammar so the ``Envelope``
    validator (T2a) and the ``HandlerRegistry`` key guard (T2b) agree.
    """
    return _EVENT_TYPE_PATTERN.match(value) is not None


def require_valid_event_type(value: str) -> None:
    """Raise ``ValueError`` unless ``value`` matches the ``domain.action`` shape.

    The ``Envelope`` validator and ``HandlerRegistry`` share this so the
    grammar and its message live in exactly one place.
    """
    if not is_valid_event_type(value):
        raise ValueError(
            f"event_type must match '<domain>.<action>' in lowercase snake_case, got {value!r}"
        )


class Envelope(BaseModel, Generic[PayloadT]):
    """A typed event crossing the outbox seam.

    ``event_id`` is the dedupe key for at-least-once delivery; ``payload`` is a
    typed Pydantic model so the seam never passes raw dicts (coding-standards
    §3). Instances are created by the publishing module and carried unchanged
    to the subscriber.
    """

    event_id: UUID
    event_type: str
    schema_version: int = Field(default=1, ge=1)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    producer: str
    payload: PayloadT

    @field_validator("event_type")
    @classmethod
    def _event_type_must_be_domain_action(cls, value: str) -> str:
        require_valid_event_type(value)
        return value

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("producer")
    @classmethod
    def _producer_must_name_the_module(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("producer must name the publishing module")
        return value

    @field_validator("payload", mode="before")
    @classmethod
    def _payload_must_be_a_model_not_a_dict(cls, value: object) -> object:
        if isinstance(value, dict):
            raise ValueError("payload must be a Pydantic model, not a raw dict")
        return value
