"""MOD-002: the practice position and display-address decisions (ticket #603).

Three pure decisions, with no schema, facade, engine or adapter import, so each
is pinned by a unit suite that needs no database. They are the executable form
of "the practice position is a PIN centroid rather than a geocode": the doctor
declares an address, the platform derives the one position every reader sees.

- :func:`resolve_pin_code` - whether a declared PIN code resolves to a position.
  The centroid is an **input**, never a lookup. The lookup that can fail belongs
  to the caller, in the database, against the bundled centroid table; this
  function only says what a missing, mismatched or malformed input *means*. A
  PIN either resolves or it does not: no coarse fallback, no default position,
  no partial answer - a silently misplaced doctor is worse than a blocked one,
  and ADR-0012's "one directory entry, one geo point" leaves a single resolved
  position as the only shape a partner can hold, so there is nowhere to fall back
  to even in principle.
- :func:`format_display_address` - the one display string every existing reader
  of the practice-address column sees, assembled from the structured parts in a
  fixed order so the column, the write path and the renderer cannot disagree.
- :func:`evaluate_peri_urban_belt` - whether a resolved position sits inside the
  peri-urban belt, with the belt radius a **parameter** and the kilometre
  arithmetic in Python.

The answers are frozen dataclasses carrying exactly what the decision produced,
following the credential-validity seam (``evaluate_eligibility``) and the
credential pre-filter (``PrefilterOutcome``): the decision lives in the domain
core, never in the router (coding-standards §4), and it is evaluable with no
connection so two readers can re-derive the same answer from the same facts.
"""

from __future__ import annotations

import math
import string
from dataclasses import dataclass
from enum import StrEnum

#: An Indian PIN code is exactly six digits, and nothing else (FEAT-004 scope
#: geography). "Malformed" therefore means **both** a length failure and a
#: character-class failure - a five-digit value, a seven-digit value, a value
#: carrying a letter, a space or a separator, and an empty value are all
#: malformed, and all indistinguishable to the caller. :func:`resolve_pin_code`
#: strips surrounding whitespace and normalises nothing else: no case folding, no
#: separator removal, no digit insertion. A PIN is what the doctor typed.
_PIN_CODE_LENGTH = 6
_PIN_CODE_DIGITS = frozenset(string.digits)

#: The mean Earth radius, in km - the single source of truth for both the pure
#: great-circle calculation here and the ``_haversine_km`` SQL expression in the
#: directory sub-facade, which imports it rather than repeating the literal. The
#: two must stay numerically consistent: a doctor this decision calls inside the
#: belt and the search clamp calls outside it (or the reverse) would be warned
#: about a listing that then behaves the other way, which is a support ticket,
#: not a rounding curiosity. It lives in the domain layer because the pure
#: calculation cannot import a facade without inverting the module layering.
EARTH_MEAN_RADIUS_KM = 6371.0

#: The separator between address parts. A comma-and-space, because the display
#: column is read in prose on a public profile card and in a doctor's own profile
#: header; a bare comma is cramped and a semicolon reads as a form, not an
#: address.
_PART_SEPARATOR = ", "


