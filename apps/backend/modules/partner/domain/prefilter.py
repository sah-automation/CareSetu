"""MOD-002: the Step-1 credential pre-filter (PHASE-5 T06, ticket #251, ADR-0008).

The first half of the two-step verification gate. It is a pure domain decision
(no schema, facade or adapter imports) run synchronously on submission: format
validation (credential type is a known value AND appropriate for the partner
type, artifacts uploaded) and duplicate detection (a like credential type is
already live for the partner). Answered as :class:`PrefilterOutcome`:

- ``passed`` - the submission is well formed and not a duplicate. This is NOT
  approval (ADR-0008: no auto-approve path); it only advances the partner to the
  Step-2 operator queue.
- ``reason`` - a specific :class:`PrefilterReason` when ``passed`` is False. A
  failed pre-filter is the auto-fail path: the partner is returned straight to
  ``[Rejected]`` and is NEVER queued.

The facade is the only caller: it threads the verdict into the lifecycle
machine (``START_VERIFICATION`` on pass, ``AUTO_FAIL`` on fail) and persists the
outcome. Unit-tested here; the DB-backed transition is the integration suite's
job (mirroring ``test_consent_state_machine.py`` / ``test_partner_state_machine.py``).
"""

from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from enum import StrEnum

from modules.partner.domain.credentials import (
    ALLOWED_CREDENTIAL_TYPES_BY_PARTNER,
    CredentialType,
)


#: Specific, machine-readable auto-fail reasons emitted to ``partner.rejected``
#: and surfaced to the partner (ADR-0008 §1: a failure returns ``[Rejected]``
#: immediately with a specific reason).
class PrefilterReason(StrEnum):
    INVALID_CREDENTIAL_TYPE = "invalid_credential_type"
    MISSING_ARTIFACTS = "missing_artifacts"
    DUPLICATE_CREDENTIAL = "duplicate_credential"


#: Module-level constants so callers name reasons without importing the enum
#: values as literals.
INVALID_CREDENTIAL_TYPE = PrefilterReason.INVALID_CREDENTIAL_TYPE
MISSING_ARTIFACTS = PrefilterReason.MISSING_ARTIFACTS
DUPLICATE_CREDENTIAL = PrefilterReason.DUPLICATE_CREDENTIAL


@dataclass(frozen=True)
class PrefilterOutcome:
    """The Step-1 verdict for one credential submission.

    ``passed`` is True only for a well-formed, non-duplicate submission. ``reason``
    names the specific failure when ``passed`` is False (never when True).
    """

    passed: bool
    reason: PrefilterReason | None = None


def evaluate_submission(
    partner_type: str,
    credential_types: Sequence[str],
    has_artifacts: bool,
    existing_active_credential_types: AbstractSet[str],
) -> PrefilterOutcome:
    """Run the Step-1 pre-filter over a credential submission.

    Checks, in priority order:

    1. **Format** - every submitted credential type is a known closed value AND
       appropriate for the partner type (``invalid_credential_type``).
    2. **Artifacts** - the submission carries at least one encrypted document
       (``missing_artifacts``).
    3. **Duplicate** - no submitted credential type is already live for the
       partner (``duplicate_credential``). A credential only held in a
       previously-rejected state is not "live" - a rejected partner may
       re-submit the same type as a new verification round.

    ``existing_active_credential_types`` is the set of credential types already
    recorded for the partner in a non-rejected state; the caller computes it
    from the live ``partner_credentials`` rows.
    """
    _require_known_partner_type(partner_type)
    if not credential_types:
        return PrefilterOutcome(passed=False, reason=INVALID_CREDENTIAL_TYPE)

    allowed = ALLOWED_CREDENTIAL_TYPES_BY_PARTNER[partner_type]  # type: ignore[index]
    for raw_type in credential_types:
        credential_type = _credential_type(raw_type)
        if credential_type is None or credential_type not in allowed:
            return PrefilterOutcome(passed=False, reason=INVALID_CREDENTIAL_TYPE)

    if not has_artifacts:
        return PrefilterOutcome(passed=False, reason=MISSING_ARTIFACTS)

    for raw_type in credential_types:
        if raw_type in existing_active_credential_types:
            return PrefilterOutcome(passed=False, reason=DUPLICATE_CREDENTIAL)

    return PrefilterOutcome(passed=True)


def _require_known_partner_type(partner_type: str) -> None:
    if partner_type not in ALLOWED_CREDENTIAL_TYPES_BY_PARTNER:
        raise ValueError(f"unsupported partner_type {partner_type!r}")


def _credential_type(raw: str) -> CredentialType | None:
    try:
        return CredentialType(raw)
    except ValueError:
        return None
