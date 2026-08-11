"""PHASE-1 T6b (#27): migration-check cross-schema FK rule - fixture tests.

Feeds throwaway migration trees to ``scripts.check_migrations_fk`` and asserts
the FK-scan acceptance criteria: a migration whose foreign key references a
table in another schema - spelled via ``create_foreign_key`` schema kwargs,
dotted qualified names, a ``ForeignKeyConstraint``, or an inline ``ForeignKey``
against a table declared in another schema - is rejected; same-schema foreign
keys and migrations without foreign keys pass; and the real migration tree
passes the same scan. The script-level CLI exit code is exercised too, which is
what ``npm run migration-check`` relays.
"""

from pathlib import Path

import pytest
from scripts.check_migrations_fk import (
    MigrationViolation,
    check_migrations_fk,
    main,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "apps" / "backend"

REVISION_HEADER = (
    '"""fixture migration"""\n\n'
    "from alembic import op\n"
    "import sqlalchemy as sa\n\n"
    'revision: str = "a1b2c3d4e5f6"\n'
    'down_revision: str = "dc0eaa6366a1"\n'
    "branch_labels = None\n"
    "depends_on = None\n\n"
)


def _write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _messages(violations: tuple[MigrationViolation, ...]) -> list[str]:
    return [violation.message for violation in violations]


def _assert_cross_schema(violations: tuple[MigrationViolation, ...]) -> None:
    assert any("cross-schema foreign key" in message for message in _messages(violations))


def test_create_foreign_key_schema_kwargs_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "abc123_care_consent_fk.py",
        REVISION_HEADER + "def upgrade() -> None:\n"
        "    op.create_foreign_key(\n"
        '        "fk_care_consent",\n'
        '        "care_prescriptions",\n'
        '        "consent_consents",\n'
        '        ["consent_id"],\n'
        '        ["id"],\n'
        '        source_schema="care",\n'
        '        referent_schema="consent",\n'
        "    )\n",
    )

    _assert_cross_schema(check_migrations_fk(tmp_path))


def test_create_foreign_key_dotted_names_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "abc123_care_consent_fk.py",
        REVISION_HEADER + "def upgrade() -> None:\n"
        "    op.create_foreign_key(\n"
        '        "fk_care_consent",\n'
        '        "care.prescriptions",\n'
        '        "consent.consent_consents",\n'
        '        ["consent_id"],\n'
        '        ["id"],\n'
        "    )\n",
    )

    _assert_cross_schema(check_migrations_fk(tmp_path))


def test_create_foreign_key_against_declared_tables_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "aaa111_consent_tables.py",
        REVISION_HEADER + "def upgrade() -> None:\n"
        "    op.create_table(\n"
        '        "consent_consents",\n'
        '        sa.Column("id", sa.BigInteger(), primary_key=True),\n'
        '        schema="consent",\n'
        "    )\n"
        "    op.create_table(\n"
        '        "care_prescriptions",\n'
        '        sa.Column("id", sa.BigInteger(), primary_key=True),\n'
        '        sa.Column("consent_id", sa.BigInteger(), nullable=False),\n'
        '        schema="care",\n'
        "    )\n",
    )
    _write(
        tmp_path,
        "bbb222_care_consent_fk.py",
        REVISION_HEADER + "def upgrade() -> None:\n"
        "    op.create_foreign_key(\n"
        '        "fk_care_consent",\n'
        '        "care_prescriptions",\n'
        '        "consent_consents",\n'
        '        ["consent_id"],\n'
        '        ["id"],\n'
        "    )\n",
    )

    _assert_cross_schema(check_migrations_fk(tmp_path))


def test_foreign_key_constraint_dotted_referent_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "abc123_care_consent_fk.py",
        REVISION_HEADER + "def upgrade() -> None:\n"
        "    op.create_table(\n"
        '        "care_prescriptions",\n'
        '        sa.Column("id", sa.BigInteger(), primary_key=True),\n'
        '        sa.Column("consent_id", sa.BigInteger(), nullable=False),\n'
        '        sa.ForeignKeyConstraint(["consent_id"], ["consent.consent_consents.id"]),\n'
        '        schema="care",\n'
        "    )\n",
    )

    _assert_cross_schema(check_migrations_fk(tmp_path))


