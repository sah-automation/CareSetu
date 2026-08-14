"""DEPLOY-3 (#114): idempotent demo seed - pure-logic coverage.

The no-op/converge behaviour (running the seed twice yields exactly one
identity row for ``+919000000001``) is proved by the two-run done-verify
against a scratch migrated database, because ``register_patient`` already
converges through the unique ``phone_e164`` index (brief, ticket #114). The
unit surface here stays on the script's pure logic - the OTP-surface
description and the printed summary - rather than faking the engine.
"""

from scripts.seed_demo import describe_otp_surface, format_summary

from app.config import Settings


def test_otp_surface_enabled_in_dev() -> None:
    assert "enabled" in describe_otp_surface(Settings(app_environment="dev"))


def test_otp_surface_enabled_under_demo_mode() -> None:
    assert "enabled" in describe_otp_surface(Settings(demo_mode=True))


def test_otp_surface_disabled_by_default() -> None:
    surface = describe_otp_surface(Settings())
    assert "disabled" in surface
    assert "DEMO_MODE" in surface


def test_otp_surface_disabled_for_real_provider() -> None:
    settings = Settings(
        sms_provider="provider",
        sms_api_key="test-key",
        sms_base_url="https://sms.test",
        app_environment="production",
    )
    assert "disabled" in describe_otp_surface(settings)


def test_summary_prints_phone_and_surface() -> None:
    summary = format_summary("+919000000001", "mock OTP read-back enabled")
    assert "demo phone: +919000000001" in summary
    assert "otp surface: mock OTP read-back enabled" in summary
