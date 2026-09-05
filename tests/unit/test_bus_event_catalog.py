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


def test_partner_events_are_registered_in_the_catalog() -> None:
    # PHASE-5 T04 (#247): the partner lifecycle event vocabulary is a first-class
    # part of the registry - each constant names the canonical dot-notation and
    # satisfies the domain.action grammar like every other catalog entry.
    partner_events = {
        "EVENT_PARTNER_REGISTERED": "partner.registered",
        "EVENT_PARTNER_VERIFICATION_STARTED": "partner.verification_started",
        "EVENT_PARTNER_ACTIVATED": "partner.activated",
        "EVENT_PARTNER_REJECTED": "partner.rejected",
        "EVENT_PARTNER_CREDENTIAL_REVIEWED": "partner.credential_reviewed",
        "EVENT_CREDENTIAL_INVALIDATED": "credential.invalidated",
        "EVENT_DIRECTORY_SEARCH": "directory.search",
    }
    for name, value in partner_events.items():
        assert getattr(events, name) == value
        require_valid_event_type(value)
