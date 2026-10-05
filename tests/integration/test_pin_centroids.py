"""PHASE-8 #601: the PIN centroid table and its bulk seed against Postgres (FEAT-004).

The seed runs as part of the v8.16 migration upgrade, so each test drives the
database itself: upgrade to head, assert, and leave the schema as found.

What is proven here, beyond the table's presence in the bootstrap suite's
expected-table set:

1. The committed seed file is byte-for-byte the dataset the migration's
   provenance record describes, and every row of it reached the table exactly
   once through the generated batched INSERT (so the count matches the file,
   not a subset).
2. A real PIN resolves to a real centroid with a district, a region and
   coordinates inside India, which is the contract the doctor profile's
   derived-position write depends on.
3. No seeded row is a malformed PIN or an out-of-range coordinate, so the table's
   own check constraints are not merely decorative.
4. Replaying the migration's own generated statement against a seeded table
   changes nothing, so re-seeding never doubles or overwrites a row.

Requires the native PostgreSQL; skips cleanly when unreachable.
"""

from __future__ import annotations

import asyncio
import csv
import gzip
import hashlib
import importlib.util
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = REPO_ROOT / "apps" / "backend" / "alembic" / "versions"
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"
SEED_FILE = VERSIONS_DIR / "pin_centroids.csv.gz"
REVISION_FILE = VERSIONS_DIR / "2022b1062d5e_v8_16__pin_centroid_table_and_seed.py"

#: The revision immediately before v8.16 - the pre-PIN-centroid state.
PARENT_REVISION = "c4e1a97b2d30"

#: The SHA-256 ``pin_centroids.SOURCE.md`` publishes for the seed file. Asserting
#: it here turns ADR-0003's "a migration is immutable" from a doc claim into a
#: machine check: an edited seed file fails the suite instead of quietly seeding
#: a different dataset than the one on record.
SEED_SHA256 = "e2ebf094065942c43abc4011945d7cc0a02c48e0dd3d4341019bfa5284a1b561"

#: The number of PIN rows the committed seed file holds. Pinned rather than read
#: at test time so that regenerating the seed cannot silently change what the
#: migration delivers; ``test_seed_file_is_the_recorded_dataset`` cross-checks
#: the file against it, so a deliberate refresh updates one number in two places.
SEEDED_PIN_COUNT = 19_258

#: A real, heavily-served PIN whose centroid every derivation must land in
#: West Singhbhum, Jharkhand. Chosen because its office cluster contains a
#: coordinate upstream places in Puglia, Italy, so this is the row that proves
#: the median derivation works where an arithmetic mean does not: a mean puts
#: the PIN in Madhya Pradesh.
REFERENCE_PIN = "833103"
REFERENCE_CENTROID = {
    "office_name": "Arahasa BO",
    "district": "WEST SINGHBHUM",
    "region": "DivReportingCircle",
    "latitude": Decimal("22.546127"),
    "longitude": Decimal("85.455600"),
}


def _revision_module() -> ModuleType:
    """Import the v8.16 revision by path, to reuse its real statement generator.

    The revision is not an importable package member (alembic loads it by path),
    so the test loads it the same way rather than restating the INSERT shape.
    """
    spec = importlib.util.spec_from_file_location("pin_centroid_revision", REVISION_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migration_state(database_url: str) -> Iterator[None]:
    """Put the DB at the pre-v8.16 revision for the module; restore base after."""
    config = _alembic_config(database_url)
    command.upgrade(config, PARENT_REVISION)
    yield
    command.downgrade(config, "base")


async def _run(database_url: str, sql: str) -> list[dict[str, object]]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(sql))
            return [dict(row) for row in result.mappings().all()]
    finally:
        await engine.dispose()


async def _exec(database_url: str, sql: str) -> None:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(sql))
    finally:
        await engine.dispose()


