"""MOD-002: domain errors for the ``partner`` module (coding-standards §3).

Phase 1 carries the module base error only; the hierarchy grows
with the tickets that introduce real validation.
"""

from __future__ import annotations

from enum import StrEnum

from modules.partner.domain.practice_position import PinResolutionReason


class VocabularyRejectionReason(StrEnum):
    """Why a value was refused by a multi-valued closed vocabulary (#602).

    A closed list refuses a value for exactly two member-level reasons, and both
    are reported on the raised error so the message names the rule the member
    broke rather than blaming the whole selection.
    """

    UNKNOWN = "unknown"
    REPEATED = "repeated"


class PartnerError(Exception):
    """Base error for the partner module."""


class IllegalPartnerTransitionError(PartnerError):
    """The attempted lifecycle action is illegal in the profile's current state.

    Raised by the pure state machine for arbitrary inputs - including any path
    that would reach ``Active`` without an explicit operator approval, or a
    Step-1 auto-fail that would enter the operator queue (ADR-0008, ticket #247).
    """


class PartnerNotFoundError(PartnerError):
    """No partner profile exists under the addressed id."""

    def __init__(self, partner_id: int) -> None:
        super().__init__(f"no partner exists with id {partner_id}")
        self.partner_id = partner_id


class PartnerIamUnavailableError(PartnerError):
    """A partner operation genuinely requires the iam facade but none is composed.

    Raised by ``register`` (WI-3, #336) when the facade was built without the iam
    seam - e.g. the daily credential-expiry sweep, whose close-out never touches
    iam. A missing dependency must fail loudly (this typed error), never silently
    no-op: the sync credential account (ADR-0010) cannot be guaranteed otherwise.
    """


class ProviderProfileNotFoundError(PartnerError):
    """No public provider profile exists under the addressed id (PHASE-6 T03).

    Raised by ``get_provider_profile`` when the partner is not ``[Active]``,
    has no ``directory_index`` row, or carries any credential that is
    unverified, expired or revoked. The public profile is hidden exactly when
    search hides the card (ADR-0011 "tick gone = card gone"), so the route
    maps this to a 404 - never a "hidden" 200 that leaks a partner identity
    patients should not see.
    """

    def __init__(self, partner_id: int) -> None:
        super().__init__(f"no public provider profile exists for partner {partner_id}")
        self.partner_id = partner_id


class InvalidQueueSortError(PartnerError):
    """The operator asked to sort the verification queue by an unknown key."""

    def __init__(self, sort_by: str) -> None:
        super().__init__(f"unknown verification queue sort key: {sort_by}")
        self.sort_by = sort_by


class InvalidQueueStatusError(PartnerError):
    """The operator filtered the verification queue by an unknown status.

    Mirrors ``InvalidQueueSortError``: the ``status`` filter is validated
    against the lifecycle statuses whitelist before the WHERE clause runs, so
    an unknown value is an explicit error (422) rather than a silent empty
    queue.
    """

    def __init__(self, status: str) -> None:
        super().__init__(f"unknown verification queue status: {status}")
        self.status = status


class RejectionReasonRequiredError(PartnerError):
    """An operator rejection must carry a reason (two-step gate, ADR-0008).

    Moves the reject-requires-reason invariant into the domain core so no
    adapter or future caller can reject without explaining why (coding-standards
    §4: pre-conditions live in the domain core, never in the router).
    """


class ConsultationFeeNotAllowedError(PartnerError):
    """Only a doctor partner may set or update a consultation fee (PHASE-8.1 #444).

    Raised when a non-doctor partner (lab, chemist) attempts to update their
    consultation fee through the partner-scoped endpoint. The fee is
    doctor-only by design (glossary: consultation fee applies to doctor
    consultations only). The route maps this to a 403 with the envelope code
    ``CONSULTATION_FEE_NOT_ALLOWED``.
    """


class PartnerSuspendedError(PartnerError):
    """The self-service surface is cut off: the identity is suspended (F014-T06 #466).

    A suspended partner (iam ``partner`` role grant flipped to ``Suspended`` by
    ``suspend_partner_role``, ADR-0019) is a contact-support-only surface
    (ADR-0016): every partner self-service route refuses with this error so the
    partner cannot keep using half-working pages. The signal is read through the
    iam facade seam (``IamFacade.partner_role_status``), never by reading the
    partner schema - ``PartnerStatus`` has no ``Suspended`` value by design, the
    suspension lives only on the iam side. The route maps this to a 403 with the
    envelope code ``PARTNER_SUSPENDED``.
    """

    def __init__(self, identity_id: int) -> None:
        super().__init__(
            f"partner identity {identity_id} is suspended; the self-service surface is closed"
        )
        self.identity_id = identity_id