class PinResolutionReason(StrEnum):
    """Why a declared PIN code did or did not resolve (machine-readable).

    ``RESOLVED`` is the only member that carries a position. ``MALFORMED`` means
    the doctor's input can never be a PIN code, so the client corrects the field.
    ``UNKNOWN`` means the input is a well-formed PIN code that this platform
    cannot place - absent from the bundled centroid dataset, offered for a
    different PIN code, or carrying unusable coordinates. Both refusals are the
    same answer to the caller in every respect that matters (no position), and
    the client renders the same actionable message for each: fix or re-check the
    PIN.
    """

    RESOLVED = "resolved"
    MALFORMED = "malformed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PinCentroid:
    """One row of the bundled PIN centroid table, stripped of DB-mapping concerns.

    Carries only what :func:`resolve_pin_code` needs, so the decision can be
    evaluated with a plain dataclass - no SQLAlchemy row, no connection. The
    caller builds it from the row it looked up and hands it over; the lookup is
    the caller's, in the database.

    ``pin_code`` is carried deliberately: a centroid supplied for a *different*
    PIN code is not a resolution of the declared one, and a decision that ignored
    the key could attach a doctor's practice to someone else's neighbourhood.

    The coordinates are typed ``float``. A ``Numeric`` column arrives from the
    driver as a ``Decimal``, so the caller converts at its own boundary (the
    shape ``directory_facade._row_fee_paise`` already uses for an integer-paise
    column) rather than widening this domain type to every numeric type the
    driver might pick.
    """

    pin_code: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class PracticePosition:
    """One resolved point on the earth, the practice position a partner holds.

    The single geo point a directory entry carries (ADR-0012). Produced only by
    :func:`resolve_pin_code`, and consumed by :func:`evaluate_peri_urban_belt`
    and, later, by the shared directory-entry refresh.
    """

    latitude: float
    longitude: float


@dataclass(frozen=True)
class PinResolution:
    """The result of :func:`resolve_pin_code`.

    A position is present if and only if ``reason`` is ``RESOLVED``, and
    :meth:`__post_init__` refuses any answer that says otherwise - so the two
    fields cannot drift apart and ``resolved`` cannot disagree with ``reason``.
    That is the structural half of "no partial resolution, no coarse fallback, no
    default position": the answer type has nowhere to put a guessed point, so an
    edit that tried to invent one fails loudly at construction rather than
    shipping a misplaced doctor. Callers branch on the derived ``resolved``
    property and never on the coordinates.
    """

    reason: PinResolutionReason
    position: PracticePosition | None = None

    def __post_init__(self) -> None:
        if (self.reason is PinResolutionReason.RESOLVED) != (self.position is not None):
            raise ValueError(
                "a pin resolution carries a position if and only if it resolved; got "
                f"reason={self.reason.value!r}, position={self.position!r}"
            )

    @property
    def resolved(self) -> bool:
        """True only when a position was actually resolved."""
        return self.position is not None


@dataclass(frozen=True)
class AddressParts:
    """The structured practice address, as declared by the doctor.

    Every part is optional: a doctor who has not finished their address submits
    some or none of them, and registration still writes the pre-structured
    free-text value into the retained display column. Each part is ``None`` or a
    string; a whitespace-only string is treated as absent by
    :func:`format_display_address` rather than emitted, so a column can never fill
    with punctuation.
    """

    address_line: str | None = None
    landmark: str | None = None
    locality: str | None = None
    city: str | None = None
    pin_code: str | None = None


@dataclass(frozen=True)
class PeriUrbanBeltDecision:
    """The result of :func:`evaluate_peri_urban_belt`.

    ``within_belt`` is the whole decision, and ``False`` is **not** a refusal: a
    save whose resolved position falls outside the belt succeeds with a warning
    attached, so a doctor in a real but outlying town is never blocked from
    correcting their own address. The warning is this answer, surfaced by the
    address-section write, not a second decision.

    ``distance_km`` is the measured great-circle distance from the belt centre, so
    the warning can state how far out the practice sits rather than only that it
    is out.
    """

    within_belt: bool
    distance_km: float


