"""Payload model registration tests (issue #943).

The dispatcher reconstructs a claimed outbox row with the registered payload
model before fan-out, so every event type in any outbox table must have exactly
one model in the registry. These tests pin the producer-owns-the-model
convention for IAM and Partner, the Audit-owned regulated-act exclusions, the
one-model-per-type guard, and the full composition root build (which is where
a cross-module duplicate would actually raise).
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from bus.events import (
    EVENT_CREDENTIAL_INVALIDATED,
    EVENT_DIRECTORY_SEARCH,
    EVENT_OPERATOR_ACTIVE_CHANGED,
    EVENT_OPERATOR_INVITED,
    EVENT_OPERATOR_MFA_FAILED,
    EVENT_OPERATOR_TIER_CHANGED,
    EVENT_OTP_FAILED,
    EVENT_OTP_SENT,
    EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_CREDENTIAL_REVIEWED,
    EVENT_PARTNER_REGISTERED,
    EVENT_PARTNER_REJECTED,
    EVENT_PARTNER_SELECTED,
    EVENT_PARTNER_VERIFICATION_STARTED,
    EVENT_PATIENT_AUTH_FAILED,
    EVENT_PATIENT_REGISTERED,
    EVENT_PATIENT_VERIFIED,
)
from bus.registry import HandlerRegistry
from modules.iam.adapters import register_handlers as iam_register_handlers
from modules.iam.domain import consumer as iam_consumer
from modules.iam.domain import events as iam_events
from modules.partner.adapters import register_handlers as partner_register_handlers
from modules.partner.domain import events as partner_events
from worker.main import build_registry


def _producer_registry() -> HandlerRegistry:
    """Registry with the two producer modules this issue touches only."""
    registry = HandlerRegistry()
    iam_register_handlers(registry)
    partner_register_handlers(registry)
    return registry


class TestIAMPayloadModelRegistration:
    """IAM (MOD-001) registers a payload model for every event it produces."""

    @pytest.mark.parametrize(
        ("event_type", "payload_model"),
        [
            (EVENT_PATIENT_REGISTERED, iam_events.PatientRegisteredPayload),
            (EVENT_OTP_SENT, iam_events.OtpSentPayload),
            (EVENT_PATIENT_VERIFIED, iam_events.PatientVerifiedPayload),
            (EVENT_OTP_FAILED, iam_events.OtpFailedPayload),
            (EVENT_PATIENT_AUTH_FAILED, iam_events.PatientAuthFailedPayload),
            (EVENT_OPERATOR_INVITED, iam_events.OperatorInvitedPayload),
            (EVENT_OPERATOR_MFA_FAILED, iam_events.OperatorMfaFailedPayload),
            (EVENT_OPERATOR_TIER_CHANGED, iam_events.OperatorTierChangedPayload),
            (EVENT_OPERATOR_ACTIVE_CHANGED, iam_events.OperatorActiveChangedPayload),
            (EVENT_CREDENTIAL_INVALIDATED, iam_consumer.CredentialInvalidatedPayload),
        ],
    )
    def test_payload_model_registered(
        self, event_type: str, payload_model: type[BaseModel]
    ) -> None:
        registry = _producer_registry()
        assert registry.payload_model_for(event_type) is payload_model


class TestPartnerPayloadModelRegistration:
    """Partner (MOD-002) registers a payload model for every event it produces."""

    @pytest.mark.parametrize(
        ("event_type", "payload_model"),
        [
            (EVENT_PARTNER_VERIFICATION_STARTED, partner_events.VerificationStartedPayload),
            (EVENT_PARTNER_ACTIVATED, partner_events.PartnerActivatedPayload),
            (EVENT_PARTNER_REJECTED, partner_events.PartnerRejectedPayload),
            (EVENT_DIRECTORY_SEARCH, partner_events.DirectorySearchPayload),
            (EVENT_PARTNER_SELECTED, partner_events.PartnerSelectedPayload),
        ],
    )
    def test_payload_model_registered(
        self, event_type: str, payload_model: type[BaseModel]
    ) -> None:
        registry = _producer_registry()
        assert registry.payload_model_for(event_type) is payload_model


class TestRegulatedActExclusions:
    """Producers must NOT register the Audit-owned regulated acts.

    The registry's one-model-per-type guard would raise once the Audit module
    also registers its chain-append mirror, so the producer leaves the slot to
    the consumer (MOD-011).
    """

    @pytest.mark.parametrize(
        "event_type", [EVENT_PARTNER_REGISTERED, EVENT_PARTNER_CREDENTIAL_REVIEWED]
    )
    def test_regulated_act_not_registered_by_producer(self, event_type: str) -> None:
        assert _producer_registry().payload_model_for(event_type) is None


class TestCompositionRootRegistry:
    """The full production registry builds without conflicts (issue #943).

    worker.main.build_registry wires every module's register_handlers in the
    same order the worker does. Any cross-module duplicate payload model (a
    consumer re-registering a producer's event) raises ValueError here, exactly
    as it would crash the worker at startup.
    """

    def test_build_registry_contains_all_produced_events(self) -> None:
        registry = build_registry()
        expected: dict[str, type[BaseModel]] = {
            EVENT_PATIENT_REGISTERED: iam_events.PatientRegisteredPayload,
            EVENT_OTP_SENT: iam_events.OtpSentPayload,
            EVENT_PATIENT_VERIFIED: iam_events.PatientVerifiedPayload,
            EVENT_OTP_FAILED: iam_events.OtpFailedPayload,
            EVENT_PATIENT_AUTH_FAILED: iam_events.PatientAuthFailedPayload,
            EVENT_OPERATOR_INVITED: iam_events.OperatorInvitedPayload,
            EVENT_OPERATOR_MFA_FAILED: iam_events.OperatorMfaFailedPayload,
            EVENT_OPERATOR_TIER_CHANGED: iam_events.OperatorTierChangedPayload,
            EVENT_OPERATOR_ACTIVE_CHANGED: iam_events.OperatorActiveChangedPayload,
            EVENT_CREDENTIAL_INVALIDATED: iam_consumer.CredentialInvalidatedPayload,
            EVENT_PARTNER_VERIFICATION_STARTED: partner_events.VerificationStartedPayload,
            EVENT_PARTNER_ACTIVATED: partner_events.PartnerActivatedPayload,
            EVENT_PARTNER_REJECTED: partner_events.PartnerRejectedPayload,
            EVENT_DIRECTORY_SEARCH: partner_events.DirectorySearchPayload,
            EVENT_PARTNER_SELECTED: partner_events.PartnerSelectedPayload,
        }
        for event_type, payload_model in expected.items():
            assert registry.payload_model_for(event_type) is payload_model, event_type

    def test_build_registry_registers_audit_mirrors_for_regulated_acts(self) -> None:
        registry = build_registry()
        # Audit (MOD-011) owns the registry slot for the regulated acts.
        from modules.audit.domain import consumer as audit_consumer

        assert registry.payload_model_for(EVENT_PARTNER_REGISTERED) is (
            audit_consumer.PartnerRegisteredPayload
        )
        assert registry.payload_model_for(EVENT_PARTNER_CREDENTIAL_REVIEWED) is (
            audit_consumer.CredentialReviewedPayload
        )


class TestCredentialInvalidatedMirrorParity:
    """The three ``credential.invalidated`` models must keep identical contracts.

    Partner publishes its own model into the envelope, IAM's consumer mirror
    owns the registry slot, and Audit's mirror re-validates for the chain
    append. The dispatcher reconstructs with IAM's model, so if any of the
    three drifts apart the other two silently mis-handle the row.
    """

    def test_all_three_models_have_identical_field_contracts(self) -> None:
        from modules.audit.domain import consumer as audit_consumer

        def contract(model: type[BaseModel]) -> dict[str, tuple[object, bool]]:
            return {
                name: (field.annotation, field.is_required())
                for name, field in model.model_fields.items()
            }

        producer = contract(partner_events.CredentialInvalidatedPayload)
        iam_mirror = contract(iam_consumer.CredentialInvalidatedPayload)
        audit_mirror = contract(audit_consumer.CredentialInvalidatedPayload)
        assert producer == iam_mirror == audit_mirror


class TestDuplicateRegistrationGuard:
    """Registering the same payload model twice raises ValueError."""

    def test_duplicate_payload_model_raises(self) -> None:
        registry = HandlerRegistry()
        registry.register_payload_model(
            EVENT_PATIENT_REGISTERED, iam_events.PatientRegisteredPayload
        )
        with pytest.raises(ValueError, match="payload model already registered"):
            registry.register_payload_model(
                EVENT_PATIENT_REGISTERED, iam_events.PatientRegisteredPayload
            )

    def test_duplicate_registration_different_model_raises(self) -> None:
        registry = HandlerRegistry()
        registry.register_payload_model(
            EVENT_PATIENT_REGISTERED, iam_events.PatientRegisteredPayload
        )

        class OtherPayload(iam_events.PatientRegisteredPayload):
            pass

        with pytest.raises(ValueError, match="payload model already registered"):
            registry.register_payload_model(EVENT_PATIENT_REGISTERED, OtherPayload)
