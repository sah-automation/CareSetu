"""v8.16__pin_centroid_table_and_seed - PHASE-8 (#601) PIN centroid table + bulk seed

FEAT-004 (geo discovery), PHASE-8 #601, parent #599.

The doctor profile's practice position is a 6-digit PIN code resolved against a
bundled India-wide PIN centroid dataset, not a geocode and not a hand-typed
coordinate. This migration makes that dataset real: it creates
``partner.partner_pin_centroids`` and seeds it in bulk from the committed
``pin_centroids.csv.gz`` beside this file.

Shape:

- ``pin`` is the primary key and a 6-character column, never an integer. A PIN
  is a fixed-width character code, so an integer column would reinterpret the
  value numerically and break the fixed-width contract the source publishes.
  (No PIN in the current source begins with a zero - India Post numbers its
  first digit by region - so ``String`` over ``CHAR`` is the honest width.)
- No foreign key, deliberately. A PIN centroid is a reference dataset, not a
  partner row, so there is nothing to key to, and ADR-0003 forbids a
  cross-schema reference in any case. The later directory write copies the
  resolved point onto ``partner_profiles``; it does not join back to here.
- ``latitude`` / ``longitude`` are ``NUMERIC(9, 6)``, the same precision the
  profile's practice position already uses, so a resolved centroid drops
  straight into the derived-position write with no lossy conversion.
- ``district`` and ``region`` are the load-bearing text columns. The parent
  decision shows both back to the doctor as a read-only confirmation of a PIN
  they typed, so they are named as the read side finds them and carry no
  translation layer. ``region`` is India Post's ``RegionName`` verbatim, which
  is the placeholder string ``DivReportingCircle`` for the 4,087 PINs in
  single-region circles; that is published, not substituted, and deciding how
  the placeholder is presented is #603's. See ``pin_centroids.SOURCE.md``.

The seed mechanism is a generated multi-row ``INSERT ... VALUES ... ON CONFLICT
(pin) DO NOTHING``, batched, issued through ``op.execute``. It is deliberately
not row-by-row: the source file carries 19,258 PIN rows and the revision cannot
hold them as literals. It is deliberately not ``op.bulk_insert`` either, because
the two pre-existing precedents (the v5.4 Daltonganj service-area seed and the
v8.6 directory-index backfill) both reach for raw ``op.execute`` SQL with
``ON CONFLICT DO NOTHING`` as the idempotency guard, and the next person to add
a vocabulary should copy one shape rather than three.

``ON CONFLICT (pin) DO NOTHING`` is the re-run guard: seeding a database that
is already seeded changes nothing and never doubles a partial seed.

A PIN that is absent from the table is the designed failure mode, not an
incomplete seed. 42 PIN codes in the source have no usable coordinate anywhere
and are deliberately left out rather than given a default centroid, a coarse
fallback or a nearest-neighbour stand-in. The lookup's job is to be able to say
"no" honestly; the operator support request for an unlisted PIN is #620's.

Source, licence and retrieval date, and the full derivation rule set, are
recorded in ``pin_centroids.SOURCE.md`` next to this file.

Written by hand (ADR-0003 - a migration never imports current source), raw
``op.execute`` SQL like the rest of the partner migrations. The only imports
are the stdlib and ``alembic.op``.

Revision ID: 2022b1062d5e
Revises: c4e1a97b2d30
Create Date: 2026-09-30
"""

from __future__ import annotations

import csv
import gzip
from collections.abc import Iterator, Sequence
from pathlib import Path

from alembic import op

revision: str = "2022b1062d5e"
down_revision: str | Sequence[str] | None = "c4e1a97b2d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_FILE = Path(__file__).resolve().parent / "pin_centroids.csv.gz"

# Rows per generated INSERT statement. One statement per batch is still a bulk
# path (no row-by-row writes, no 19k round trips) while keeping each statement
# small enough for the server to parse without a large memory spike.
#
# Not configuration (coding-standards §9): this is not a tunable limit, it is
# how the frozen script chunks its own work, and a migration cannot read
# settings without making the same revision do different work per deployment
# (ADR-0003 immutability). Changing the chunking changes nothing an operator can
# observe, so there is nothing to externalise.
BATCH_SIZE = 500

# Column order of the seed file, and of every generated VALUES tuple.
SEED_COLUMNS = ("pin", "office_name", "district", "region", "latitude", "longitude")

# The two coordinate columns are numeric literals; the other four are quoted
# text and go through _text_literal.
_NUMERIC_COLUMNS = frozenset({"latitude", "longitude"})


def _text_literal(value: str) -> str:
    """Quote a seed value as a PostgreSQL string literal.

    Doubling the single quote is the standard-conforming escape (PostgreSQL runs
    with ``standard_conforming_strings = on``, so a backslash inside a plain
    quoted literal is just a backslash). The derivation filters the source down
    to values that need no escaping at all, so this is belt and braces.
    """
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _seed_rows() -> Iterator[tuple[str, ...]]:
    """Yield one tuple per PIN from the committed seed file, in file order."""
    with gzip.open(SEED_FILE, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != SEED_COLUMNS:
            raise RuntimeError(f"unexpected seed header in {SEED_FILE.name}: {reader.fieldnames}")
        for row in reader:
            yield tuple(row[column] for column in SEED_COLUMNS)


def _insert_statement(rows: Sequence[tuple[str, ...]]) -> str:
    """Build one multi-row INSERT ... ON CONFLICT DO NOTHING statement."""
    tuples: list[str] = []
    for row in rows:
        values = ", ".join(
            value if column in _NUMERIC_COLUMNS else _text_literal(value)
            for column, value in zip(SEED_COLUMNS, row, strict=True)
        )
        tuples.append(f"    ({values})")
    columns = ", ".join(SEED_COLUMNS)
    return (
        f"INSERT INTO partner.partner_pin_centroids ({columns})\n"
        f"VALUES\n" + ",\n".join(tuples) + "\nON CONFLICT (pin) DO NOTHING"
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE partner.partner_pin_centroids (
            pin VARCHAR(6) PRIMARY KEY,
            office_name VARCHAR(80) NOT NULL,
            district VARCHAR(80) NOT NULL,
            region VARCHAR(80) NOT NULL,
            latitude NUMERIC(9,6) NOT NULL,
            longitude NUMERIC(9,6) NOT NULL,
            CONSTRAINT ck_partner_pin_centroids_pin_format
                CHECK (pin ~ '^[0-9]{6}$'),
            CONSTRAINT ck_partner_pin_centroids_latitude
                CHECK (latitude BETWEEN -90 AND 90),
            CONSTRAINT ck_partner_pin_centroids_longitude
                CHECK (longitude BETWEEN -180 AND 180)
        )
        """
    )

    batch: list[tuple[str, ...]] = []
    for row in _seed_rows():
        batch.append(row)
        if len(batch) == BATCH_SIZE:
            op.execute(_insert_statement(batch))
            batch = []
    if batch:
        op.execute(_insert_statement(batch))


def downgrade() -> None:
    # Dropping the table takes the seeded rows with it - the seed is derived
    # data, not something a downgrade should try to preserve - and leaves the
    # schema exactly as v8.15 left it for the up-and-down round trip.
    op.execute("DROP TABLE IF EXISTS partner.partner_pin_centroids")
