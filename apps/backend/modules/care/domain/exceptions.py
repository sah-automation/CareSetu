"""MOD-006: domain errors for the ``care`` module (coding-standards §3).

The hierarchy grows with the tickets that introduce real validation.
"""

from __future__ import annotations


class CareError(Exception):
    """Base error for the care module."""


class CareNotFoundError(CareError):
    """Raised when a care entity is not found or the caller lacks access.

    Mirrors :class:`~modules.intake.domain.exceptions.IntakeNotFoundError`
    for the MOD-006 care module (PHASE-8 T04, ticket #420): the facade
    raises this when a care case lookup misses, or when the requesting
    doctor does not own the case.
    """


class CareValidationError(CareError):
    """Raised when a care write is rejected by a state/input validation.

    Mirrors :class:`~modules.intake.domain.exceptions.IntakeValidationError`
    for the MOD-006 care module (PHASE-8 T04, ticket #420): raised for a
    non-transition state or input check the case machine does not decide
    (e.g. a closed case rejecting a fresh doctor input).
    """


class IllegalCareTransitionError(CareError):
    """Raised when a care case is asked to take an illegal lifecycle action.

    Mirrors :class:`~modules.intake.domain.exceptions.IllegalIntakeTransitionError`
    for the MOD-006 case machine (PHASE-8 T02, ticket #418): the case stage
    machine is a closed automaton, so every edge outside the binding transition
    table is reported with the action and the current stage named.
    """


class IllegalPrescriptionTransitionError(CareError):
    """Raised when a prescription is asked to take an illegal lifecycle action.

    Mirrors :class:`~modules.intake.domain.exceptions.IllegalPreSummaryTransitionError`
    for the MOD-006 prescription machine (PHASE-8 T03, ticket #419): the
    prescription machine is a closed automaton, so every edge outside the
    binding transition table is reported with the action, current status, and
    any missing transition prerequisite (verification declaration, rejection
    reason, or the drafting cap) named. ``CareError`` subclasses carry the
    ``care`` module's namespace so the facade can map them to typed responses.
    """


# ---------------------------------------------------------------------------
# Prescription-drafting refusals (PHASE-8.1 T5, ticket #487)
#
# One distinct type per AI-draft refusal so the route boundary can answer the
# shared error envelope with a code the frontend maps to a specific message
# (ticket #490) instead of the generic ``CARE_VALIDATION_ERROR`` catch-all.
# Each is a ``CareError`` subclass so the module's 500 fallback still covers
# any future un-mapped addition.
# ---------------------------------------------------------------------------


class CareRxDraftConsentDeniedError(CareError):
    """The consent-gated history read for AI drafting was refused.

    Raised by the prescription facade when ``HealthFacade.read_consented_history``
    answers a denial (no live ``prescriptions``/``full_record`` grant for the
    attending doctor). The denial has already been recorded in the health
    access-history ledger; the care route maps this to the 403
    ``CARE_RX_CONSENT_DENIED`` envelope. Fail-closed per NFR-SEC-006.
    """


class CareRxNoDoctorInputError(CareValidationError):
    """An AI draft was requested before any doctor input was captured.

    The drafting leg needs a voice note / photo / typed addendum to draft from;
    the care route maps this to the 422 ``CARE_RX_NO_DOCTOR_INPUT`` envelope.
    """


class CareRxDraftCapReachedError(IllegalPrescriptionTransitionError):
    """The drafting cap blocks a new AI draft (max 2 rejected drafts).

    Raised by the prescription machine's ``CREATE_DRAFT`` branch once 2 drafts
    have been rejected. The care route maps this to the 422
    ``CARE_RX_DRAFT_CAP_REACHED`` envelope; manual authoring stays open
    (CONTEXT.md glossary, ``drafting cap``).
    """


class CareCaseClosedError(CareValidationError):
    """A prescription write targeted a care case that is already ``Closed``.

    ``Closed`` is terminal: no new draft (AI or manual) may be created. The
    care route maps this to the 422 ``CARE_CASE_CLOSED`` envelope.
    """
