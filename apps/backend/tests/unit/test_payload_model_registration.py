"""Tests for payload model registration (issue #943).

Verifies that all event types produced by IAM and Partner modules have
registered payload models in the HandlerRegistry after build_registry().
"""

from __future__ import annotations

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
    EVENT_PARTNER_REJECTED,
    EVENT_PARTNER_SELECTED,
    EVENT_PARTNER_VERIFICATION_STARTED,
    EVENT_PATIENT_AUTH_FAILED,
    EVENT_PATIENT_REGISTERED,
    EVENT_PATIENT_VERIFIED,
)
from bus.registry import HandlerRegistry
from modules.iam.adapters import register_handlers as iam_register_handlers
from modules.iam.domain.consumer import (
    CredentialInvalidatedPayload,
)
from modules.iam.domain.events import (
    OperatorActiveChangedPayload,
    OperatorInvitedPayload,
    OperatorMfaFailedPayload,
    OperatorTierChangedPayload,
    OtpFailedPayload,
    OtpSentPayload,
    PatientAuthFailedPayload,
    PatientRegisteredPayload,
    PatientVerifiedPayload,
)
from modules.partner.adapters import register_handlers as partner_register_handlers

# isort: off
from modules.partner.domain.events import (
    DirectorySearchPayload,
    PartnerActivatedPayload as PartnerPartnerActivatedPayload,
    PartnerRejectedPayload as PartnerPartnerRejectedPayload,
    PartnerSelectedPayload,
    VerificationStartedPayload,
)
# isort: on


def _build_registry() -> HandlerRegistry:
    """Build a registry with IAM and Partner module registrations."""
    registry = HandlerRegistry()
    iam_register_handlers(registry)
    partner_register_handlers(registry)
    return registry


class TestIAMPayloadModelRegistration:
    """Verify IAM module registers payload models for all events it produces."""

    def test_patient_registered_payload_model_registered(self) -> None:
        registry = _build_registry()
        model = registry.payload_model_for(EVENT_PATIENT_REGISTERED)
        assert model is PatientRegisteredPayload

    def test_otp_sent_payload_model_registered(self) -> None:
        registry = _build_registry()
        model = registry.payload_model_for(EVENT_OTP_SENT)
        assert model is OtpSentPayload

    def test_patient_verified_payload_model_registered(self) -> None:
        registry = _build_registry()
        model = registry.payload_model_for(EVENT_PATIENT_VERIFIED)
        assert model is PatientVerifiedPayload

    def test_otp_failed_payload_model_registered(self) -> None:
        registry = _build_registry()
        model = registry.payload_model_for(EVENT_OTP_FAILED)
        assert model is OtpFailedPayload

    def test_patient_auth_failed_payload_model_registered(self) -> None:
        registry = _build_registry()
        model = registry.payload_model_for(EVENT_PATIENT_AUTH_FAILED)
        assert model is PatientAuthFailedPayload

    def test_operator_invited_payload_model_registered(self) -> None:
        registry = _build_registry()
        model = registry.payload_model_for(EVENT_OPERATOR_INVITED)
        assert model is OperatorInvitedPayload

    def test_operator_mfa_failed_payload_model_registered(self) -> None:
        registry = _build_registry()
        model = registry.payload_model_for(EVENT_OPERATOR_MFA_FAILED)
        assert model is OperatorMfaFailedPayload

    def test_operator_tier_changed_payload_model_registered(self) -> None:
        registry = _build_registry()
        model = registry.payload_model_for(EVENT_OPERATOR_TIER_CHANGED)
        assert model is OperatorTierChangedPayload

    def test_operator_active_changed_payload_model_registered(self) -> None:
        registry = _build_registry()
        model = registry.payload_model_for(EVENT_OPERATOR_ACTIVE_CHANGED)
        assert model is OperatorActiveChangedPayload

    def test_credential_invalidated_payload_model_registered(self) -> None:
        registry = _build_registry()
        model = registry.payload_model_for(EVENT_CREDENTIAL_INVALIDATED)
        assert model is CredentialInvalidatedPayload

    def test_partner_activated_payload_model_not_registered_by_iam(self) -> None:
        """IAM does NOT register payload model for partner.activated (producer owns it)."""
        registry = _build_registry()
        # Partner module (producer) registers it, not IAM (consumer)
        model = registry.payload_model_for(EVENT_PARTNER_ACTIVATED)
        assert model is PartnerPartnerActivatedPayload

    def test_partner_rejected_payload_model_not_registered_by_iam(self) -> None:
        """IAM does NOT register payload model for partner.rejected (producer owns it)."""
        registry = _build_registry()
        model = registry.payload_model_for(EVENT_PARTNER_REJECTED)
        assert model is PartnerPartnerRejectedPayload


