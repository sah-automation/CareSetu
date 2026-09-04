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
