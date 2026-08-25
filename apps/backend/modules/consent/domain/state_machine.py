"""MOD-004: the pure consent state machine (PHASE-3 T3, ticket #212).

The binding, prototype-derived machine ratified in the PHASE-3 grilling
session (spec #209 "Consent model"):

    Requested --grant--> Granted(v1..vN) --revoke--> Revoked
       |                     | regrant                  |
       +- decline            +-------------> Granted(vN+1) (revoke again)

Lineage rules: a lineage is the ``(patient, counterparty type,
counterparty id, record scope)`` identity carried by one ``consent_consents``
row; ``version`` counts the grants minted inside it (0 = never granted).
Versions are immutable once terminal - revocation is terminal for that
version and only a fresh re-grant continues the lineage at ``vN+1``. A
declined request closed without creating any grant, so a later explicit
grant to the same triple starts the lineage at v1 (the unique key leaves
no second row to start).

Pure decision logic only: no imports from schema, facade or adapters -
the persistence layer applies what this module decides (coding-standards §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from modules.consent.domain.exceptions import IllegalConsentTransitionError

# The closed record-scope enum (CONTEXT.md glossary "record scope"):
# never per-entry, never free-form.
RECORD_SCOPES: tuple[str, ...] = (
    "consultations",
    "prescriptions",
    "lab_results",
    "metrics",
    "full_record",
)


class ConsentStatus(StrEnum):
    """Row status; ``declined`` is the closed-without-grant terminal state."""

    REQUESTED = "requested"
    GRANTED = "granted"
    REVOKED = "revoked"
    DECLINED = "declined"


class ConsentAction(StrEnum):
    """The lifecycle actions a consent row can be asked to take."""

    GRANT = "grant"
    REVOKE = "revoke"
    DECLINE = "decline"


@dataclass(frozen=True)
class ConsentState:
    """One immutable snapshot of a consent lineage.

    ``version`` counts the grants inside the lineage; a granted or revoked
    state's version never mutates - every further grant mints the next one.
    """

    status: ConsentStatus
    version: int


REQUESTED: ConsentState = ConsentState(status=ConsentStatus.REQUESTED, version=0)

_LEGAL_TRANSITIONS: dict[tuple[ConsentStatus, ConsentAction], str] = {
    (ConsentStatus.REQUESTED, ConsentAction.GRANT): "granted_next_version",
    (ConsentStatus.REQUESTED, ConsentAction.DECLINE): "declined",
    (ConsentStatus.GRANTED, ConsentAction.GRANT): "granted_next_version",
    (ConsentStatus.GRANTED, ConsentAction.REVOKE): "revoked_same_version",
    (ConsentStatus.REVOKED, ConsentAction.GRANT): "granted_next_version",
    (ConsentStatus.DECLINED, ConsentAction.GRANT): "granted_next_version",
}


def transition(state: ConsentState, action: ConsentAction) -> ConsentState:
    """Apply ``action`` to ``state``, answering the next immutable state.

    Raises :class:`IllegalConsentTransitionError` for every edge outside the
    binding machine - including revoke of a never-granted request, decline of
    a live grant, and any action on an already-terminal revoked version.
    """
    outcome = _LEGAL_TRANSITIONS.get((state.status, action))
    if outcome is None:
        raise IllegalConsentTransitionError(
            f"{action.value} is illegal while the consent is {state.status.value}"
        )
    if outcome == "declined":
        return ConsentState(status=ConsentStatus.DECLINED, version=state.version)
    if outcome == "revoked_same_version":
        return ConsentState(status=ConsentStatus.REVOKED, version=state.version)
    return ConsentState(status=ConsentStatus.GRANTED, version=state.version + 1)
