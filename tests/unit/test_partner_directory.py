"""PHASE-6 T01 (#307): directory-schema domain enums + schema lockstep.

The ticket introduces two closed vocabularies - the credential close-out reason
(CredentialInvalidatedReason) and the doctor specialty pick-list (Specialty) -
that MUST stay in lockstep with the CHECK constraints a migration bakes into the
partner schema (domain never names a value the schema cannot hold). The pure
enum values are pinned here; the lockstep is asserted by introspecting the
SQLAlchemy CheckConstraints on the in-memory Table objects (no database
needed). The migration's idempotent backfill is exercised against the real
postgres in the integration suite (upgrade head -> query -> downgrade base).

#602 widened the specialty pick-list to roughly twenty values, and #606 retired
the lockstep it was breaking: the directory entry's ``specialty`` column is now a
multi-valued JSONB selection and ``ck_partner_directory_index_specialty`` is
GONE. A CHECK cannot express "every member is one of twenty values, and a
non-doctor carries none" as readably as the domain's own validation can, so the
vocabulary moved to application level - ``require_specialty`` /
``require_specialties`` in ``domain/vocabularies.py``, plus the search's
explicit ``partner_type = 'doctor'`` pin. ``test_specialty_is_a_closed_strenum``
therefore now pins the vocabulary on its own, with no schema counterpart to keep
in step, and the test that replaced the lockstep one pins the widening itself so
the drop cannot be reverted by accident.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import CheckConstraint, Table
from sqlalchemy.dialects.postgresql import JSONB

from modules.partner.domain.credentials import CredentialInvalidatedReason
from modules.partner.domain.vocabularies import Specialty
from modules.partner.schema.models import (
    MODULE_METADATA,
    partner_credentials,
    partner_directory_index,
)


def _constraint_text(table: Table, name: str) -> str:
    constraints = [
        c for c in table.constraints if isinstance(c, CheckConstraint) and c.name == name
    ]
    assert constraints, f"{table.name} missing CHECK constraint {name}"
    return str(constraints[0].sqltext)


def test_credential_invalidated_reason_is_a_closed_strenum() -> None:
    assert issubclass(CredentialInvalidatedReason, StrEnum)
    # StrEnum compares equal to its string value.
    assert CredentialInvalidatedReason.EXPIRED == "expired"
    assert set(CredentialInvalidatedReason) == {
        CredentialInvalidatedReason.EXPIRED,
        CredentialInvalidatedReason.REVOKED,
        CredentialInvalidatedReason.REVERIFICATION_FAILED,
    }


def test_credential_close_out_reason_matches_schema_check() -> None:
    # The credential close-out fields serve ADR-0011; invalidation_reason is a
    # closed enum on partner_credentials.
    for value in CredentialInvalidatedReason:
        constraint = _constraint_text(
            partner_credentials, "ck_partner_credentials_invalidation_reason"
        )
        assert value.value in constraint


#: The four values the retired specialty CHECK constraint accepted. Retained as
#: a regression pin: every value the schema could once hold must still be a member
#: of the domain list, or a downgrade would leave live data the domain refuses.
LEGACY_SPECIALTIES = ("General Physician", "Pediatrician", "Gynecologist", "Dentist")


def test_specialty_is_a_closed_strenum() -> None:
    assert issubclass(Specialty, StrEnum)
    # StrEnum compares equal to its string value.
    assert Specialty.GENERAL_PHYSICIAN == "General Physician"
    values = {member.value for member in Specialty}
    assert set(LEGACY_SPECIALTIES) <= values


def test_directory_index_specialty_is_multi_valued_and_unconstrained() -> None:
    # #606 widened the column to the same JSONB-array shape the profile's own
    # ``specialties`` uses, which is the only shape a closed-list validator can be
    # applied to member by member.
    assert isinstance(partner_directory_index.c.specialty.type, JSONB)
    # Nullable, unlike the profile's NOT NULL selection: NULL is how a directory
    # entry says "carries no specialty" (a lab or chemist row, and every row
    # written before #606) and stays distinct from an empty selection.
    assert partner_directory_index.c.specialty.nullable
    # The doctors-only CHECK is GONE, on purpose: it hard-coded four values and
    # could not follow #602's twenty, and validation is application-level now.
    # Asserted by absence so re-adding a constraint that would reject a legitimate
    # specialty fails here rather than in production.
    assert [
        constraint
        for constraint in partner_directory_index.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_partner_directory_index_specialty"
    ] == []


def test_directory_index_is_registered_in_partner_schema() -> None:
    table = MODULE_METADATA.tables.get("partner.partner_directory_index")
    assert table is not None
    assert table.schema == "partner"
    for column in (
        "practice_latitude",
        "practice_longitude",
        "partner_type",
        "specialty",
        "is_active",
    ):
        assert column in table.c
    assert "partner_id" in table.primary_key.columns


def test_credentials_carry_close_out_columns() -> None:
    for column in ("revoked_at", "revoked_by", "invalidation_reason"):
        assert column in partner_credentials.c
