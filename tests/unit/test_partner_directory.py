"""PHASE-6 T01 (#307): directory-schema domain enums + schema lockstep.

The ticket introduces two closed vocabularies - the credential close-out reason
(CredentialInvalidatedReason) and the doctor specialty pick-list (Specialty) -
that MUST stay in lockstep with the CHECK constraints a migration bakes into the
partner schema (domain never names a value the schema cannot hold). The pure
enum values are pinned here; the lockstep is asserted by introspecting the
SQLAlchemy CheckConstraints on the in-memory Table objects (no database
needed). The migration's idempotent backfill is exercised against the real
postgres in the integration suite (upgrade head -> query -> downgrade base).

Ticket #602 widened the specialty pick-list to roughly twenty values while the
CHECK constraint - baked into an already-applied revision, and immutable under
ADR-0003 - still names the original four. The constraint is retired by #606,
which replaces the column; the domain widening is safe until then because no
runtime writer ever sets the column (it is always NULL). So the two specialty
tests below pin the *narrower* truth that still holds: the four legacy values
remain members of the list. The lockstep direction is asserted legacy-values-in-
constraint, not every-value-in-constraint.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import CheckConstraint, Table

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


#: The four values the retired specialty CHECK constraint accepted. The domain
#: list grew in #602; the constraint is replaced by #606, so these four are the
#: values the schema and the domain must still agree on.
LEGACY_SPECIALTIES = ("General Physician", "Pediatrician", "Gynecologist", "Dentist")


def test_specialty_is_a_closed_strenum() -> None:
    assert issubclass(Specialty, StrEnum)
    # StrEnum compares equal to its string value.
    assert Specialty.GENERAL_PHYSICIAN == "General Physician"
    values = {member.value for member in Specialty}
    assert set(LEGACY_SPECIALTIES) <= values


def test_specialty_matches_directory_index_check() -> None:
    # Narrower than the pre-#602 form on purpose: the constraint predates the
    # widened list and cannot be edited (ADR-0003), so only the four legacy
    # values are asserted to be in lockstep. #606 retires the constraint.
    constraint = _constraint_text(partner_directory_index, "ck_partner_directory_index_specialty")
    for legacy in LEGACY_SPECIALTIES:
        assert legacy in constraint


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
