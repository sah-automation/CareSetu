"""PHASE-6 T01 (#307): directory-schema domain enums + schema lockstep.

The ticket introduces two closed vocabularies - the credential close-out reason
(CredentialInvalidatedReason) and the doctor specialty pick-list (Specialty) -
that MUST stay in lockstep with the CHECK constraints a migration bakes into the
partner schema (domain never names a value the schema cannot hold). The pure
enum values are pinned here; the lockstep is asserted by introspecting the
SQLAlchemy CheckConstraints on the in-memory Table objects (no database
needed). The migration's idempotent backfill is exercised against the real
Postgres in the integration suite (upgrade head -> query -> downgrade base).
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import CheckConstraint, Table

from modules.partner.domain.credentials import (
    CredentialInvalidatedReason,
    Specialty,
)
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


def test_specialty_is_a_closed_strenum() -> None:
    assert issubclass(Specialty, StrEnum)
    assert set(Specialty) == {
        Specialty.GENERAL_PHYSICIAN,
        Specialty.PEDIATRICIAN,
        Specialty.GYNECOLOGIST,
        Specialty.DENTIST,
    }


def test_specialty_matches_directory_index_check() -> None:
    constraint = _constraint_text(partner_directory_index, "ck_partner_directory_index_specialty")
    for value in Specialty:
        assert value.value in constraint


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