class PartnerNotActiveError(PartnerError):
    """The consultation fee is reachable only for an ``[Active]`` partner (F014-T06 #466).

    Raised when a partner that is not yet ``[Active]`` (or no longer, via
    deactivation) tries to set or clear their consultation fee. ADR-0016 gates
    the fee route to the active state; the doctor-only rule stays a separate,
    earlier refusal (``ConsultationFeeNotAllowedError``). The route maps this to
    a 403 with the envelope code ``PARTNER_NOT_ACTIVE``.
    """

    def __init__(self, partner_id: int, status: str) -> None:
        super().__init__(f"partner {partner_id} is {status}; consultation fee requires 'Active'")
        self.partner_id = partner_id
        self.status = status


class DoctorProfileNotAllowedError(PartnerError):
    def __init__(self, partner_id: int, partner_type: str, status: str) -> None:
        super().__init__(
            f"partner {partner_id} is {partner_type} in {status}; "
            "the private doctor profile requires an active doctor"
        )
        self.partner_id = partner_id
        self.partner_type = partner_type
        self.status = status


class DoctorProfilePhotoNotFoundError(PartnerError):
    def __init__(self, partner_id: int) -> None:
        super().__init__(f"doctor {partner_id} has no profile photo")
        self.partner_id = partner_id


class DoctorProfilePhotoValidationError(PartnerError):
    pass


class DoctorProfilePhotoTransferError(PartnerError):
    pass


class DoctorProfilePhotoStoreUnavailableError(PartnerError):
    pass


class PartnerNotRejectedError(PartnerError):
    """The recovery action requires the partner to be in the ``[Rejected]`` state.

    A rejection-reason view or a one-time appeal only makes sense for a rejected
    partner (ADR-0008 recovery; PHASE-5 T09). Raising from the domain core keeps
    the precondition in the facade, never just the router.
    """

    def __init__(self, partner_id: int, status: str) -> None:
        super().__init__(
            f"partner {partner_id} is {status}; rejection recovery requires 'Rejected'"
        )
        self.partner_id = partner_id
        self.status = status


class AppealAlreadyUsedError(PartnerError):
    """The partner's one-time appeal has already been consumed (PHASE-5 T09).

    A rejection appeal may be filed exactly once; a second attempt is rejected
    (the ``appeal_used`` flag is consumed on first use and never re-armed).
    """


class ServiceAreaNotFoundError(PartnerError):
    """The ``service_area_id`` a registration declared does not exist (PHASE-5 #265).

    A partner can never be attached to a nonexistent service area: an unknown
    ``service_area_id`` is rejected (mapped to a 422) instead of silently
    persisting a dangling reference.
    """

    def __init__(self, service_area_id: int) -> None:
        super().__init__(f"no service area exists with id {service_area_id}")
        self.service_area_id = service_area_id


class ReSubmissionThrottledError(PartnerError):
    """A rejected partner has exhausted the re-submission budget (PHASE-5 T09).

    The verification queue is protected by a business-rule throttle - a rejected
    partner may re-submit corrected credentials up to a maximum number of rounds
    before a cooldown (NFR-001 headcount, ADR-0008). Raised when the boundary is
    crossed so the queue cannot be spammed.
    """

    def __init__(self, partner_id: int, retry_at: str | None = None) -> None:
        message = f"partner {partner_id} has exceeded the re-submission limit"
        if retry_at is not None:
            message += f"; retry after {retry_at}"
        super().__init__(message)
        self.partner_id = partner_id
        self.retry_at = retry_at


class InvalidSpecialtyError(PartnerError):
    """The submitted specialty breaks the closed pick-list rule (#602).

    Raised by ``require_specialty`` and ``require_specialties``, the two
    validation entry points for the doctor specialty pick-list (FEAT-004,
    glossary). The field is never free-form, so a value outside the list is an
    explicit rejection (422) rather than a value that persists and can never be
    filtered on.

    ``value`` is typed ``object`` because a malformed submission is not
    necessarily a string - the entry point refuses a non-string as readily as an
    unknown string. ``position`` and ``reason`` are carried only when a member of
    a multi-valued selection broke a rule, so the single-valued field keeps a
    plain ``"unknown specialty"`` message.
    """

    def __init__(
        self,
        value: object,
        position: int | None = None,
        reason: VocabularyRejectionReason = VocabularyRejectionReason.UNKNOWN,
    ) -> None:
        if position is None:
            super().__init__(f"{reason} specialty: {value!r}")
        else:
            super().__init__(f"{reason} specialty at position {position}: {value!r}")
        self.value = value
        self.position = position
        self.reason = reason


