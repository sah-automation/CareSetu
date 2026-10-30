"""Tests for SMTP alert delivery channel (#786)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from modules.observability.domain.alert_delivery import (
    AlertRow,
    Channel,
    DeliveryAttemptResult,
    FakeAdapter,
    SmtpAdapter,
)
from modules.observability.facade import ObservabilityFacade
from modules.ops.domain.settings import EffectiveSetting, SettingSource


class TestSmtpAdapter:
    """Tests for the SmtpAdapter."""

    def test_smtp_adapter_initialization(self) -> None:
        """SMTP adapter initializes with correct parameters."""
        adapter = SmtpAdapter(
            host="smtp.example.com",
            port=587,
            username="user@example.com",
            password="secret",
            from_addr="alerts@example.com",
            to_addrs=["ops@example.com"],
            use_tls=True,
        )
        assert adapter.channel_name == "email"
        assert adapter._host == "smtp.example.com"
        assert adapter._port == 587
        assert adapter._username == "user@example.com"
        assert adapter._password == "secret"
        assert adapter._from_addr == "alerts@example.com"
        assert adapter._to_addrs == ["ops@example.com"]
        assert adapter._use_tls is True

    @pytest.mark.asyncio
    async def test_smtp_adapter_send_success(self) -> None:
        """Successful send returns DeliveryAttemptResult with success=True."""
        adapter = SmtpAdapter(
            host="smtp.example.com",
            port=587,
            username="user@example.com",
            password="secret",
            from_addr="alerts@example.com",
            to_addrs=["ops@example.com"],
        )

        alert = AlertRow(
            id="00000000-0000-0000-0000-000000000000",
            severity="warning",
            kind="test_alert",
            title="Test Alert",
            payload={"key": "value"},
            status="open",
            created_at=None,
        )

        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = AsyncMock()
            mock_get_loop.return_value = mock_loop
            mock_loop.run_in_executor = AsyncMock()

            result = await adapter.send(alert, "https://console.example.com/alerts/123")

        assert isinstance(result, DeliveryAttemptResult)
        assert result.success is True
        assert result.error is None

    @pytest.mark.asyncio
    async def test_smtp_adapter_send_failure_does_not_leak_credentials(self) -> None:
        """Failed send returns error without leaking SMTP credentials."""
        adapter = SmtpAdapter(
            host="smtp.example.com",
            port=587,
            username="user@example.com",
            password="super-secret-password",
            from_addr="alerts@example.com",
            to_addrs=["ops@example.com"],
        )

        alert = AlertRow(
            id="00000000-0000-0000-0000-000000000000",
            severity="warning",
            kind="test_alert",
            title="Test Alert",
            payload={"key": "value"},
            status="open",
            created_at=None,
        )

        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = AsyncMock()
            mock_get_loop.return_value = mock_loop
            mock_loop.run_in_executor = AsyncMock(
                side_effect=Exception(
                    "authentication failed for user@example.com with password super-secret-password"
                )
            )

            result = await adapter.send(alert, "https://console.example.com/alerts/123")

        assert isinstance(result, DeliveryAttemptResult)
        assert result.success is False
        # Error should not leak the username or password
        assert "user@example.com" not in result.error
        assert "super-secret-password" not in result.error
        # Should return generic error
        assert result.error == "SMTP delivery failed"


class TestAlertDeliveryAdaptersEmail:
    """Tests for the alert_delivery_adapters factory function with email channel."""

    def test_email_adapter_not_created_when_gate_is_off(self) -> None:
        """Email adapter is not created when notification.channels.email.enabled is False."""
        settings = Settings(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="user@example.com",
            smtp_password="secret",
            smtp_from="alerts@example.com",
            smtp_to="ops@example.com",
        )

        # Effective settings with Email gate OFF (default)
        effective_settings = [
            EffectiveSetting(
                key="notification.channels.email.enabled",
                value=False,
                source=SettingSource.DEFAULT.value,
                editable=True,
                restart_required=False,
            ),
        ]

        facade = ObservabilityFacade(engine=None, settings=settings)
        adapters = facade.alert_delivery_adapters(settings, effective_settings)

        assert Channel.EMAIL.value not in adapters

    def test_email_adapter_not_created_when_credentials_missing(self) -> None:
        """Email adapter is not created when SMTP credentials are missing."""
        settings = Settings(smtp_host="")  # Missing host

        # Effective settings with Email gate ON
        effective_settings = [
            EffectiveSetting(
                key="notification.channels.email.enabled",
                value=True,
                source=SettingSource.DATABASE.value,
                editable=True,
                restart_required=False,
            ),
        ]

        facade = ObservabilityFacade(engine=None, settings=settings)
        adapters = facade.alert_delivery_adapters(settings, effective_settings)

        assert Channel.EMAIL.value not in adapters

    def test_email_adapter_not_created_when_gate_on_but_some_credentials_missing(self) -> None:
        """Email adapter is not created when gate is ON but some credentials are missing."""
        settings = Settings(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="user@example.com",
            smtp_password="",  # Missing password
            smtp_from="alerts@example.com",
            smtp_to="ops@example.com",
        )

        effective_settings = [
            EffectiveSetting(
                key="notification.channels.email.enabled",
                value=True,
                source=SettingSource.DATABASE.value,
                editable=True,
                restart_required=False,
            ),
        ]

        facade = ObservabilityFacade(engine=None, settings=settings)
        adapters = facade.alert_delivery_adapters(settings, effective_settings)

        assert Channel.EMAIL.value not in adapters

    def test_email_adapter_created_when_gate_on_and_all_credentials_present(self) -> None:
        """Email adapter is created when gate is ON and all credentials are present."""
        settings = Settings(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="user@example.com",
            smtp_password="secret",
            smtp_from="alerts@example.com",
            smtp_to="ops@example.com",
        )

        effective_settings = [
            EffectiveSetting(
                key="notification.channels.email.enabled",
                value=True,
                source=SettingSource.DATABASE.value,
                editable=True,
                restart_required=False,
            ),
        ]

        facade = ObservabilityFacade(engine=None, settings=settings)
        adapters = facade.alert_delivery_adapters(settings, effective_settings)

        assert Channel.EMAIL.value in adapters
        assert isinstance(adapters[Channel.EMAIL.value], SmtpAdapter)

    def test_email_adapter_not_created_when_no_effective_settings_provided(self) -> None:
        """Email adapter not created when no effective settings (defaults to gate OFF)."""
        settings = Settings(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="user@example.com",
            smtp_password="secret",
            smtp_from="alerts@example.com",
            smtp_to="ops@example.com",
        )

        facade = ObservabilityFacade(engine=None, settings=settings)
        adapters = facade.alert_delivery_adapters(settings, effective_settings=None)

        assert Channel.EMAIL.value not in adapters

    def test_email_adapter_handles_comma_separated_recipients(self) -> None:
        """Email adapter handles comma-separated recipient string."""
        settings = Settings(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="user@example.com",
            smtp_password="secret",
            smtp_from="alerts@example.com",
            smtp_to="ops1@example.com, ops2@example.com, ops3@example.com",
        )

        effective_settings = [
            EffectiveSetting(
                key="notification.channels.email.enabled",
                value=True,
                source=SettingSource.DATABASE.value,
                editable=True,
                restart_required=False,
            ),
        ]

        facade = ObservabilityFacade(engine=None, settings=settings)
        adapters = facade.alert_delivery_adapters(settings, effective_settings)

        assert Channel.EMAIL.value in adapters
        adapter = adapters[Channel.EMAIL.value]
        assert isinstance(adapter, SmtpAdapter)
        assert adapter._to_addrs == ["ops1@example.com", "ops2@example.com", "ops3@example.com"]


class TestDeliveryCoreWithEmailChannel:
    """Tests for the delivery core using the email channel."""

    @pytest.mark.asyncio
    async def test_delivery_core_uses_email_channel_when_enabled(
        self,
    ) -> None:
        """Delivery core routes to email when channel is enabled."""
        settings = Settings(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="user@example.com",
            smtp_password="secret",
            smtp_from="alerts@example.com",
            smtp_to="ops@example.com",
            alert_delivery_enabled=True,
        )

        effective_settings = [
            EffectiveSetting(
                key="notification.channels.email.enabled",
                value=True,
                source=SettingSource.DATABASE.value,
                editable=True,
                restart_required=False,
            ),
            EffectiveSetting(
                key="notification.routing.test_alert",
                value="email",
                source=SettingSource.DATABASE.value,
                editable=True,
                restart_required=False,
            ),
        ]

        facade = ObservabilityFacade(engine=None, settings=settings)
        adapters = facade.alert_delivery_adapters(settings, effective_settings)

        assert Channel.EMAIL.value in adapters
        assert adapters[Channel.EMAIL.value].channel_name == "email"

    @pytest.mark.asyncio
    async def test_delivery_core_noop_when_email_gate_off(
        self,
    ) -> None:
        """Delivery core no-ops for email when gate is off."""
        settings = Settings(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="user@example.com",
            smtp_password="secret",
            smtp_from="alerts@example.com",
            smtp_to="ops@example.com",
            alert_delivery_enabled=True,
        )

        effective_settings = [
            EffectiveSetting(
                key="notification.channels.email.enabled",
                value=False,
                source=SettingSource.DEFAULT.value,
                editable=True,
                restart_required=False,
            ),
            EffectiveSetting(
                key="notification.routing.test_alert",
                value="email",
                source=SettingSource.DATABASE.value,
                editable=True,
                restart_required=False,
            ),
        ]

        facade = ObservabilityFacade(engine=None, settings=settings)
        adapters = facade.alert_delivery_adapters(settings, effective_settings)

        # Gate is off, so no email adapter should be created
        assert Channel.EMAIL.value not in adapters


class TestFakeAdapterForEmail:
    """Tests that FakeAdapter works for email channel testing."""

    def test_fake_adapter_works_for_testing(self) -> None:
        """FakeAdapter can be used for testing without real SMTP calls."""
        adapter = FakeAdapter()

        alert = AlertRow(
            id="00000000-0000-0000-0000-000000000000",
            severity="warning",
            kind="test_alert",
            title="Test Alert",
            payload={"key": "value"},
            status="open",
            created_at=None,
        )

        result = asyncio.run(adapter.send(alert, "https://console.example.com/alerts/123"))

        assert result.success is True
        assert result.response == {"fake": True}
        assert len(adapter.sent_alerts) == 1
        assert adapter.sent_alerts[0][0] == alert


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
