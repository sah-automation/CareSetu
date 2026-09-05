"""MOD-002: the closed credential-type vocabulary (PHASE-5 T06, ticket #251).

The partner module's professional-document vocabulary, fixed per partner type
(ADR-0008: a ``doctor`` submits a medical registration, a ``lab`` a lab license,
a ``chemist`` a drug license; each may carry one or two supporting documents).
The enum mirrors the ``partner_credentials.credential_type`` CHECK constraint so
the domain never names a value the schema cannot hold - a single source of truth
for the closed enum (coding-standards §3, pure domain: no schema imports).
"""

from __future__ import annotations

from enum import StrEnum

from modules.partner.domain.events import PartnerType


#: The full closed set of credential types the ``partner_credentials`` table can
#: hold (must stay in lockstep with ``ck_partner_credentials_credential_type``).
class CredentialType(StrEnum):
    MEDICAL_REGISTRATION = "medical_registration"
    QUALIFICATION_CERTIFICATE = "qualification_certificate"
    LAB_LICENSE = "lab_license"
    ACCREDITATION = "accreditation"
    DRUG_LICENSE = "drug_license"
    PHARMACIST_REGISTRATION = "pharmacist_registration"


#: The credential types a partner of each type may submit (ADR-0008, FEAT-014):
#: a doctor registers with a medical registration plus qualification documents,
#: a lab with a lab license/accreditation, a chemist with a drug license /
#: pharmacist registration). Mismatched types are rejected by the Step-1
#: pre-filter.
ALLOWED_CREDENTIAL_TYPES_BY_PARTNER: dict[PartnerType, frozenset[CredentialType]] = {
    "doctor": frozenset(
        {CredentialType.MEDICAL_REGISTRATION, CredentialType.QUALIFICATION_CERTIFICATE}
    ),
    "lab": frozenset({CredentialType.LAB_LICENSE, CredentialType.ACCREDITATION}),
    "chemist": frozenset({CredentialType.DRUG_LICENSE, CredentialType.PHARMACIST_REGISTRATION}),
}


#: The closed set of reasons a credential stops being valid (PHASE-6 T01, #307;
#: ADR-0011). Mirrors ``ck_partner_credentials_invalidation_reason`` so the
#: domain never names a close-out the schema cannot hold. ``expired`` is the
#: date-passed-without-renewal trigger (daily sweep); ``revoked`` is the
#: taken-away-by-authority/operator trigger (immediate, ``invalidate_credential``);
#: ``reverification_failed`` is the existing Phase 5 active-partner failure path
#: (re-verification reject / grace lapse).
class CredentialInvalidatedReason(StrEnum):
    EXPIRED = "expired"
    REVOKED = "revoked"
    REVERIFICATION_FAILED = "reverification_failed"


#: The closed pick-list of the kind of care an [Active] doctor offers
#: (FEAT-004, glossary). Doctors only - labs and chemists carry no specialty,
#: the field is never free-form. Mirrors the ``directory_index.specialty``
#: CHECK constraint and pre-seeds the homepage/directory search filter chips.
class Specialty(StrEnum):
    GENERAL_PHYSICIAN = "General Physician"
    PEDIATRICIAN = "Pediatrician"
    GYNECOLOGIST = "Gynecologist"
    DENTIST = "Dentist"
