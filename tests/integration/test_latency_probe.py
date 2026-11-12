"""LAT-HARNESS (#901): the probe end-to-end against the in-process application.

Boots the real app (real routes, real database, JWT verify on, the opt-in
server-timing header on) under a real uvicorn server on an ephemeral localhost
port, then drives the probe exactly as a developer would: one run through
``main`` asserting the zero exit code and the reported table (user stories 1
and 4), and one run through ``demo_login`` + ``run_probe`` asserting the
per-endpoint p95 lands under a generous bound and the server-processing split
arrives (user stories 3 and 6). Needs the native PostgreSQL like the rest of
the integration suite; skips when it is unreachable.
"""

from __future__ import annotations

import importlib.util
import random
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from app.config import Settings
from app.main import create_app

_PROBE_FILE = Path(__file__).resolve().parents[2] / "scripts" / "measure_backend_latency.py"


def _load_probe():
    """Import ``scripts/measure_backend_latency.py`` by file location.

    The root ``scripts/`` directory is not a Python package - ``scripts``
    resolves to ``apps/backend/scripts`` (see ``test_contract_check.py``).
    """
    spec = importlib.util.spec_from_file_location("measure_backend_latency", _PROBE_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = _load_probe()
demo_login = probe.demo_login
main = probe.main
run_probe = probe.run_probe

_SIGNING_KEY = "latency-probe-integration-key"
_GENEROUS_P95_BOUND_MS = 5000.0
_SERVER_BOOT_TIMEOUT_SECONDS = 30.0


def _unique_phone() -> str:
    """A fresh 10-digit Indian mobile per run: no cooldown or lockout reuse."""
    return "9" + "".join(random.choices("0123456789", k=9))


@pytest.fixture(scope="module")
def probe_server(database_url: str, migrated_schema: None) -> Iterator[str]:
    """The real app under a real uvicorn server on an ephemeral localhost port.

    ``app_environment="test"`` arms the mock-OTP read-back the probe's demo
    login drives; ``server_timing_header_enabled=True`` arms the attribution
    header the probe parses. ``migrated_schema`` guarantees the shared
    database is at head while this module runs - without it the module would
    run outside any neighbor's migrate window and the schema could be at
    base. Module-scoped so the file boots one server.
    """
    application = create_app(
        settings=Settings(
            database_url=database_url,
            gateway_jwt_verify_enabled=True,
            gateway_jwt_signing_key=_SIGNING_KEY,
            app_environment="test",
            server_timing_header_enabled=True,
        )
    )
    server = uvicorn.Server(
        uvicorn.Config(application, host="127.0.0.1", port=0, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + _SERVER_BOOT_TIMEOUT_SECONDS
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("latency probe integration server failed to boot")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    server.should_exit = True
    thread.join(timeout=10)


def test_probe_main_exits_zero_and_reports_both_endpoints(
    probe_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "--backend-url",
            probe_server,
            "--iterations",
            "5",
            "--p95-threshold-ms",
            f"{_GENEROUS_P95_BOUND_MS}",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "/health" in output
    assert "/v1/me" in output
    assert "PASS" in output


def test_probe_reports_the_server_processing_split(probe_server: str) -> None:
    """The gate-on app answers with the timing header, so the split is real."""
    phone = _unique_phone()
    token = demo_login(probe_server, phone)

    results = run_probe(
        probe_server,
        ("/health", "/v1/me"),
        iterations=5,
        token=token,
    )

    assert len(results) == 2
    for stats in results:
        assert stats.status_failures == 0
        assert stats.count == 5
        assert stats.p95_ms < _GENEROUS_P95_BOUND_MS
        assert stats.server_p95_ms is not None
        assert 0.0 <= stats.server_p95_ms <= stats.p95_ms
        assert stats.endpoint in ("/health", "/v1/me")
