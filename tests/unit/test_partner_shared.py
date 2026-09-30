"""PHASE-6: shared internal helpers of the partner module (ticket #606).

``shared.py`` is a grab-bag of profile-loading and registration race-retry
helpers, so it has no single subject to name. It is pinned here because #606
added ``representative_specialty``, which is the only place the three
single-valued specialty readers agree on what a multi-valued selection projects
to, and which is reached from a live database row on every directory and profile
read. Its input is whatever asyncpg decoded off a JSONB column, so the
malformed-row behaviour is the part worth pinning rather than the happy path.
"""

from __future__ import annotations

import pytest

from modules.partner.shared import representative_specialty


def test_projects_the_first_member_of_a_selection() -> None:
    assert representative_specialty(["General Physician", "Pediatrician"]) == "General Physician"


def test_projects_the_doctor_own_order_not_an_arbitrary_one() -> None:
    """Order is the selection's own, so the value is the first DECLARED specialty.

    A reverse-alphabetical or sorted projection would still satisfy every
    "returns some member" test; only a doctor who declares "Pediatrician" first
    and searches on that pin distinguishes this.
    """
    assert representative_specialty(["Pediatrician", "General Physician"]) == "Pediatrician"


@pytest.mark.parametrize(
    "empty_selection",
    [[], (), None],
    ids=["empty-list", "empty-tuple", "null"],
)
def test_an_absent_specialty_projects_to_none(empty_selection: object) -> None:
    """NULL is how a lab or chemist directory entry says "carries no specialty"."""
    assert representative_specialty(empty_selection) is None


@pytest.mark.parametrize(
    "malformed",
    [
        "General Physician",
        b"General Physician",
        42,
        {"0": "General Physician"},
        [],
        [None],
        [7],
        [""],
        [None, ""],
        [{"name": "General Physician"}],
    ],
    ids=[
        "bare-string",
        "bytes",
        "bare-int",
        "json-object",
        "empty-list",
        "null-member",
        "int-member",
        "empty-string-member",
        "unusable-members-only",
        "object-member",
    ],
)
def test_a_malformed_row_reads_as_no_specialty(malformed: object) -> None:
    """A malformed row must never leak a Python ``repr`` into a response field.

    Nothing writes these shapes - the column is written as a JSONB array or left
    NULL - but a hand-repaired row can hold one, and the alternative to projecting
    ``None`` is rendering ``"{'0': 'General...'}"`` into an API response that a
    client will display to a patient. Degraded, never leaked.
    """
    assert representative_specialty(malformed) is None


@pytest.mark.parametrize(
    "prefixed",
    [["", "Pediatrician"], [None, "Pediatrician"], [7, "Pediatrician"]],
    ids=["empty-string-first", "null-member-first", "int-member-first"],
)
def test_skips_past_unusable_members_to_the_first_real_one(prefixed: list[object]) -> None:
    """A junk member must not swallow the doctor's first real specialty.

    Projecting ``None`` for a row that declares a usable value would hide a
    doctor from their own specialty search, which is worse than the junk it
    skips past.
    """
    assert representative_specialty(prefixed) == "Pediatrician"