class PracticePinUnresolvedError(PartnerError):
    """A declared practice PIN code does not resolve to a position (#609).

    Raised by the address section write when ``resolve_pin_code`` (#603) answers
    with anything but a position. It is an **expected 4xx**, not an operational
    failure (error taxonomy): the doctor typed something this platform cannot
    place, the save is refused, and every other edit on their profile is untouched.
    The partner adapter encodes it as a 422 whose ``details.errors[].path`` is the
    PIN field, which is what lets the client render the problem under that input
    instead of guessing which one failed.

    **Both refusals are the same error to the caller.** ``reason`` distinguishes
    them for the machine - ``MALFORMED`` means "fix this field", ``UNKNOWN`` means
    "this well-formed PIN code is not one we can place yet" - but the doctor cannot
    tell a length failure from a character-class failure, so the message never
    claims to. The data gap behind ``UNKNOWN`` is a follow-up, not something this
    write works around: there is no support-request surface in the repo to route it
    to, so the field-level error is genuinely all the doctor gets, and inventing a
    fallback position would be worse than the refusal.

    ``pin_code`` is the declared value, carried so a caller can report which value
    it refused. It is never echoed into the response body or the log line.
    """

    def __init__(self, pin_code: str, reason: PinResolutionReason) -> None:
        if reason is PinResolutionReason.MALFORMED:
            message = "the PIN code must be six digits"
        else:
            message = "this PIN code is not one we can place yet"
        super().__init__(message)
        self.pin_code = pin_code
        self.reason = reason


class InvalidConsultLanguageError(PartnerError):
    """A submitted consulting language breaks the closed-list rule (#602).

    Raised by ``require_consult_languages``, which validates a multi-valued
    selection member by member. ``position`` is the index of the offending
    member, and ``reason`` says which of the two member-level rules it broke,
    so the message points at the member instead of blaming the whole selection.
    """

    def __init__(self, value: object, position: int, reason: VocabularyRejectionReason) -> None:
        super().__init__(f"{reason} consulting language at position {position}: {value!r}")
        self.value = value
        self.position = position
        self.reason = reason


class InvalidConsultingDayError(PartnerError):
    """A submitted consulting day breaks the closed seven-day rule (#602).

    The consulting-day counterpart of :class:`InvalidConsultLanguageError`:
    raised by ``require_consulting_days`` with the same ``value`` / ``position``
    / ``reason`` shape.
    """

    def __init__(self, value: object, position: int, reason: VocabularyRejectionReason) -> None:
        super().__init__(f"{reason} consulting day at position {position}: {value!r}")
        self.value = value
        self.position = position
        self.reason = reason


class InvalidSelectionError(PartnerError):
    """A multi-valued field was submitted as one bare value instead of a selection.

    A ``str`` is itself iterable, so ``require_consulting_days("Monday")`` would
    otherwise walk one character at a time and reject the letter ``M`` - a
    legitimate single-day submission reported as nonsense. One day is a
    one-member selection, so the caller sends a list; this error says exactly
    that instead of blaming a character (coding-standards §3: type everything,
    but ``Iterable`` cannot exclude ``str``, so the check is at runtime).
    """

    def __init__(self, value: object) -> None:
        super().__init__(f"expected a selection of values, not a single value: {value!r}")
        self.value = value


class InvalidNotificationKeyError(PartnerError):
    """A submitted notification preference key is not one of the five (#610).

    Raised by ``require_notification_preferences`` and
    :func:`~modules.partner.domain.vocabularies.merge_notification_preferences`
    when the save carries a key outside ``NotificationPreferenceKey``. It is an
    **expected 4xx**, encoded by the partner adapter as a 422 whose
    ``details.errors[].path`` is ``notification_preferences``, so the client
    renders it against the card rather than guessing which toggle failed.

    No ``position`` and no ``reason``, unlike the three multi-valued pick-lists:
    a preference is a **dict**, so there is no member order to point into and
    only one member-level rule to break - a key that is not on the list. The key
    itself is the whole answer, and it is carried so a caller can report which
    one was refused. ``str(err)`` quotes the submitted key back, which is a
    machine-readable identifier and never free text a doctor typed.
    """

    def __init__(self, key: object) -> None:
        super().__init__(f"unknown notification preference key: {key!r}")
        self.key = key