def _seed_file_rows() -> list[dict[str, str]]:
    with gzip.open(SEED_FILE, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_seed_file_is_the_recorded_dataset() -> None:
    """The committed seed file is the dataset the migration promises to insert.

    A pure-file assertion (no database needed): the recorded hash, the row count,
    the column set and the sort order the SQL generation depends on are all part
    of the contract, so a truncated, edited or re-ordered seed file fails here
    rather than half-seeding a database.
    """
    digest = hashlib.sha256(SEED_FILE.read_bytes()).hexdigest()
    assert digest == SEED_SHA256, (
        f"seed file hash {digest} does not match the {SEED_SHA256} recorded in "
        "pin_centroids.SOURCE.md; a refresh is a new seed file plus a new "
        "migration, never an edit to the file this migration reads (ADR-0003)"
    )

    rows = _seed_file_rows()

    assert len(rows) == SEEDED_PIN_COUNT, (
        f"seed file holds {len(rows)} rows, the recorded contract is {SEEDED_PIN_COUNT}; "
        "a refresh is a new seed file plus a new migration, never an edit to this one"
    )
    assert list(rows[0].keys()) == [
        "pin",
        "office_name",
        "district",
        "region",
        "latitude",
        "longitude",
    ]
    pins = [row["pin"] for row in rows]
    assert pins == sorted(pins), "seed rows must stay sorted by pin so the generated SQL is stable"
    assert len(set(pins)) == len(pins), "the seed file must not carry a duplicate pin"


def test_bulk_seed_writes_every_row_of_the_seed_file(
    database_url: str, reachable_db: None, migration_state: None
) -> None:
    """Every seeded PIN row arrives exactly once - the bulk path, not a subset.

    The count is asserted against the seed file, so a silently dropped batch
    (a bad escape, a truncated read) fails loudly instead of leaving a database
    that resolves only part of India.
    """
    command.upgrade(_alembic_config(database_url), "head")

    rows = asyncio.run(
        _run(
            database_url,
            "SELECT count(*) AS n, count(DISTINCT pin) AS distinct_pins "
            "FROM partner.partner_pin_centroids",
        )
    )

    assert rows == [{"n": SEEDED_PIN_COUNT, "distinct_pins": SEEDED_PIN_COUNT}]

    # The table's own guards hold across the whole seed: no malformed PIN and no
    # coordinate outside the world, so the CHECK constraints are load-bearing.
    malformed = asyncio.run(
        _run(
            database_url,
            "SELECT count(*) AS n FROM partner.partner_pin_centroids "
            "WHERE pin !~ '^[0-9]{6}$' "
            "OR latitude NOT BETWEEN -90 AND 90 "
            "OR longitude NOT BETWEEN -180 AND 180",
        )
    )
    assert malformed == [{"n": 0}]

    # Nothing partial: the read-only confirmation columns the doctor profile
    # shows back are never empty on a seeded row.
    blank_text = asyncio.run(
        _run(
            database_url,
            "SELECT count(*) AS n FROM partner.partner_pin_centroids "
            "WHERE office_name = '' OR district = '' OR region = ''",
        )
    )
    assert blank_text == [{"n": 0}]

    command.downgrade(_alembic_config(database_url), PARENT_REVISION)


def test_a_seeded_pin_resolves_to_its_own_district(
    database_url: str, reachable_db: None, migration_state: None
) -> None:
    """A real PIN resolves to a real centroid - the lookup the write depends on.

    #603 resolves the PIN a doctor typed and #609 writes the derived position, so
    the contract is a single row keyed by the PIN, carrying a district, a region
    and coordinates inside India. West Singhbhum is the row that proves the
    median derivation: its office cluster holds a coordinate in Italy, and a
    mean derivation put this PIN in Madhya Pradesh.
    """
    command.upgrade(_alembic_config(database_url), "head")

    rows = asyncio.run(
        _run(
            database_url,
            "SELECT office_name, district, region, latitude, longitude "
            f"FROM partner.partner_pin_centroids WHERE pin = '{REFERENCE_PIN}'",
        )
    )

    assert len(rows) == 1, f"{REFERENCE_PIN} must resolve to exactly one centroid"
    assert rows[0] == REFERENCE_CENTROID
    # The region is stored as the source publishes it. West Singhbhum is a
    # single-region circle upstream, so the value is the placeholder string and
    # not a fabricated region name.

    # A PIN the source never listed does not resolve - the designed failure mode
    # is an honest "no", never a default or nearest-neighbour stand-in.
    absent = asyncio.run(
        _run(
            database_url,
            "SELECT count(*) AS n FROM partner.partner_pin_centroids WHERE pin = '000000'",
        )
    )
    assert absent == [{"n": 0}]

    command.downgrade(_alembic_config(database_url), PARENT_REVISION)


def test_replaying_the_generated_seed_statement_is_a_no_op(
    database_url: str, reachable_db: None, migration_state: None
) -> None:
    """The migration's own ``ON CONFLICT (pin) DO NOTHING`` guard makes a re-run inert.

    The statement is generated by the revision's own ``_insert_statement``, loaded
    by path, so this exercises the real generation path and the real guard rather
    than a hand-written lookalike. Replaying it against a seeded table must add no
    row and overwrite no row: the first writer wins. Without the guard a re-run
    would either fail on the primary key or silently replace the data a doctor may
    already have a saved position derived from.
    """
    command.upgrade(_alembic_config(database_url), "head")

    before = asyncio.run(
        _run(
            database_url,
            "SELECT count(*) AS n FROM partner.partner_pin_centroids",
        )
    )

    revision = _revision_module()
    seeded = {row["pin"]: row for row in _seed_file_rows()}
    reference_row = tuple(seeded[REFERENCE_PIN][column] for column in revision.SEED_COLUMNS)
    replayed = revision._insert_statement((reference_row,))
    assert "ON CONFLICT (pin) DO NOTHING" in replayed, "the guard is what this test proves"
    assert "REWRITTEN" not in replayed, "the replay must carry the seed's own values, not new ones"

    asyncio.run(_exec(database_url, replayed))

    after = asyncio.run(
        _run(
            database_url,
            "SELECT count(*) AS n FROM partner.partner_pin_centroids",
        )
    )
    survivor = asyncio.run(
        _run(
            database_url,
            "SELECT office_name, district, region, latitude, longitude "
            f"FROM partner.partner_pin_centroids WHERE pin = '{REFERENCE_PIN}'",
        )
    )

    assert before == [{"n": SEEDED_PIN_COUNT}]
    assert after == [{"n": SEEDED_PIN_COUNT}]
    assert survivor == [REFERENCE_CENTROID], "the conflict guard must not overwrite a seeded row"

    command.downgrade(_alembic_config(database_url), PARENT_REVISION)


def test_downgrade_removes_the_seeded_rows_and_the_table(
    database_url: str, reachable_db: None, migration_state: None
) -> None:
    """The downgrade is reversible: the rows and the table go together.

    The seed is derived data, so a downgrade drops the table rather than trying
    to preserve rows nothing else references. This is the half of the round trip
    the version-table assertion in ``test_migrations.py`` cannot see.
    """
    command.upgrade(_alembic_config(database_url), "head")

    seeded = asyncio.run(
        _run(database_url, "SELECT count(*) AS n FROM partner.partner_pin_centroids")
    )
    assert seeded == [{"n": SEEDED_PIN_COUNT}]

    command.downgrade(_alembic_config(database_url), PARENT_REVISION)

    present = asyncio.run(
        _run(
            database_url,
            "SELECT EXISTS ("
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'partner' AND table_name = 'partner_pin_centroids'"
            ") AS exists",
        )
    )
    assert present == [{"exists": False}]