def resolve_pin_code(pin_code: str, centroid: PinCentroid | None) -> PinResolution:
    """Decide whether a declared PIN code resolves to a practice position.

    Pure: it takes the declared code and an optional centroid the caller already
    looked up, and returns its answer. It never opens a connection, never reads a
    table and never takes an engine - the lookup that can fail is the caller's,
    in the database, and this function's job is to say what a missing, mismatched
    or malformed input means. That is what makes the decision unit-testable
    before the centroid table exists, and what keeps the failure mode honest:
    there is exactly one way to get a position out of this function, and it is a
    well-formed code with a matching, usable centroid.

    Three answers, in this order:

    - **malformed** - the declared value is not six ASCII digits. Both a length
      failure and a character-class failure, and the caller cannot tell them
      apart, so the field-level error it renders says the PIN is not a PIN code
      rather than guessing which rule was broken.
    - **unknown** - the value is a well-formed PIN code that cannot be placed:
      ``centroid`` is ``None`` (absent from the bundled dataset), is keyed to a
      different code, or carries coordinates outside the valid ranges. All three
      are the same answer, because all three mean the same thing to the doctor:
      we cannot place this practice. A centroid supplied for a different code is
      additionally a caller defect, and the caller is the only place that can see
      it - this decision refuses it rather than using it, which is why the
      mismatch cannot become a misplaced doctor.
    - **resolved** - the code is well formed, the centroid is keyed to it, and its
      coordinates are usable. The returned position is the centroid's own point,
      never a rounded, snapped or derived variant of it.

    Surrounding whitespace on the declared code is stripped and nothing else is
    normalised, because every keyboard and every form emits it. An all-whitespace
    or empty value is malformed, not unknown: it is not a PIN code.
    """
    declared = pin_code.strip()
    if len(declared) != _PIN_CODE_LENGTH or not set(declared) <= _PIN_CODE_DIGITS:
        return PinResolution(reason=PinResolutionReason.MALFORMED)
    if centroid is None or centroid.pin_code != declared:
        return PinResolution(reason=PinResolutionReason.UNKNOWN)
    if not _is_usable_coordinate(centroid.latitude, -90.0, 90.0) or not _is_usable_coordinate(
        centroid.longitude, -180.0, 180.0
    ):
        return PinResolution(reason=PinResolutionReason.UNKNOWN)
    return PinResolution(
        reason=PinResolutionReason.RESOLVED,
        position=PracticePosition(latitude=centroid.latitude, longitude=centroid.longitude),
    )


def format_display_address(parts: AddressParts) -> str:
    """Assemble the practice-address display string from the structured parts.

    The one string every existing reader of the practice-address column sees: the
    retained column, the doctor's own profile header and the public profile card
    all read the same assembled value, so the order is a contract and is fixed
    here rather than at each reader.

    **The order is address line, landmark, locality, city, PIN code**, joined with
    a comma and a space. It reads the way a patient would say the address aloud -
    where the building is, what to look for, which part of town, which city, which
    code - and it puts the most specific part first, so a truncated display still
    identifies the practice. The landmark is optional and simply drops out when
    it is absent: no doubled separator, no leading separator, no dangling
    conjunction, because the separator is only ever inserted *between* two
    present parts.

    A part that is ``None``, empty, or whitespace-only counts as absent, so a
    half-filled address never produces a column of punctuation.

    Safe to call with every part absent - registration still writes the
    pre-structured free-text value into the column until the structured parts
    exist, and a doctor who has not finished their address must not get a 500
    from a formatting function. An address with nothing in it returns the empty
    string; an address with one part in it returns that part alone, with no
    separator.

    The PIN code is emitted exactly as declared (whitespace stripped). Whether it
    resolves is :func:`resolve_pin_code`'s answer, not this function's, so a
    display string never implies that a position was derived.
    """
    present = (
        _present(parts.address_line),
        _present(parts.landmark),
        _present(parts.locality),
        _present(parts.city),
        _present(parts.pin_code),
    )
    return _PART_SEPARATOR.join(part for part in present if part is not None)


