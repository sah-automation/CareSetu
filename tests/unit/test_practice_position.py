"""Practice-position pure decisions (ticket #603, MOD-002 FEAT-004 REQ-008): PIN
resolution, the display address string, and the peri-urban belt.

The three decisions in ``modules.partner.domain.practice_position`` are pure -
no database, no engine, no facade - so this suite pins all of them without one,
mirroring the credential-validity pure-tier suite (the eligibility decision
mirrored by SQL predicates integration-tested elsewhere) and the credential
pre-filter suite.

The queries that will consume these answers are not tested here: the centroid
lookup and the directory-entry refresh against real Postgres belong to the
integration suites (#620), and the search clamp's belt comparison is
``search_directory``'s own integration coverage. What is pinned here is the
arithmetic and the refusals, at the boundary the acceptance criteria name.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import math
import textwrap
from pathlib import Path

import pytest

from modules.partner.directory_facade import PERI_URBAN_RADIUS_KM, _haversine_km
from modules.partner.domain import practice_position
from modules.partner.domain.practice_position import (
    EARTH_MEAN_RADIUS_KM,
    AddressParts,
    PeriUrbanBeltDecision,
    PinCentroid,
    PinResolution,
    PinResolutionReason,
    PracticePosition,
    evaluate_peri_urban_belt,
    format_display_address,
    great_circle_km,
    resolve_pin_code,
)
from modules.partner.facade import (
    DALTONGANJ_LATITUDE,
    DALTONGANJ_LONGITUDE,
)

CENTRE = PracticePosition(latitude=DALTONGANJ_LATITUDE, longitude=DALTONGANJ_LONGITUDE)

# A real Daltonganj PIN code, and a real centroid for it. The numbers are the
# test's own; this ticket must not know what the centroid table is called or what
# it was seeded with.
_KNOWN_PIN = "827101"
_KNOWN_CENTROID = PinCentroid(pin_code=_KNOWN_PIN, latitude=24.0412, longitude=84.0718)


# --- resolve_pin_code: a known PIN resolves to a centroid ---


def test_known_pin_resolves_to_the_centroids_own_coordinates() -> None:
    result = resolve_pin_code(_KNOWN_PIN, _KNOWN_CENTROID)

    assert result.reason is PinResolutionReason.RESOLVED
    assert result.resolved is True
    assert result.position == PracticePosition(latitude=24.0412, longitude=84.0718)


def test_a_resolved_position_is_the_centroid_point_and_never_a_variant_of_it() -> None:
    """No rounding, snapping, quantisation or re-derivation of the centroid.

    A silently moved position is the failure this whole seam exists to prevent,
    so the coordinates come back exactly as the centroid carries them.
    """
    result = resolve_pin_code(_KNOWN_PIN, _KNOWN_CENTROID)

    assert result.position is not None
    assert result.position.latitude == _KNOWN_CENTROID.latitude
    assert result.position.longitude == _KNOWN_CENTROID.longitude


def test_surrounding_whitespace_on_the_declared_pin_is_stripped() -> None:
    result = resolve_pin_code(f"  {_KNOWN_PIN}\n", _KNOWN_CENTROID)

    assert result.resolved is True
    assert result.position == PracticePosition(latitude=24.0412, longitude=84.0718)


# --- resolve_pin_code: an unknown but well-formed PIN does not resolve ---


def test_well_formed_pin_absent_from_the_dataset_does_not_resolve() -> None:
    result = resolve_pin_code("999999", None)

    assert result.reason is PinResolutionReason.UNKNOWN
    assert result.resolved is False
    assert result.position is None


def test_a_centroid_keyed_to_a_different_pin_never_resolves() -> None:
    """The declared code and the centroid's key must agree.

    Without this check a lookup that returned the wrong row would place a doctor
    in another neighbourhood - the exact class of bug the no-fallback rule exists
    to prevent, so it is refused rather than used.
    """
    result = resolve_pin_code("999999", _KNOWN_CENTROID)

    assert result.reason is PinResolutionReason.UNKNOWN
    assert result.position is None


def test_a_centroid_the_caller_passed_as_none_and_an_absent_pin_are_indistinguishable() -> None:
    """A missing centroid and a well-formed-but-absent PIN are one answer.

    "No partial resolution, no coarse fallback, no default position" is a property
    of the answer *type*, not only of the branch that produces it: if the caller
    could tell the two apart, the next reader would be tempted to handle the
    distinguishable one differently.
    """
    null_centroid = resolve_pin_code(_KNOWN_PIN, None)
    absent_pin = resolve_pin_code("999999", None)

    assert null_centroid == absent_pin
    assert null_centroid.reason is PinResolutionReason.UNKNOWN


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (91.0, 84.07),
        (-90.5, 84.07),
        (24.04, 180.5),
        (24.04, -180.5),
        (math.inf, 84.07),
        (math.nan, 84.07),
        (24.04, -math.inf),
    ],
)
def test_a_centroid_with_unusable_coordinates_does_not_resolve(
    latitude: float, longitude: float
) -> None:
    result = resolve_pin_code(_KNOWN_PIN, PinCentroid(_KNOWN_PIN, latitude, longitude))

    assert result.reason is PinResolutionReason.UNKNOWN
    assert result.position is None


# --- resolve_pin_code: a malformed PIN does not resolve ---


@pytest.mark.parametrize(
    "malformed",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace-only"),
        pytest.param("82710", id="five-digits"),
        pytest.param("8271011", id="seven-digits"),
        pytest.param("82710A", id="letter-in-place-of-a-digit"),
        pytest.param("82 710", id="embedded-space"),
        pytest.param("82-7101", id="separator"),
        pytest.param("8.27101", id="decimal-separator"),
        pytest.param("٨٢٧١٠١", id="arabic-indic-digits"),
        pytest.param("८२७१०१", id="devanagari-digits"),
    ],
)
def test_a_malformed_pin_does_not_resolve(malformed: str) -> None:
    result = resolve_pin_code(malformed, _KNOWN_CENTROID)

    assert result.reason is PinResolutionReason.MALFORMED
    assert result.resolved is False
    assert result.position is None


def test_malformed_means_both_a_length_failure_and_a_character_class_failure() -> None:
    """The contract is length AND character class, and the caller cannot tell.

    ``#609``'s client renders a field-level error under the PIN input from this
    reason, so the suite pins that a short code and a letter-bearing code of the
    right length are refused identically - the message must not have to guess
    which rule was broken.
    """
    too_short = resolve_pin_code("82710", _KNOWN_CENTROID)
    wrong_class = resolve_pin_code("8271A1", _KNOWN_CENTROID)

    assert too_short.reason is wrong_class.reason is PinResolutionReason.MALFORMED
    assert too_short == wrong_class


def test_malformed_is_checked_before_the_centroid_is_consulted() -> None:
    """A malformed code refuses even when a centroid is offered for it.

    The format is the doctor's input; the centroid is the platform's dataset.
    Answering "resolved" for a value that is not a PIN code would let a caller
    mistake a formatting bug for a placement.
    """
    result = resolve_pin_code("not-a-pin", PinCentroid("not-a-pin", 24.0, 84.0))

    assert result.reason is PinResolutionReason.MALFORMED
    assert result.position is None


# --- resolve_pin_code: the answer type carries no wrong position ---


def test_the_answer_is_frozen_so_a_resolved_point_cannot_be_edited_in_place() -> None:
    result: PinResolution = resolve_pin_code(_KNOWN_PIN, _KNOWN_CENTROID)

    assert dataclasses.is_dataclass(result)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.position = PracticePosition(latitude=0.0, longitude=0.0)  # type: ignore[misc]


def test_every_unresolved_answer_has_a_null_position() -> None:
    """A non-resolved answer has nowhere to put a guessed point.

    The structural half of the no-fallback rule: across every refusal branch the
    position is ``None``, and ``resolved`` is derived from it rather than stored,
    so the two can never disagree.
    """
    refusals = [
        resolve_pin_code("", _KNOWN_CENTROID),
        resolve_pin_code("999999", None),
        resolve_pin_code(_KNOWN_PIN, PinCentroid(_KNOWN_PIN, 999.0, 84.0)),
    ]

    assert all(answer.position is None for answer in refusals)
    assert all(answer.resolved is False for answer in refusals)


def test_the_answer_type_refuses_to_claim_a_position_it_did_not_resolve() -> None:
    """The invariant is enforced at construction, not only by convention.

    A future edit that bolted a fallback position onto a refusal would construct
    an answer that says both "unknown" and "here is where they are", and
    ``resolved`` would disagree with ``reason``. That has to be impossible to
    build, not merely absent today.
    """
    with pytest.raises(ValueError, match="if and only if it resolved"):
        PinResolution(reason=PinResolutionReason.UNKNOWN, position=PracticePosition(24.0, 84.0))


def test_the_answer_type_refuses_to_resolve_without_a_position() -> None:
    with pytest.raises(ValueError, match="if and only if it resolved"):
        PinResolution(reason=PinResolutionReason.RESOLVED)


@pytest.mark.parametrize(
    "reason",
    [PinResolutionReason.MALFORMED, PinResolutionReason.UNKNOWN],
)
def test_every_refusal_reason_is_constructible_bare(reason: PinResolutionReason) -> None:
    """Both refusals build the same way, so neither can be special-cased later."""
    answer = PinResolution(reason=reason)

    assert answer.position is None
    assert answer.resolved is False


# --- format_display_address: the defined order ---


def test_all_parts_assemble_in_the_defined_order() -> None:
    parts = AddressParts(
        address_line="12, Nehru Road",
        landmark="Near the water tank",
        locality="Sadar",
        city="Daltonganj",
        pin_code=_KNOWN_PIN,
    )

    assert (
        format_display_address(parts)
        == "12, Nehru Road, Near the water tank, Sadar, Daltonganj, 827101"
    )


def test_the_landmark_is_the_second_part_and_not_appended_at_the_end() -> None:
    """Order is line, landmark, locality, city, PIN - fixed here, once.

    The retained display column, the write path and the public renderer all read
    this one string, so the order is a contract between them. Pinning the
    landmark's position stops a later "tidier" reorder from silently changing
    what a column already written means.
    """
    parts = AddressParts(
        address_line="12 Nehru Road",
        landmark="Near the water tank",
        locality="Sadar",
        city="Daltonganj",
        pin_code=_KNOWN_PIN,
    )

    assert format_display_address(parts).split(", ") == [
        "12 Nehru Road",
        "Near the water tank",
        "Sadar",
        "Daltonganj",
        _KNOWN_PIN,
    ]


def test_a_bare_zip_separator_in_a_part_does_not_confuse_the_reader() -> None:
    """A part may itself contain a comma; the assembly still reads correctly.

    The separator only ever goes *between* present parts, so an address line
    written as "Shop 4, Nehru Road" keeps its own comma.
    """
    parts = AddressParts(address_line="Shop 4, Nehru Road", city="Daltonganj")

    assert format_display_address(parts) == "Shop 4, Nehru Road, Daltonganj"


# --- format_display_address: an absent landmark leaves no stray separator ---


def test_an_absent_landmark_leaves_no_stray_doubled_or_leading_separator() -> None:
    parts = AddressParts(
        address_line="12, Nehru Road",
        landmark=None,
        locality="Sadar",
        city="Daltonganj",
        pin_code=_KNOWN_PIN,
    )

    result = format_display_address(parts)

    assert result == "12, Nehru Road, Sadar, Daltonganj, 827101"
    assert ", ," not in result
    assert ",," not in result
    assert not result.startswith(", ")
    assert not result.endswith(", ")


def test_a_whitespace_only_landmark_is_treated_as_absent() -> None:
    """Blank and absent are the same thing to a reader of an address.

    Emitting a blank part would fill the retained column with punctuation, which
    is what this rule exists to prevent.
    """
    parts = AddressParts(
        address_line="12, Nehru Road",
        landmark="   \t ",
        locality="Sadar",
        city="Daltonganj",
        pin_code=_KNOWN_PIN,
    )

    assert format_display_address(parts) == "12, Nehru Road, Sadar, Daltonganj, 827101"


@pytest.mark.parametrize("blank", ["", "   ", "\n\t", None])
def test_every_blank_part_is_treated_as_absent(blank: str | None) -> None:
    parts = AddressParts(
        address_line=blank,
        landmark=blank,
        locality=blank,
        city=blank,
        pin_code=blank,
    )

    assert format_display_address(parts) == ""


def test_only_the_address_line_present_produces_no_trailing_separator() -> None:
    result = format_display_address(AddressParts(address_line="12, Nehru Road"))

    assert result == "12, Nehru Road"
    assert not result.endswith(",")


def test_a_missing_first_part_leaves_no_leading_separator() -> None:
    """A doctor who has only typed a landmark and a city gets a readable string.

    The interior and trailing gaps are as real as the leading one: the separator
    is inserted between two present parts and nowhere else.
    """
    result = format_display_address(AddressParts(landmark="Near the water tank", city="Daltonganj"))

    assert result == "Near the water tank, Daltonganj"
    assert not result.startswith(", ")


# --- format_display_address: safe on an unfinished address ---


def test_an_all_absent_address_returns_the_empty_string_rather_than_raising() -> None:
    """Registration still writes the pre-structured value until the parts exist.

    A doctor who has not finished their address must not get a 500 out of a
    formatting function, so the empty case is a pinned answer and not an
    exception.
    """
    assert format_display_address(AddressParts()) == ""


def test_the_retained_display_column_pre_structured_value_is_a_valid_input_shape() -> None:
    """A registration-era free-text address is one part, and reads back verbatim.

    The pre-structured value registration writes today is the city name typed at
    sign-up; passing it as the only part must not reshape it.
    """
    assert format_display_address(AddressParts(city="Daltonganj")) == "Daltonganj"


def test_parts_are_trimmed_but_never_rewritten() -> None:
    parts = AddressParts(
        address_line="  12, Nehru Road  ",
        landmark="  Near the water tank",
        locality=None,
        city=" Daltonganj ",
        pin_code=f" {_KNOWN_PIN} ",
    )

    expected = f"12, Nehru Road, Near the water tank, Daltonganj, {_KNOWN_PIN}"

    assert format_display_address(parts) == expected


# --- great_circle_km ---


def test_the_distance_from_a_point_to_itself_is_zero() -> None:
    assert great_circle_km(CENTRE, CENTRE) == 0.0


def test_the_distance_is_symmetric() -> None:
    east = PracticePosition(latitude=CENTRE.latitude, longitude=CENTRE.longitude + 0.1)

    assert great_circle_km(CENTRE, east) == great_circle_km(east, CENTRE)


def test_one_degree_of_longitude_at_the_equator_is_the_textbook_arc() -> None:
    """An independent check on the formula, not a restatement of it.

    One degree of a great circle is ``2 * pi * R / 360`` = 111.19 km at the mean
    Earth radius, measured on the equator where a degree of longitude is a degree
    of arc. If the pure calculation drifts from the haversine the SQL expression
    mirrors, this is the number that moves.
    """
    equator = PracticePosition(latitude=0.0, longitude=0.0)
    one_degree_east = PracticePosition(latitude=0.0, longitude=1.0)

    distance = great_circle_km(equator, one_degree_east)

    assert distance == pytest.approx(111.19, abs=0.01)


def test_near_antipodal_points_do_not_raise_on_floating_point_rounding() -> None:
    """The ``a`` term can exceed 1 by a rounding hair; ``sqrt`` must not blow up.

    Two Indian PIN centroids are never antipodal, but the calculation is total
    over its input type and a crash on a legal pair of coordinates would be a
    latent 500 in whatever future caller passes one.
    """
    north_pole = PracticePosition(latitude=90.0, longitude=0.0)
    south_pole = PracticePosition(latitude=-90.0, longitude=0.0)
    quarter_turn = PracticePosition(latitude=0.0, longitude=90.0)

    antipodal = great_circle_km(north_pole, south_pole)
    quarter = great_circle_km(PracticePosition(latitude=0.0, longitude=0.0), quarter_turn)

    assert antipodal == pytest.approx(math.pi * EARTH_MEAN_RADIUS_KM, rel=1e-9)
    assert quarter == pytest.approx(math.pi * EARTH_MEAN_RADIUS_KM / 2.0, rel=1e-9)


# --- evaluate_peri_urban_belt: the boundary is a parameter ---


def test_the_belt_radius_is_a_parameter_and_not_a_constant_of_this_decision() -> None:
    """The acceptance criterion, pinned against the function's own signature.

    A boundary that exists only inside a query cannot be unit-tested at the
    boundary and cannot be varied by a caller, which is what the parameter exists
    to prevent. The radius is keyword-only with no default, so there is no place
    for a module constant to hide and no call that can omit it - the module names
    ``PERI_URBAN_RADIUS_KM`` in prose so the reader knows what to pass, and holds
    no value of its own.
    """
    radius_parameter = inspect.signature(evaluate_peri_urban_belt).parameters["radius_km"]

    assert radius_parameter.default is inspect.Parameter.empty
    assert radius_parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_the_same_position_is_inside_one_radius_and_outside_another() -> None:
    """The radius the caller passes is the only thing that decides the answer."""
    east = PracticePosition(latitude=CENTRE.latitude, longitude=CENTRE.longitude + 0.10)

    inside = evaluate_peri_urban_belt(east, centre=CENTRE, radius_km=25.0)
    outside = evaluate_peri_urban_belt(east, centre=CENTRE, radius_km=5.0)

    assert inside.within_belt is True
    assert outside.within_belt is False


def test_a_position_exactly_at_the_radius_is_inside() -> None:
    """``<=``, matching the search clamp's own comparison.

    The pure decision and ``search_directory``'s ``distance_km <=
    PERI_URBAN_RADIUS_KM`` must be the same comparison, or the belt has two edges
    and a doctor can be warned about a listing that then behaves the other way.
    """
    east = PracticePosition(latitude=CENTRE.latitude, longitude=CENTRE.longitude + 0.10)
    exactly_at_radius = great_circle_km(CENTRE, east)

    at_radius = evaluate_peri_urban_belt(east, centre=CENTRE, radius_km=exactly_at_radius)
    just_inside = evaluate_peri_urban_belt(
        east, centre=CENTRE, radius_km=math.nextafter(exactly_at_radius, math.inf)
    )

    assert at_radius.within_belt is True
    assert at_radius.distance_km == exactly_at_radius
    assert just_inside.within_belt is True


def test_a_position_just_past_the_radius_is_outside() -> None:
    east = PracticePosition(latitude=CENTRE.latitude, longitude=CENTRE.longitude + 0.10)
    exactly_at_radius = great_circle_km(CENTRE, east)

    just_outside = evaluate_peri_urban_belt(
        east, centre=CENTRE, radius_km=math.nextafter(exactly_at_radius, 0.0)
    )

    assert just_outside.within_belt is False
    assert just_outside.distance_km == exactly_at_radius


def test_the_launch_belt_radius_places_a_neighbouring_town_inside_and_a_far_one_outside() -> None:
    """The decision agrees with the constant the search clamp uses.

    ``radius_km`` is passed from ``PERI_URBAN_RADIUS_KM``, so the value under
    test is the value the search clamp compares against, not a copy of it.
    """
    neighbouring = PracticePosition(latitude=CENTRE.latitude, longitude=CENTRE.longitude + 0.20)
    distant = PracticePosition(latitude=CENTRE.latitude, longitude=CENTRE.longitude + 0.50)

    near_decision = evaluate_peri_urban_belt(
        neighbouring, centre=CENTRE, radius_km=PERI_URBAN_RADIUS_KM
    )
    far_decision = evaluate_peri_urban_belt(distant, centre=CENTRE, radius_km=PERI_URBAN_RADIUS_KM)

    assert near_decision.within_belt is True
    assert far_decision.within_belt is False
    assert far_decision.distance_km > PERI_URBAN_RADIUS_KM


def test_a_position_at_the_belt_centre_is_inside_at_zero_distance() -> None:
    decision = evaluate_peri_urban_belt(CENTRE, centre=CENTRE, radius_km=PERI_URBAN_RADIUS_KM)

    assert decision == PeriUrbanBeltDecision(within_belt=True, distance_km=0.0)


# --- evaluate_peri_urban_belt: outside the belt is a warning, not a refusal ---


def test_an_outside_the_belt_answer_still_carries_a_measurable_distance() -> None:
    """The answer a save outside the belt succeeds *with*.

    A warning that cannot say how far out the practice sits is a warning the
    doctor cannot act on, and this dataclass is what the address-section write
    turns into one.
    """
    distant = PracticePosition(latitude=CENTRE.latitude, longitude=CENTRE.longitude + 0.50)

    decision = evaluate_peri_urban_belt(distant, centre=CENTRE, radius_km=PERI_URBAN_RADIUS_KM)

    assert decision.within_belt is False
    assert decision.distance_km > PERI_URBAN_RADIUS_KM
    assert math.isfinite(decision.distance_km)


def test_the_answer_is_frozen_and_reads_as_the_whole_decision() -> None:
    decision = evaluate_peri_urban_belt(CENTRE, centre=CENTRE, radius_km=25.0)

    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.within_belt = False  # type: ignore[misc]


@pytest.mark.parametrize("radius_km", [0.0, -1.0, -0.001, math.inf, math.nan])
def test_a_non_positive_or_non_finite_radius_is_a_loud_programming_error(radius_km: float) -> None:
    """Bad caller configuration raises; it never returns a distance comparing wrong."""
    with pytest.raises(ValueError, match="radius_km"):
        evaluate_peri_urban_belt(CENTRE, centre=CENTRE, radius_km=radius_km)


@pytest.mark.parametrize(
    "centre",
    [
        PracticePosition(latitude=91.0, longitude=84.07),
        PracticePosition(latitude=24.04, longitude=-180.5),
        PracticePosition(latitude=math.nan, longitude=84.07),
    ],
)
def test_an_unusable_belt_centre_is_a_loud_programming_error(centre: PracticePosition) -> None:
    with pytest.raises(ValueError, match="belt centre"):
        evaluate_peri_urban_belt(CENTRE, centre=centre, radius_km=25.0)


# --- the pure decisions stay pure, and stay numerically consistent with the SQL ---


def test_the_module_imports_nothing_but_the_standard_library() -> None:
    """Acceptance criterion 3, pinned mechanically rather than by convention.

    A decision that reaches for a connection cannot be re-derived identically by
    two readers, and a decision with an engine parameter is not a decision. The
    check is an allowlist rather than a denylist, so a new import of anything -
    ``sqlalchemy``, a facade, a schema object, a relative module - fails it.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(practice_position)))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(("." * (node.level or 0)) + (node.module or ""))

    assert imported <= {"math", "string", "dataclasses", "enum", "__future__"}


