"""v8.17__structured_profile_columns - PHASE-8 (#606) structured profile columns

FEAT-004/005 (doctor profile, provider directory), PHASE-8 #606, parent #599.

The doctor profile gains the shape the profile redesign needs, so the section
writes after this one (#608 practice, #609 address, #610 about/notifications)
have columns to write rather than free-text fields to parse.

Shape:

- ``clinic_name`` is the building the practice is in, distinct from
  ``practice_name``, which is the doctor's own name and stays the only
  patient-searchable name.
- ``specialties``, ``consulting_days`` and ``languages`` are all the same
  multi-valued storage shape - ``JSONB`` defaulting to an empty array - because
  that is the only shape a closed-list validator can be applied to member by
  member without re-deriving a parse. Their vocabularies are owned by
  ``modules/partner/domain/vocabularies.py`` (#602): ``Specialty``,
  ``ConsultingDay`` and ``ConsultLanguage``. The ``languages`` column already
  had this shape; only its contents were hand-typed free text, so it needed no
  DDL change here.
- The structured address is five nullable parts - ``address_line``,
  ``address_landmark``, ``address_locality``, ``address_city`` and
  ``address_pin`` - matching ``AddressParts`` in ``domain/practice_position.py``
  (#603). ``address_pin`` is deliberately **not** a foreign key to
  ``partner_pin_centroids`` (#601): like ``service_area_id``, it is a
  same-schema value the write resolves through the domain, so a bad PIN returns
  a field-level error instead of failing the save on a data reason. It carries
  the same six-digit format CHECK the centroid table's key carries.
- ``consulting_hours`` supersedes ``availability``. ``availability`` is kept,
  not dropped: it is a ``TEXT NOT NULL``-free nullable column that existing rows
  and the shipped whole-form write still address, and dropping it here would
  break both. Superseding means ``consulting_hours`` is what new writes fill and
  what the read side projects; ``availability`` is inert.

``practice_address`` is retained, unchanged in name, type and nullability, and
becomes a **denormalised display projection** of the structured parts. It has two
writers: registration (``insert_registered_profile``) still writes the
pre-structured value it captured at sign-up, unchanged, and the address section
write (#609) rewrites it from the structured parts via
``format_display_address``. Three projections read it - the private doctor
profile view, the operator verification queue row and the operator per-partner
detail row - so it must stay ``NOT NULL`` for as long as registration is a
writer. This migration does not touch it.

Latitude and longitude stay ``NOT NULL`` with their range CHECKs intact and stop
being client-writable: the update schemas drop both fields, so with
``extra="forbid"`` a request that still sends them is a live 422 rather than a
silent write. The practice position becomes server-written - #609 derives it
from the declared PIN. This is deliberately not a data migration: no existing
coordinate is rewritten here.

The directory entry's ``specialty`` widens from ``VARCHAR(40)`` to multi-valued
``JSONB``, and ``ck_partner_directory_index_specialty`` is **dropped**. A CHECK
constraint cannot express "every member is one of twenty values, and a non-doctor
never carries any" as readably as application-level validation can, and #602
widened the pick-list past the four literals the constraint hard-codes. The
constraint was the last place the schema and the domain had to agree by hand;
dropping it retires that lockstep in favour of
``require_specialties``/``require_specialty`` (#602) plus the explicit
``partner_type = 'doctor'`` pin the search keeps. This narrows the *database's*
enforcement deliberately, in exchange for validation the domain actually owns.

The column stays nullable rather than becoming ``NOT NULL DEFAULT '[]'``: NULL is
how the directory entry says "carries no specialty" - a lab or chemist row, and
every row written before this migration - and the glossary keeps that as a
distinct state from a doctor who has declared an empty selection.

Data reset, and why nothing is parsed:

``languages`` and the superseded ``availability`` were typed by hand against help
text reading "Separate with commas" and a placeholder reading "e.g. Mon-Sat,
9am-1pm". Recovering selections from those strings is guesswork, and a wrong
guess is worse than an empty prompt because the doctor then has to notice and
correct a machine's invention of their working hours. So this migration **resets
and does not parse**: ``languages`` returns to the empty array, and the directory
entry's existing specialty values are normalised to the empty multi-value rather
than wrapped into a one-member array or carried forward into a column whose
validation is now application-level. ``specialties`` and ``consulting_days`` are
new columns, so "reset to empty" is already true by construction. The result is
that the "doctor with no specialties yet" state is the real-world default, not an
edge case.

``experience_years`` tightens from ``0..100`` to ``0..60``. 100 is not a range a
practising doctor can hold: medical entry in India is around 22-24, so the oldest
plausible first registration puts the ceiling near 60 and the bound leaves
headroom over it. 60 is high enough that no legitimate value is refused - which
matters because the field exists for the longest-career doctors - while making
the non-realistic tail unrepresentable. The bound lives in four places (the
CHECK here, the schema declaration, and the update and view models' ``Field``);
the profile page's own client-side ``LIMITS`` stays ``0..100``, which is a
superset and therefore never refuses a legitimate value. #608/#611 own the
client.

Existing rows upgrade cleanly: every column added here is nullable or defaulted,
so the raw-SQL row inserts in the integration suites keep working untouched.

Migration discipline:

- Written by hand (ADR-0003 - a migration never imports current source), raw
  ``op.execute`` SQL like the rest of the partner migrations, one statement per
  ``op.execute``.
- ``downgrade()`` is a real reversal for the column additions and both constraint
  swaps, dropping the new PIN CHECK before the columns it covers. The data reset
  is a **no-op**, for the reason the v8.6 backfill records: a migration that
  converges data toward the live path's outcome and invents nothing is
  irreversibly correct, and putting the parsed free text back is not a reversal
  anyone wants.
- The narrowed directory column is restored to ``VARCHAR(40)``, empty array to
  NULL and the first member to itself, but the retired CHECK is **not**
  re-added: it names only the four pre-#602 values, so re-adding it would make a
  downgrade fail on any row carrying a value the live code legitimately writes.
- ``address_pin`` and the directory entry's ``partner_id`` are the only same-
  schema references involved and neither is a foreign key; the FK scanner is a
  no-op confirmation here.

Revision ID: 3e7c5a1d8f24
Revises: 2022b1062d5e
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "3e7c5a1d8f24"
down_revision: str | Sequence[str] | None = "2022b1062d5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) The declared shape. Every column is nullable or defaulted, so this is a
    #    widening an existing row survives without a rewrite: the structured
    #    address parts (all optional, #603's AddressParts), the clinic name, the
    #    two new multi-valued selections in the same JSONB-array shape as
    #    ``languages``, and consulting hours as prose. The PIN carries the same
    #    six-digit format CHECK the centroid table's key carries (#601) - a
    #    format rule, not a vocabulary the domain has to own, and it holds
    #    without a foreign key so a bad PIN is still a field-level error rather
    #    than a failed save.
    op.execute(
        """
        ALTER TABLE partner.partner_profiles
            ADD COLUMN clinic_name VARCHAR(120),
            ADD COLUMN specialties JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN address_line VARCHAR(200),
            ADD COLUMN address_landmark VARCHAR(200),
            ADD COLUMN address_locality VARCHAR(120),
            ADD COLUMN address_city VARCHAR(120),
            ADD COLUMN address_pin VARCHAR(6),
            ADD COLUMN consulting_days JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN consulting_hours TEXT,
            ADD CONSTRAINT ck_partner_profiles_address_pin
                CHECK (address_pin IS NULL OR address_pin ~ '^[0-9]{6}$');
        """
    )

    # 2) The experience-years bound tightens to a realistic range. Dropped and
    #    re-added in one statement so the row is never briefly unconstrained,
    #    and so the swap is atomic.
    op.execute(
        """
        ALTER TABLE partner.partner_profiles
            DROP CONSTRAINT ck_partner_profiles_experience_years,
            ADD CONSTRAINT ck_partner_profiles_experience_years
                CHECK (
                    experience_years IS NULL
                    OR experience_years BETWEEN 0 AND 60
                );
        """
    )

    # 3) The directory entry's specialty widens to multi-valued and its CHECK
    #    goes. The CHECK is dropped in the same statement as the type change so
    #    PostgreSQL does not re-validate it against the new type, and so no
    #    legacy value is ever measured against a four-value vocabulary the domain
    #    retired in #602. The USING clause normalises every legacy value to the
    #    empty multi-value rather than wrapping it into a one-member array: the
    #    value is not parsed, and nothing is carried forward into a column whose
    #    validation is now application-level. NULL stays NULL, because NULL is
    #    how this column still says "carries no specialty".
    #
    #    The drop is ``IF EXISTS`` so that this upgrade stays re-appliable over a
    #    database this migration's own downgrade has already run against: the
    #    downgrade deliberately leaves the retired CHECK behind, so an unguarded
    #    ``DROP CONSTRAINT`` would make any ``alembic downgrade`` followed by
    #    ``alembic upgrade head`` - an ordinary operator recovery - fail here, at
    #    the head of the chain, with the database stranded between revisions. The
    #    guard costs nothing at the real head, where the constraint is present.
    op.execute(
        """
        ALTER TABLE partner.partner_directory_index
            DROP CONSTRAINT IF EXISTS ck_partner_directory_index_specialty,
            ALTER COLUMN specialty TYPE JSONB
                USING (
                    CASE
                        WHEN specialty IS NULL THEN NULL::jsonb
                        ELSE '[]'::jsonb
                    END
                );
        """
    )

    # 4) The data reset, for the two columns that were never reliably
    #    structured: hand-typed free text is emptied, never parsed. Guarded so a
    #    re-run against an already-reset database touches no row.
    op.execute(
        """
        UPDATE partner.partner_profiles
        SET languages = '[]'::jsonb
        WHERE languages <> '[]'::jsonb;
        """
    )


def downgrade() -> None:
    # The data reset is irreversibly correct and is not reversed: it converges
    # existing rows toward the live path's outcome and invents nothing. Putting
    # hand-typed free text back into a column the closed vocabulary now owns is
    # not a reversal anyone wants, and no information is lost that the doctor did
    # not retype. The v8.6 backfill records the same reasoning for the same call.

    # 1) The directory entry narrows back to a single value: the empty
    #    multi-value to NULL, and the first member to itself. The retired CHECK is
    #    deliberately not re-added - it names only the four pre-#602 values, so
    #    re-adding it would make this downgrade fail on any row carrying a value
    #    the live code legitimately writes. That constraint's enforcement is
    #    superseded by the domain vocabulary (#602) plus the search's explicit
    #    doctor pin, and a downgrade that rejects live data is worse than one
    #    that leaves a check behind.
    op.execute(
        """
        ALTER TABLE partner.partner_directory_index
            ALTER COLUMN specialty TYPE VARCHAR(40)
                USING (
                    CASE
                        WHEN specialty IS NULL OR specialty = '[]'::jsonb
                            THEN NULL::varchar(40)
                        ELSE specialty ->> 0
                    END
                );
        """
    )

    # 2) The experience-years bound returns to the pre-#606 range, and the
    #    guarantee goes with it: after this statement the database accepts
    #    values the current models reject.
    op.execute(
        """
        ALTER TABLE partner.partner_profiles
            DROP CONSTRAINT ck_partner_profiles_experience_years,
            ADD CONSTRAINT ck_partner_profiles_experience_years
                CHECK (
                    experience_years IS NULL
                    OR experience_years BETWEEN 0 AND 100
                );
        """
    )

    # 3) The declared shape comes off, in reverse order, and the new PIN CHECK
    #    before the column it covers. ``practice_address`` and ``availability``
    #    are untouched by this revision and so are not dropped here.
    op.execute(
        """
        ALTER TABLE partner.partner_profiles
            DROP CONSTRAINT ck_partner_profiles_address_pin,
            DROP COLUMN consulting_hours,
            DROP COLUMN consulting_days,
            DROP COLUMN address_pin,
            DROP COLUMN address_city,
            DROP COLUMN address_locality,
            DROP COLUMN address_landmark,
            DROP COLUMN address_line,
            DROP COLUMN specialties,
            DROP COLUMN clinic_name;
        """
    )
