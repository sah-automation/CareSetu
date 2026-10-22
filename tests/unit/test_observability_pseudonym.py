"""B6 #723: the pseudonymous actor key (pure, no DB, no settings).

Attribution may group spend per patient and per doctor, but the observability
schema must never name one. These tests pin the three properties the aggregation
depends on: the key is stable (a consume-time key joins a rollup-time key), it is
domain-separated (a patient and a doctor sharing a reference do not share a key),
and it is a fixed-width digest that fits its column.

What this is NOT, and what no test here should pretend otherwise: the digest is
enumerable by someone who holds the rows, because the references are dense
database serials. ``pseudonym.py``'s module docstring says so at length. The
control being tested is that the identity COLUMN of the telemetry store is not
the identity itself.
"""

from __future__ import annotations

from modules.observability.domain.pseudonym import (
    ACTOR_KIND_DOCTOR,
    ACTOR_KIND_PATIENT,
    actor_key,
)


def test_key_is_stable_for_the_same_reference() -> None:
    assert actor_key(ACTOR_KIND_PATIENT, 7) == actor_key(ACTOR_KIND_PATIENT, 7)


def test_different_references_get_different_keys() -> None:
    assert actor_key(ACTOR_KIND_PATIENT, 7) != actor_key(ACTOR_KIND_PATIENT, 8)


def test_key_is_domain_separated_by_actor_kind() -> None:
    """Patient 7 and doctor 7 draw from different id spaces and must not collide."""
    assert actor_key(ACTOR_KIND_PATIENT, 7) != actor_key(ACTOR_KIND_DOCTOR, 7)


def test_key_is_a_fixed_width_hex_digest_that_fits_its_column() -> None:
    """The key column is ``VARCHAR(64)``, so a key can never carry anything else.

    A hex digest of fixed width is the whole COLUMN story: the row stores 64
    characters of one-way digest and nothing that varies with the reference's
    own length or spelling.
    """
    key = actor_key(ACTOR_KIND_PATIENT, 7)
    assert len(key) == 64
    assert all(character in "0123456789abcdef" for character in key)
