"""PHASE-5 T06: the Step-1 credential pre-filter (ticket #251, ADR-0008).

The pre-filter is pure domain logic (no schema, facade or adapter imports), so
the unit suite pins the whole matrix without a database (prior art: the
consent/partner state-machine tests). It answers PASS or FAIL-with-a-specific-
reason for a credential submission. A FAIL is the auto-fail path that returns a
partner to ``[Rejected]`` and is NEVER queued; a PASS only advances to Step 2
(no auto-approve). Unit-tested here; the facade wires the verdict into the
lifecycle machine (``START_VERIFICATION`` vs ``AUTO_FAIL``) and the integration
suite proves the DB outcome.
"""

from __future__ import annotations

import pytest

from modules.partner.domain.credentials import CredentialType
from modules.partner.domain.prefilter import (
    DUPLICATE_CREDENTIAL,
    INVALID_CREDENTIAL_TYPE,
    MISSING_ARTIFACTS,
    PrefilterReason,
    evaluate_submission,
)

# Every credential type is a known enum value (mirrors the partner_credentials
# CHECK constraint, ADR-0008 closed per-partner-type enum).
_ALL_TYPES = (
    CredentialType.MEDICAL_REGISTRATION,
    CredentialType.QUALIFICATION_CERTIFICATE,
    CredentialType.LAB_LICENSE,
    CredentialType.ACCREDITATION,
    CredentialType.DRUG_LICENSE,
    CredentialType.PHARMACIST_REGISTRATION,
)


def test_every_partner_primary_credential_type_is_closed_in_enum() -> None:
    # The three flagship credential types the ticket names.
    assert CredentialType.MEDICAL_REGISTRATION in _ALL_TYPES
    assert CredentialType.LAB_LICENSE in _ALL_TYPES
    assert CredentialType.DRUG_LICENSE in _ALL_TYPES


def test_empty_submission_fails_with_invalid_credential_type() -> None:
    outcome = evaluate_submission(
        partner_type="doctor",
        credential_types=(),
        has_artifacts=True,
        existing_active_credential_types=frozenset(),
    )

    assert outcome.passed is False
    assert outcome.reason is INVALID_CREDENTIAL_TYPE


def test_unknown_credential_type_fails_with_invalid_credential_type() -> None:
    outcome = evaluate_submission(
        partner_type="doctor",
        credential_types=("not_a_credential",),
        has_artifacts=True,
        existing_active_credential_types=frozenset(),
    )

    assert outcome.passed is False
    assert outcome.reason is INVALID_CREDENTIAL_TYPE


@pytest.mark.parametrize(
    ("partner_type", "foreign_type"),
    [
        ("doctor", CredentialType.LAB_LICENSE),
        ("lab", CredentialType.MEDICAL_REGISTRATION),
        ("chemist", CredentialType.MEDICAL_REGISTRATION),
    ],
)
def test_credential_type_mismatching_partner_type_is_rejected(
    partner_type: str, foreign_type: CredentialType
) -> None:
    # A surgery's drug licence, a lab's medical registration etc. never belong
    # to the submitting partner type - known-bad value, rejected up front.
    outcome = evaluate_submission(
        partner_type=partner_type,
        credential_types=(foreign_type,),
        has_artifacts=True,
        existing_active_credential_types=frozenset(),
    )

    assert outcome.passed is False
    assert outcome.reason is INVALID_CREDENTIAL_TYPE


def test_doctor_medical_registration_with_artifacts_passes() -> None:
    outcome = evaluate_submission(
        partner_type="doctor",
        credential_types=(CredentialType.MEDICAL_REGISTRATION,),
        has_artifacts=True,
        existing_active_credential_types=frozenset(),
    )

    assert outcome.passed is True
    assert outcome.reason is None


def test_lab_lab_license_with_artifacts_passes() -> None:
    outcome = evaluate_submission(
        partner_type="lab",
        credential_types=(CredentialType.LAB_LICENSE,),
        has_artifacts=True,
        existing_active_credential_types=frozenset(),
    )

    assert outcome.passed is True


def test_chemist_drug_license_with_artifacts_passes() -> None:
    outcome = evaluate_submission(
        partner_type="chemist",
        credential_types=(CredentialType.DRUG_LICENSE,),
        has_artifacts=True,
        existing_active_credential_types=frozenset(),
    )

    assert outcome.passed is True


def test_missing_artifacts_fails_with_missing_artifacts() -> None:
    outcome = evaluate_submission(
        partner_type="doctor",
        credential_types=(CredentialType.MEDICAL_REGISTRATION,),
        has_artifacts=False,
        existing_active_credential_types=frozenset(),
    )

    assert outcome.passed is False
    assert outcome.reason is MISSING_ARTIFACTS


def test_duplicate_live_credential_fails_with_duplicate_credential() -> None:
    outcome = evaluate_submission(
        partner_type="doctor",
        credential_types=(CredentialType.MEDICAL_REGISTRATION,),
        has_artifacts=True,
        existing_active_credential_types=frozenset({CredentialType.MEDICAL_REGISTRATION}),
    )

    assert outcome.passed is False
    assert outcome.reason is DUPLICATE_CREDENTIAL


def test_duplicate_check_only_flags_the_offending_type() -> None:
    # A re-submission with one live credential type and one fresh type: the live
    # one trips the duplicate gate; the fresh one is fine on its own.
    outcome = evaluate_submission(
        partner_type="doctor",
        credential_types=(
            CredentialType.MEDICAL_REGISTRATION,
            CredentialType.QUALIFICATION_CERTIFICATE,
        ),
        has_artifacts=True,
        existing_active_credential_types=frozenset({CredentialType.MEDICAL_REGISTRATION}),
    )

    assert outcome.passed is False
    assert outcome.reason is DUPLICATE_CREDENTIAL


def test_type_check_runs_before_duplicate_check() -> None:
    # Priority is format (type validity) before duplicate, so a mismatched type
    # reports the type reason even if a like-named type is already live.
    outcome = evaluate_submission(
        partner_type="doctor",
        credential_types=(CredentialType.DRUG_LICENSE,),
        has_artifacts=True,
        existing_active_credential_types=frozenset({CredentialType.DRUG_LICENSE}),
    )

    assert outcome.passed is False
    assert outcome.reason is INVALID_CREDENTIAL_TYPE


def test_rejected_partner_can_resubmit_same_credential_type() -> None:
    # A Rejected partner re-submitting a credential type they already hold is a
    # NEW verification round (T09), not a duplicate - the duplicate gate only
    # fires on credentials already live in a non-rejected state.
    outcome = evaluate_submission(
        partner_type="lab",
        credential_types=(CredentialType.LAB_LICENSE,),
        has_artifacts=True,
        existing_active_credential_types=frozenset(),
    )

    assert outcome.passed is True


def test_non_primary_document_with_artifacts_passes_for_matching_partner() -> None:
    # A doctor submitting a qualification certificate (their required primary
    # was a medical_registration, already present) is a valid non-primary doc.
    outcome = evaluate_submission(
        partner_type="doctor",
        credential_types=(CredentialType.QUALIFICATION_CERTIFICATE,),
        has_artifacts=True,
        existing_active_credential_types=frozenset(),
    )

    assert outcome.passed is True


def test_prefilter_reasons_are_closed() -> None:
    assert {r.value for r in PrefilterReason} == {
        INVALID_CREDENTIAL_TYPE.value,
        MISSING_ARTIFACTS.value,
        DUPLICATE_CREDENTIAL.value,
    }
