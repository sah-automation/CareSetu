"""DEPLOY-3 (#114): idempotent demo-data seed.

Runnable as ``python -m scripts.seed_demo`` from ``apps/backend`` against a
migrated database (deployment plan 4.4). ``deploy.yml`` runs it after
``alembic upgrade head`` so a fresh Supabase database is demo-ready (plan 6.1).

The seed ensures the demo identity for ``+919000000001`` exists - registering
it through the iam facade's begin-or-resume path when missing, a no-op when
present. Repeated or concurrent runs converge on exactly one identity row
because ``register_patient`` inserts with ``ON CONFLICT DO NOTHING`` on the
unique ``phone_e164`` index and re-reads the winner, never SELECT-then-INSERT
(duplicate resolution, spec #51 §2.3). It then prints the demo phone and which
OTP surface is enabled (mock OTP read-back enabled vs not).

This is a demo convenience, not a load-bearing path: it resolves ``Settings``
from the environment (``DATABASE_URL`` is the Supabase direct connection string
on the deploy path, the localhost dev database by default) and constructs the
facade with the mock SMS adapter - never the provider adapter, whatever
``SMS_PROVIDER`` says - so the OTP issuance's background delivery is harmless
in-process. It fails loudly on errors: a message on stderr and a non-zero exit
so the deploy pipeline that runs it after migrations notices a broken database.
The delivery queue is flushed before exit so no background send is left pending
when the run loop closes.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings, get_settings
from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.facade import IamFacade

DEMO_PHONE_E164 = "+919000000001"


def describe_otp_surface(settings: Settings) -> str:
    """One line naming the OTP surface a demo of ``settings`` exposes.

    Mirrors ``Settings.mock_otp_readback_enabled``: the read-back route is the
    surface the demo banner consumes (deployment plan 4.3/4.6), so the seed
    reports whether it answers - and, when it does not, which setting combo
    turned it off.
    """
    if settings.mock_otp_readback_enabled:
        return "mock OTP read-back enabled (demo banner will show the code)"
    provider = settings.sms_provider.strip().lower()
    return (
        "mock OTP read-back disabled: check SMS_PROVIDER / APP_ENVIRONMENT / "
        "DEMO_MODE "
        f"(got sms_provider={provider!r}, app_environment={settings.app_environment!r})"
    )


def format_summary(phone_e164: str, otp_surface: str) -> str:
    """The seed's stdout, one field per line, ready to print."""
    return f"demo phone: {phone_e164}\notp surface: {otp_surface}"


async def _seed(settings: Settings) -> tuple[str, str]:
    """Ensure the demo identity exists and report the OTP surface.

    Returns ``(phone_e164, otp_surface)``: the normalized demo phone as stored
    and the description of which OTP surface is enabled. The engine is always
    disposed, mirroring the worker composition root's lifecycle (worker/main.py).
    """
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        facade = IamFacade(engine=engine, sms_adapter=MockSmsAdapter())
        result = await facade.register_patient(DEMO_PHONE_E164)
        await facade.delivery_queue.flush()
        return result.phone_e164, describe_otp_surface(settings)
    finally:
        await engine.dispose()


def main() -> int:
    """Entrypoint for ``python -m scripts.seed_demo``; 0 on success.

    Fails loudly on errors: any failure - bad settings, an unreachable database,
    a refused register - is named on stderr and the process exits non-zero so a
    deploy pipeline that runs the seed after migrations notices a broken
    database.
    """
    try:
        settings = get_settings()
        phone_e164, otp_surface = asyncio.run(_seed(settings))
    except Exception as exc:
        print(f"demo seed failed: {exc}", file=sys.stderr)
        return 1
    print(format_summary(phone_e164, otp_surface))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
