"""Tests for Slack alert delivery channel (#785)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from modules.observability.domain.alert_delivery import (
    AlertRow,
    Channel,
    DeliveryAttemptResult,
    FakeAdapter,
    SlackAdapter,
)
from modules.observability.facade import ObservabilityFacade
from modules.ops.domain.settings import EffectiveSetting, SettingSource


class TestSlackAdapter:
    """Tests for the SlackAdapter."""

    def test_slack_adapter_requires_valid_webhook_url(self) -> None:
        """Invalid webhook URL raises ValueError."""
        with pytest.raises(ValueError, match="Invalid Slack webhook URL"):
            SlackAdapter("")

        with pytest.raises(ValueError, match="Invalid Slack webhook URL"):
            SlackAdapter("not-a-url")

        with pytest.raises(ValueError, match="Invalid Slack webhook URL"):
            SlackAdapter("https://example.com/webhook")

    def test_slack_adapter_accepts_valid_webhook_url(self) -> None:
        """Valid Slack webhook URL is accepted."""
        test_url = "https://hooks.slack.com/services/TEST/TEST/TEST"
        adapter = SlackAdapter(test_url)
        assert adapter.channel_name == "slack"
        assert adapter._webhook_url == test_url

    @pytest.mark.asyncio
    async def test_slack_adapter_send_success(self) -> None:
        """Successful send returns DeliveryAttemptResult with success=True."""
        test_url = "https://hooks.slack.com/services/TEST/TEST/TEST"
        adapter = SlackAdapter(test_url)

        alert = AlertRow(
            id="00000000-0000-0000-0000-000000000000",
            severity="warning",
            kind="test_alert",
            title="Test Alert",
            payload={"key": "value"},
            status="open",
            created_at=None,
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_response = AsyncMock()
            mock_response.raise_for_status = lambda: None
            mock_response.json = AsyncMock(return_value={"ok": True})
            mock_response.content = b'{"ok": true}'
            mock_post.return_value = mock_response

            result = await adapter.send(alert, "https://console.example.com/alerts/123")

        assert isinstance(result, DeliveryAttemptResult)
        assert result.success is True
        assert result.response == {"ok": True}

    @pytest.mark.asyncio
    async def test_slack_adapter_send_failure_does_not_leak_webhook_url(self) -> None:
        """Failed send returns error without leaking the webhook URL."""
        test_url = "https://hooks.slack.com/services/TEST/TEST/TEST"
        adapter = SlackAdapter(test_url)

        alert = AlertRow(
            id="00000000-0000-0000-0000-000000000000",
            severity="warning",
            kind="test_alert",
            title="Test Alert",
            payload={"key": "value"},
            status="open",
            created_at=None,
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = Exception("connection refused")

            result = await adapter.send(alert, "https://console.example.com/alerts/123")

        assert isinstance(result, DeliveryAttemptResult)
        assert result.success is False
        # Error should not leak the webhook URL
        assert "https://hooks.slack.com" not in result.error
        assert "TEST" not in result.error


class TestAlertDeliveryAdapters:
    """Tests for the alert_delivery_adapters factory function."""

    def test_slack_adapter_not_created_when_gate_is_off(self) -> None:
        """Slack adapter is not created when notification.channels.slack.enabled is False."""
        test_url = "https://hooks.slack.com/services/TEST/TEST/TEST"
        settings = Settings(slack_webhook_url=test_url)

        # Effective settings with Slack gate OFF (default)
        effective_settings = [
            EffectiveSetting(
                key="notification.channels.slack.enabled",
                value=False,
                source=SettingSource.DEFAULT.value,
                editable=True,
                restart_required=False,
            ),
        ]

        facade = ObservabilityFacade(engine=None, settings=settings)
        adapters = facade.alert_delivery_adapters(settings, effective_settings)

        assert Channel.SLACK.value not in adapters

    def test_slack_adapter_not_created_when_webhook_url_missing(self) -> None:
        """Slack adapter is not created when webhook URL is missing."""
        settings = Settings(slack_webhook_url="")

        # Effective settings with Slack gate ON
        effective_settings = [
            EffectiveSetting(
                key="notification.channels.slack.enabled",
                value=True,
                source=SettingSource.DATABASE.value,
                editable=True,
                restart_required=False,
            ),
        ]

        facade = ObservabilityFacade(engine=None, settings=settings)
        adapters = facade.alert_delivery_adapters(settings, effective_settings)

        assert Channel.SLACK.value not in adapters

    def test_slack_adapter_created_when_gate_on_and_webhook_present(self) -> None:
        """Slack adapter is created when gate is ON and webhook URL is present."""
        test_url = "https://hooks.slack.com/services/TEST/TEST/TEST"
        settings = Settings(slack_webhook_url=test_url)

        effective_settings = [
            EffectiveSetting(
                key="notification.channels.slack.enabled",
                value=True,
                source=SettingSource.DATABASE.value,
                editable=True,
                restart_required=False,
            ),
        ]

        facade = ObservabilityFacade(engine=None, settings=settings)
        adapters = facade.alert_delivery_adapters(settings, effective_settings)

        assert Channel.SLACK.value in adapters
        assert isinstance(adapters[Channel.SLACK.value], SlackAdapter)

    def test_slack_adapter_not_created_when_no_effective_settings_provided(self) -> None:
        """Slack adapter not created when no effective settings (defaults to gate OFF)."""
        test_url = "https://hooks.slack.com/services/TEST/TEST/TEST"
        settings = Settings(slack_webhook_url=test_url)

        facade = ObservabilityFacade(engine=None, settings=settings)
        adapters = facade.alert_delivery_adapters(settings, effective_settings=None)

        assert Channel.SLACK.value not in adapters

    def test_fake_adapter_works_for_testing(self) -> None:
        """FakeAdapter can be used for testing without real HTTP calls."""
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

        import asyncio

        result = asyncio.run(adapter.send(alert, "https://console.example.com/alerts/123"))

        assert result.success is True
        assert result.response == {"fake": True}
        assert len(adapter.sent_alerts) == 1
        assert adapter.sent_alerts[0][0] == alert


class TestDeliveryCoreWithSlackChannel:
    """Tests for the delivery core using the Slack channel."""

    @pytest.mark.asyncio
    async def test_delivery_core_uses_slack_channel_when_enabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Delivery core routes to Slack when channel is enabled."""

        from modules.observability.domain.alert_delivery import (
            Channel,
        )

        # This test would require a database engine and full setup
        # For unit testing, we verify the adapters dict includes Slack when enabled
        test_url = "https://hooks.slack.com/services/TEST/TEST/TEST"
        settings = Settings(
            slack_webhook_url=test_url,
            alert_delivery_enabled=True,
        )

        effective_settings = [
            EffectiveSetting(
                key="notification.channels.slack.enabled",
                value=True,
                source=SettingSource.DATABASE.value,
                editable=True,
                restart_required=False,
            ),
            EffectiveSetting(
                key="notification.routing.test_alert",
                value="slack",
                source=SettingSource.DATABASE.value,
                editable=True,
                restart_required=False,
            ),
        ]

        facade = ObservabilityFacade(engine=None, settings=settings)
        adapters = facade.alert_delivery_adapters(settings, effective_settings)

        assert Channel.SLACK.value in adapters
        assert adapters[Channel.SLACK.value].channel_name == "slack"

    @pytest.mark.asyncio
    async def test_delivery_core_noop_when_slack_gate_off(
        self,
    ) -> None:
        """Delivery core no-ops for Slack when gate is off."""
        test_url = "https://hooks.slack.com/services/TEST/TEST/TEST"
        settings = Settings(
            slack_webhook_url=test_url,
            alert_delivery_enabled=True,
        )

        effective_settings = [
            EffectiveSetting(
                key="notification.channels.slack.enabled",
                value=False,
                source=SettingSource.DEFAULT.value,
                editable=True,
                restart_required=False,
            ),
            EffectiveSetting(
                key="notification.routing.test_alert",
                value="slack",
                source=SettingSource.DATABASE.value,
                editable=True,
                restart_required=False,
            ),
        ]

        facade = ObservabilityFacade(engine=None, settings=settings)
        adapters = facade.alert_delivery_adapters(settings, effective_settings)

        # Gate is off, so no Slack adapter should be created
        assert Channel.SLACK.value not in adapters


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
