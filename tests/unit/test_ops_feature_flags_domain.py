"""Unit tests for ops feature flags domain logic (#773)."""

from __future__ import annotations

import pytest

from modules.ops.domain.exceptions import InvalidFeatureFlagWriteError
from modules.ops.domain.settings import (
    FeatureFlag,
    FeatureFlagKind,
    validate_feature_flag_write,
)


class TestFeatureFlagDomain:
    """Tests for feature flag domain logic (no database required)."""

    def test_feature_flag_editable_property_runtime(self) -> None:
        """Runtime flags should be editable."""
        flag = FeatureFlag(
            flag_key="test.runtime",
            enabled=True,
            flag_kind=FeatureFlagKind.RUNTIME,
            description="Test runtime flag",
            updated_by=None,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        assert flag.editable is True

    def test_feature_flag_editable_property_restart_required(self) -> None:
        """Restart-required flags should not be editable."""
        flag = FeatureFlag(
            flag_key="test.restart",
            enabled=True,
            flag_kind=FeatureFlagKind.RESTART_REQUIRED,
            description="Test restart flag",
            updated_by=None,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        assert flag.editable is False

    def test_validate_feature_flag_write_runtime_succeeds(self) -> None:
        """Writing a runtime flag should succeed."""
        flag = FeatureFlag(
            flag_key="test.runtime",
            enabled=True,
            flag_kind=FeatureFlagKind.RUNTIME,
            description="Test runtime flag",
            updated_by=None,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        validate_feature_flag_write(flag, False)  # Should not raise

    def test_validate_feature_flag_write_restart_required_raises(self) -> None:
        """Writing a restart-required flag should raise with clear error."""
        flag = FeatureFlag(
            flag_key="test.restart",
            enabled=True,
            flag_kind=FeatureFlagKind.RESTART_REQUIRED,
            description="Test restart flag",
            updated_by=None,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        with pytest.raises(InvalidFeatureFlagWriteError) as exc_info:
            validate_feature_flag_write(flag, False)
        assert "restart-required" in str(exc_info.value).lower()
        assert "cannot be edited" in str(exc_info.value).lower()