def test_the_search_clamp_and_this_calculation_share_one_earth_radius() -> None:
    """The two distance implementations must not drift apart.

    The search clamp and the nearest-first sort stay in SQL for the cost floor,
    and this calculation exists so a *decision* about distance can be taken
    without a connection. Two radii would mean a doctor warned by one and
    clamped by the other. ``_haversine_km`` is private to the sub-facade, which
    is why this one test reaches out of the pure tier at all; it asserts the
    numeric agreement that a docstring cannot enforce.
    """
    compiled = str(
        _haversine_km(DALTONGANJ_LATITUDE, DALTONGANJ_LONGITUDE).compile(
            compile_kwargs={"literal_binds": True}
        )
    )

    assert 2.0 * EARTH_MEAN_RADIUS_KM == 12742.0
    assert "12742.0" in compiled


def test_the_pure_calculation_is_the_same_haversine_the_sql_expression_builds() -> None:
    """The formula's terms are pinned, so a rewrite has to be a deliberate diff."""
    compiled = str(
        _haversine_km(DALTONGANJ_LATITUDE, DALTONGANJ_LONGITUDE).compile(
            compile_kwargs={"literal_binds": True}
        )
    )

    for term in ("radians(", "asin(sqrt(", "cos(", "power(sin(", "CAST(2 AS NUMERIC)"):
        assert term in compiled, f"the SQL expression no longer builds {term}"


def test_the_decision_module_lives_in_the_partner_domain_layer() -> None:
    """A pure decision about a partner-schema concept belongs in ``domain/``.

    The module-boundary hook is the gate; this is the test that says what it is
    protecting, so a future move to the facade layer is a visible decision.
    """
    module_path = Path(inspect.getfile(practice_position)).resolve()

    assert module_path.parent.name == "domain"
    assert module_path.parent.parent.name == "partner"
