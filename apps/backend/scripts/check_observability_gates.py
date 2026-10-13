"""PHASE-14A E (#712): CI boot-smoke for the observability vendor gates.

Every Phase-14A vendor integration (structlog JSON logging, Sentry, the OTel
SDK for traces + metrics, and Langfuse) is env-gated, and the plan's safety rule
is that each is a **no-op when unconfigured** while still booting cleanly when
configured (plan-phase14-observability §4, Appendix A.2). The configured path is
easy to keep green because someone exercises it; the no-op path is the one that
quietly rots - an unconditional SDK import, a module-level global mutated at
import, or a shutdown flush that assumes a client.

``ci.yml`` runs this twice, once with every gate off (the default posture) and
once with them on (dummy endpoints), so both ends of every gate are exercised on
each CI run. The smoke imports the real composition root (``create_app`` wires
structlog + OTel), drives the ASGI lifespan through an in-process client (which
wires Sentry + Langfuse and runs the shutdown flushes), and serves
``GET /health``. It needs no database: the engine is lazy and ``/health``
touches nothing.

Exit 0 only when the app boots, answers, and shuts down under the configured
gates; a boot-time exception or a non-200 ``/health`` fails the job.
"""

from __future__ import annotations

import sys

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app


def _gate_posture(settings: Settings) -> dict[str, object]:
    """The resolved on/off state of each gate, for the CI log."""
    endpoint = settings.otel_exporter_otlp_endpoint.strip()
    return {
        "log_format": settings.log_format,
        "sentry": bool(settings.sentry_dsn.strip()),
        "otel_traces": settings.otel_enabled and bool(endpoint),
        "otel_metrics": settings.metrics_enabled and bool(endpoint),
        "langfuse": bool(settings.langfuse_public_key.strip()),
        "observability": settings.observability_enabled,
    }


def main() -> int:
    settings: Settings = app.state.settings
    print(f"observability gate boot-smoke: {_gate_posture(settings)}")

    # The context manager drives the ASGI lifespan, so Sentry + Langfuse are
    # wired on entry and the exporter flushes run on exit - both ends of the
    # gate, not just the import-time half.
    with TestClient(app) as client:
        response = client.get("/health")

    if response.status_code != 200 or response.json().get("status") != "ok":
        print(
            f"FAILED: GET /health -> {response.status_code} {response.text}",
            file=sys.stderr,
        )
        return 1

    print("observability gate boot-smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