def great_circle_km(origin: PracticePosition, destination: PracticePosition) -> float:
    """Great-circle distance in km between two points, the haversine formula.

    The Python counterpart of the ``_haversine_km`` SQL expression in the
    directory sub-facade, deliberately the same formula over the same
    :data:`EARTH_MEAN_RADIUS_KM` mean Earth radius: the SQL expression keeps the
    nearest-first sort and the peri-urban range clamp inside the database at the
    cost floor, and this one exists so a *decision* about distance can be taken and
    tested without a connection. They must agree to the last meaningful digit;
    the unit suite pins the shared constant against the compiled SQL.

    The intermediate ``a`` term is clamped to ``[0, 1]`` because floating-point
    rounding can push it fractionally past 1 for near-antipodal points, which
    would otherwise make ``sqrt`` raise on a legitimate pair of coordinates.
    """
    origin_lat, origin_lng = math.radians(origin.latitude), math.radians(origin.longitude)
    dest_lat, dest_lng = math.radians(destination.latitude), math.radians(destination.longitude)
    half_lat = (dest_lat - origin_lat) / 2.0
    half_lng = (dest_lng - origin_lng) / 2.0
    a = (
        math.sin(half_lat) ** 2
        + math.cos(origin_lat) * math.cos(dest_lat) * math.sin(half_lng) ** 2
    )
    return 2.0 * EARTH_MEAN_RADIUS_KM * math.asin(math.sqrt(min(1.0, max(0.0, a))))


def evaluate_peri_urban_belt(
    position: PracticePosition,
    *,
    centre: PracticePosition,
    radius_km: float,
) -> PeriUrbanBeltDecision:
    """Decide whether a resolved practice position sits inside the peri-urban belt.

    The belt is the launch directory's geographic scope (FEAT-004, REQ-008):
    Daltonganj plus its surrounding peri-urban area. A position outside it is
    still a legitimate place to practise, so the answer is a **warning, not a
    refusal** - the address-section write succeeds and attaches this answer as a
    warning, because a doctor who has corrected a wrong sign-up PIN must not be
    blocked from saving by where they turned out to be.

    ``radius_km`` is a parameter, deliberately, and has no default here. Today the
    search clamp compares its own SQL distance expression against
    ``PERI_URBAN_RADIUS_KM`` in the directory sub-facade, and a boundary that
    only exists buried inside a query is a boundary no unit suite can reach and
    no caller can vary. Passing it in makes the decision testable at the exact
    radius and just past it, and makes the agreement with that constant the
    caller's explicit statement rather than an accident. The caller passes
    ``PERI_URBAN_RADIUS_KM``; this module knows no number.

    A position exactly on the boundary is **inside** (``<=``), matching the
    search clamp's own ``distance_km <= PERI_URBAN_RADIUS_KM`` condition. The two
    comparisons must be the same comparison, or the belt would have two edges.

    ``centre`` and ``radius_km`` are caller configuration: a non-finite or
    non-positive radius, or a centre outside the valid coordinate ranges, is a
    programming error and raises rather than silently returning a distance that
    compares wrong. ``position`` is trusted because it came out of
    :func:`resolve_pin_code`, which already refused unusable coordinates.
    """
    if not math.isfinite(radius_km) or radius_km <= 0.0:
        raise ValueError(f"radius_km must be finite and positive; got {radius_km!r}")
    if not _is_usable_coordinate(centre.latitude, -90.0, 90.0) or not _is_usable_coordinate(
        centre.longitude, -180.0, 180.0
    ):
        raise ValueError(f"belt centre is not a usable coordinate: {centre!r}")
    distance_km = great_circle_km(centre, position)
    return PeriUrbanBeltDecision(within_belt=distance_km <= radius_km, distance_km=distance_km)


def _present(value: str | None) -> str | None:
    """The trimmed part, or ``None`` when it is absent, empty or whitespace-only.

    Absent and blank are the same thing to a reader of an address: a line of
    commas carries no information, and emitting it would fill the retained
    display column with punctuation.
    """
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _is_usable_coordinate(value: float, minimum: float, maximum: float) -> bool:
    """True when a coordinate is finite and within its valid range.

    A centroid carrying a non-finite or out-of-range coordinate cannot be turned
    into a position a patient could ever be routed to, so the decision refuses it
    rather than writing it.
    """
    return math.isfinite(value) and minimum <= value <= maximum