class TestPartnerPayloadModelRegistration:
    """Verify Partner module registers payload models for all events it produces."""

    def test_partner_verification_started_payload_model_registered(self) -> None:
        registry = _build_registry()
        model = registry.payload_model_for(EVENT_PARTNER_VERIFICATION_STARTED)
        assert model is VerificationStartedPayload

    def test_partner_activated_payload_model_registered_in_partner(self) -> None:
        """Partner registers payload model for partner.activated (producer owns model)."""
        registry = _build_registry()
        model = registry.payload_model_for(EVENT_PARTNER_ACTIVATED)
        # Partner module is the producer, so it should register its own model
        assert model is PartnerPartnerActivatedPayload

    def test_partner_rejected_payload_model_registered_in_partner(self) -> None:
        """Partner registers payload model for partner.rejected (producer owns model)."""
        registry = _build_registry()
        model = registry.payload_model_for(EVENT_PARTNER_REJECTED)
        assert model is PartnerPartnerRejectedPayload

    def test_directory_search_payload_model_registered(self) -> None:
        registry = _build_registry()
        model = registry.payload_model_for(EVENT_DIRECTORY_SEARCH)
        assert model is DirectorySearchPayload

    def test_partner_selected_payload_model_registered(self) -> None:
        registry = _build_registry()
        model = registry.payload_model_for(EVENT_PARTNER_SELECTED)
        assert model is PartnerSelectedPayload


class TestRegulatedActExclusions:
    """Verify regulated act events are NOT registered by producer modules."""

    def test_partner_registered_not_registered_by_partner(self) -> None:
        """partner.registered is a regulated act owned by Audit."""
        from bus.events import EVENT_PARTNER_REGISTERED

        registry = _build_registry()
        # Partner module should NOT register this - Audit owns it
        model = registry.payload_model_for(EVENT_PARTNER_REGISTERED)
        # It will be registered by audit module, not by partner
        # But since we only built IAM+Partner registry, it should be None
        assert model is None

    def test_partner_credential_reviewed_not_registered_by_partner(self) -> None:
        """partner.credential_reviewed is a regulated act owned by Audit."""
        from bus.events import EVENT_PARTNER_CREDENTIAL_REVIEWED

        registry = _build_registry()
        model = registry.payload_model_for(EVENT_PARTNER_CREDENTIAL_REVIEWED)
        assert model is None


class TestDuplicateRegistrationGuard:
    """Verify that registering the same payload model twice raises ValueError."""

    def test_duplicate_payload_model_raises(self) -> None:
        registry = HandlerRegistry()
        registry.register_payload_model(EVENT_PATIENT_REGISTERED, PatientRegisteredPayload)

        # Second registration should raise
        try:
            registry.register_payload_model(EVENT_PATIENT_REGISTERED, PatientRegisteredPayload)
        except ValueError as e:
            assert "payload model already registered" in str(e)
        else:
            raise AssertionError("Expected ValueError")

    def test_duplicate_registration_different_model_raises(self) -> None:
        registry = HandlerRegistry()
        registry.register_payload_model(EVENT_PATIENT_REGISTERED, PatientRegisteredPayload)

        class OtherPayload(PatientRegisteredPayload):
            pass

        try:
            registry.register_payload_model(EVENT_PATIENT_REGISTERED, OtherPayload)
        except ValueError as e:
            assert "payload model already registered" in str(e)
        else:
            raise AssertionError("Expected ValueError")