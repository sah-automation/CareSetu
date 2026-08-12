"""Canonical event-name catalog tests (ticket #55 follow-up).

Every ``EVENT_*`` constant in ``bus.events`` must satisfy the registry
``domain.action`` grammar that the ``Envelope`` and ``HandlerRegistry``
enforce, and the constants must be distinct strings. This pins the grammar on
the catalog directly so a future constant cannot slip past with the legacy
snake_case telemetry form that once caused the dot-notation vs snake_case
event-name mismatch (tickets #54/#55).
"""

from bus import events
from bus.envelope import require_valid_event_type


def _catalog_values() -> list[str]:
    return [value for name, value in vars(events).items() if name.startswith("EVENT_")]


def test_every_catalog_constant_matches_domain_action() -> None:
    for value in _catalog_values():
        require_valid_event_type(value)


def test_catalog_constants_are_distinct() -> None:
    values = _catalog_values()
    assert len(values) == len(set(values))
