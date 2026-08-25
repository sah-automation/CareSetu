"""PHASE-3 T4: check_consent gate - property-style scope subsumption tests (#213).

The gate is a pure function over (patient, scope, counterparty) returning the
four-field contract. Scope subsumption is the critical logic: full_record
subsumes every specific scope; exact match passes; everything else fails.
"""

from __future__ import annotations

import pytest

from modules.consent.domain.state_machine import RECORD_SCOPES
from modules.consent.facade import _scope_subsumes


class TestScopeSubsumption:
    """Property-style tests over the closed RECORD_SCOPES enum."""

    @pytest.mark.parametrize("scope", RECORD_SCOPES)
    def test_full_record_subsumes_every_specific_scope(self, scope: str) -> None:
        """full_record granted => every requested scope is allowed."""
        assert _scope_subsumes(requested=scope, granted="full_record") is True

    @pytest.mark.parametrize("scope", RECORD_SCOPES)
    def test_exact_match_passes(self, scope: str) -> None:
        """Same scope requested and granted => allowed."""
        assert _scope_subsumes(requested=scope, granted=scope) is True

    @pytest.mark.parametrize("requested", [s for s in RECORD_SCOPES if s != "full_record"])
    @pytest.mark.parametrize("granted", [s for s in RECORD_SCOPES if s != "full_record"])
    def test_specific_scopes_do_not_subsume_each_other(self, requested: str, granted: str) -> None:
        """Different specific scopes => denied (no cross-subsumption)."""
        if requested != granted:
            assert _scope_subsumes(requested=requested, granted=granted) is False

    def test_unknown_scope_is_denied_even_against_full_record(self) -> None:
        """Unknown requested scope is denied even if full_record is granted."""
        assert _scope_subsumes(requested="unknown_scope", granted="full_record") is False

    def test_full_record_requested_requires_full_record_granted(self) -> None:
        """Requesting full_record requires full_record granted, not a specific scope."""
        for specific in [s for s in RECORD_SCOPES if s != "full_record"]:
            assert _scope_subsumes(requested="full_record", granted=specific) is False


class TestCheckConsentDecision:
    """Test the ConsentDecision model contract."""

    def test_decision_contract_has_four_fields(self) -> None:
        """ConsentDecision must have exactly: allowed, consent_id, version, effective_scope."""
        from modules.consent.facade import ConsentDecision

        decision = ConsentDecision(
            allowed=True, consent_id=42, version=3, effective_scope="consultations"
        )
        assert decision.allowed is True
        assert decision.consent_id == 42
        assert decision.version == 3
        assert decision.effective_scope == "consultations"

    def test_decision_denied_has_none_fields(self) -> None:
        """Denied decision has None for consent_id, version, effective_scope."""
        from modules.consent.facade import ConsentDecision

        decision = ConsentDecision(
            allowed=False,
            consent_id=None,
            version=None,
            effective_scope=None,
        )
        assert decision.allowed is False
        assert decision.consent_id is None
        assert decision.version is None
        assert decision.effective_scope is None