def test_inline_foreign_key_against_declared_table_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "aaa111_consent_table.py",
        REVISION_HEADER + "def upgrade() -> None:\n"
        "    op.create_table(\n"
        '        "consent_consents",\n'
        '        sa.Column("id", sa.BigInteger(), primary_key=True),\n'
        '        schema="consent",\n'
        "    )\n",
    )
    _write(
        tmp_path,
        "bbb222_care_table.py",
        REVISION_HEADER + "def upgrade() -> None:\n"
        "    op.create_table(\n"
        '        "care_prescriptions",\n'
        '        sa.Column("id", sa.BigInteger(), primary_key=True),\n'
        "        sa.Column(\n"
        '            "consent_id",\n'
        "            sa.BigInteger(),\n"
        '            sa.ForeignKey("consent_consents.id"),\n'
        "            nullable=False,\n"
        "        ),\n"
        '        schema="care",\n'
        "    )\n",
    )

    _assert_cross_schema(check_migrations_fk(tmp_path))


def test_same_schema_foreign_key_passes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "abc123_care_internal_fk.py",
        REVISION_HEADER + "def upgrade() -> None:\n"
        "    op.create_table(\n"
        '        "care_clinicians",\n'
        '        sa.Column("id", sa.BigInteger(), primary_key=True),\n'
        '        schema="care",\n'
        "    )\n"
        "    op.create_table(\n"
        '        "care_prescriptions",\n'
        '        sa.Column("id", sa.BigInteger(), primary_key=True),\n'
        '        sa.Column("clinician_id", sa.BigInteger(), nullable=False),\n'
        '        sa.ForeignKeyConstraint(["clinician_id"], ["care_clinicians.id"]),\n'
        '        schema="care",\n'
        "    )\n",
    )

    assert check_migrations_fk(tmp_path) == ()


def test_unresolvable_schema_fk_passes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "abc123_ambiguous_fk.py",
        REVISION_HEADER + "def upgrade() -> None:\n"
        "    op.create_foreign_key(\n"
        '        "fk_care_consent",\n'
        '        "care_prescriptions",\n'
        '        "consent_consents",\n'
        '        ["consent_id"],\n'
        '        ["id"],\n'
        "    )\n",
    )

    assert check_migrations_fk(tmp_path) == ()


def test_migration_without_foreign_keys_passes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "abc123_schemas.py",
        REVISION_HEADER + "def upgrade() -> None:\n"
        "    op.execute('CREATE SCHEMA IF NOT EXISTS \"care\"')",
    )

    assert check_migrations_fk(tmp_path) == ()


def test_main_fails_on_cross_schema_fk(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(
        tmp_path,
        "abc123_care_consent_fk.py",
        REVISION_HEADER + "def upgrade() -> None:\n"
        "    op.create_foreign_key(\n"
        '        "fk_care_consent",\n'
        '        "care_prescriptions",\n'
        '        "consent_consents",\n'
        '        ["consent_id"],\n'
        '        ["id"],\n'
        '        source_schema="care",\n'
        '        referent_schema="consent",\n'
        "    )\n",
    )

    assert main(["--versions-dir", str(tmp_path)]) == 1
    assert "cross-schema foreign key" in capsys.readouterr().err


def test_main_reports_clean_tree_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(
        tmp_path,
        "abc123_schemas.py",
        REVISION_HEADER + "def upgrade() -> None:\n"
        "    op.execute('CREATE SCHEMA IF NOT EXISTS \"care\"')",
    )

    assert main(["--versions-dir", str(tmp_path)]) == 0
    assert "no cross-schema foreign keys" in capsys.readouterr().out


def test_real_migration_tree_passes() -> None:
    assert check_migrations_fk(BACKEND_ROOT / "alembic" / "versions") == ()
