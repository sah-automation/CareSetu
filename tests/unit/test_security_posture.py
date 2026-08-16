"""TEST-B2 (#136): boundary security posture gate - fixture tests.

Feeds ``scripts.security_posture`` crafted header maps, cipher names, and
URLs and asserts the acceptance criteria: HTTPS-only scheme enforcement,
TLS 1.2+ / legacy-refusal / cipher classification, HSTS with a meaningful
max-age, ``X-Content-Type-Options: nosniff``, and failure messages that name
the failing check with its observed value. No network is touched - the live
probe functions are exercised only via their pure helpers here.
"""

from __future__ import annotations

import importlib.util
import ssl
import sys
import warnings
from pathlib import Path

import pytest

POSTURE_FILE = Path(__file__).resolve().parents[2] / "scripts" / "security_posture.py"


def _load_posture():
    """Import ``scripts/security_posture.py`` by file location.

    The root ``scripts/`` directory is not a Python package (``scripts``
    resolves to ``apps/backend/scripts``), so - like ``test_contract_check`` -
    the module is loaded from its path directly.
    """
    spec = importlib.util.spec_from_file_location("security_posture", POSTURE_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


posture = _load_posture()

CheckResult = posture.CheckResult
check_response_headers = posture.check_response_headers
check_target = posture.check_target
is_legacy_cipher = posture.is_legacy_cipher
main = posture.main


def _labels(results: tuple[CheckResult, ...]) -> set[str]:
    return {result.label for result in results}


def _failures(results: tuple[CheckResult, ...]) -> tuple[CheckResult, ...]:
    return tuple(result for result in results if not result.ok)


# ---------------------------------------------------------------------------
# Response-header assertions
# ---------------------------------------------------------------------------


def test_missing_both_headers_fails_with_observed_absent() -> None:
    results = check_response_headers({})

    failed = _failures(results)
    assert {result.label for result in failed} == {
        "HSTS (Strict-Transport-Security)",
        "X-Content-Type-Options",
    }
    assert all("observed: absent" in result.observed for result in failed)


def test_compliant_headers_pass() -> None:
    results = check_response_headers(
        {
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "X-Content-Type-Options": "nosniff",
        }
    )

    assert _failures(results) == ()


def test_hsts_max_age_below_floor_fails_naming_the_value() -> None:
    results = check_response_headers(
        {
            "Strict-Transport-Security": "max-age=60; includeSubDomains",
            "X-Content-Type-Options": "nosniff",
        }
    )

    failed = _failures(results)
    assert [result.label for result in failed] == ["HSTS (Strict-Transport-Security)"]
    assert "max-age=60" in failed[0].observed


def test_hsts_without_max_age_fails() -> None:
    results = check_response_headers(
        {
            "Strict-Transport-Security": "includeSubDomains",
            "X-Content-Type-Options": "nosniff",
        }
    )

    assert any(not result.ok for result in results if result.label.startswith("HSTS"))


def test_xcto_wrong_value_fails_naming_the_value() -> None:
    results = check_response_headers(
        {
            "Strict-Transport-Security": "max-age=31536000",
            "X-Content-Type-Options": "sniff",
        }
    )

    failed = _failures(results)
    assert [result.label for result in failed] == ["X-Content-Type-Options"]
    assert "sniff" in failed[0].observed


def test_headers_are_read_case_insensitively() -> None:
    results = check_response_headers(
        {
            "strict-transport-security": "max-age=31536000",
            "x-content-type-options": "NOSNIFF",
        }
    )

    assert _failures(results) == ()


# ---------------------------------------------------------------------------
# Cipher classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cipher",
    [
        "TLS_NULL_WITH_NULL_NULL",
        "ECDHE-RSA-RC4-SHA",
        "TLS_ECDHE_RSA_WITH_3DES_EDE_CBC_SHA",
        "EXP-RC4-MD5",
    ],
)
def test_legacy_ciphers_are_flagged(cipher: str) -> None:
    assert is_legacy_cipher(cipher)


@pytest.mark.parametrize(
    "cipher",
    [
        "TLS_AES_256_GCM_SHA384",
        "TLS_AES_128_GCM_SHA256",
        "ECDHE-ECDSA-AES128-GCM-SHA256",
        "ECDHE-RSA-AES256-GCM-SHA384",
    ],
)
def test_modern_aead_ciphers_are_not_flagged(cipher: str) -> None:
    assert not is_legacy_cipher(cipher)


# ---------------------------------------------------------------------------
# Target-level checks
# ---------------------------------------------------------------------------


def test_non_https_scheme_hard_fails_without_probing() -> None:
    outcome = check_target("http://example.com/")

    assert outcome.reached is True
    assert not outcome.ok
    failed = _failures(outcome.results)
    assert [result.label for result in failed] == ["HTTPS only"]
    assert "http" in failed[0].observed
    assert "TLS" not in _labels(outcome.results)


def test_url_without_host_is_unavailable() -> None:
    outcome = check_target("https:///no-host")

    assert outcome.reached is False
    assert outcome.availability_error


def test_legacy_probe_context_only_speaks_tls_1_0_and_1_1() -> None:
    """Python 3.13 defaults to a TLSv1.2 floor and drops the legacy suites, so
    the refusal probe must re-open them or it can never reach the server."""

    context = posture._legacy_only_context()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert context.minimum_version == ssl.TLSVersion.TLSv1
        assert context.maximum_version == ssl.TLSVersion.TLSv1_1
    protocols = {cipher["protocol"] for cipher in context.get_ciphers()}
    assert protocols & {"TLSv1", "TLSv1.0"}


def test_probe_connection_failure_is_availability_not_a_hard_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def stub_probe(host: str, port: int, *, legacy_only: bool = False) -> tuple[str, str]:
        del host, port, legacy_only
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(posture, "_probe_tls", stub_probe)

    outcome = check_target("https://example.com/")

    assert outcome.reached is False
    assert outcome.availability_error


def test_legacy_probe_connection_failure_is_not_reported_as_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def stub_probe(host: str, port: int, *, legacy_only: bool = False) -> tuple[str, str]:
        del host, port
        if legacy_only:
            raise TimeoutError("legacy probe timed out")
        return "TLSv1.3", "TLS_AES_128_GCM_SHA256"

    monkeypatch.setattr(posture, "_probe_tls", stub_probe)

    outcome = check_target("https://example.com/")

    assert outcome.reached is False
    assert "handshake rejected" not in "".join(r.observed for r in outcome.results)


def test_check_target_assembles_a_pass_for_a_compliant_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def stub_probe(host: str, port: int, *, legacy_only: bool = False) -> tuple[str, str]:
        del host, port
        if legacy_only:
            raise ssl.SSLError("legacy refused")
        return "TLSv1.3", "TLS_AES_128_GCM_SHA256"

    monkeypatch.setattr(posture, "_probe_tls", stub_probe)
    monkeypatch.setattr(
        posture,
        "_fetch_response",
        lambda url: (
            200,
            {
                "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
                "X-Content-Type-Options": "nosniff",
            },
        ),
    )

    outcome = check_target("https://example.com/")

    assert outcome.reached is True
    assert outcome.ok is True
    assert {result.label for result in outcome.results} == {
        "HTTPS only",
        "TLS >= 1.2",
        "no legacy/cleartext cipher",
        "legacy TLS (1.0/1.1) refused",
        "HTTP reachable",
        "HSTS (Strict-Transport-Security)",
        "X-Content-Type-Options",
    }


def test_check_target_reports_a_missing_header_as_hard_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def stub_probe(host: str, port: int, *, legacy_only: bool = False) -> tuple[str, str]:
        del host, port
        if legacy_only:
            raise ssl.SSLError("legacy refused")
        return "TLSv1.2", "ECDHE-ECDSA-AES128-GCM-SHA256"

    monkeypatch.setattr(posture, "_probe_tls", stub_probe)
    monkeypatch.setattr(posture, "_fetch_response", lambda url: (200, {}))

    outcome = check_target("https://example.com/")

    assert outcome.reached is True
    assert outcome.ok is False
    failed = {result.label for result in outcome.results if not result.ok}
    assert failed == {"HSTS (Strict-Transport-Security)", "X-Content-Type-Options"}


def test_main_reports_non_https_failure_fast() -> None:
    exit_code = main(
        [
            "--backend-url",
            "http://localhost:8000",
            "--frontend-url",
            "http://localhost:8000",
            "--no-retry",
        ]
    )

    assert exit_code == 1


def test_main_retries_an_unavailable_target_until_it_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry window is the script's tolerance for a deploy in flight / cold
    start: a target that answers unavailable at first must be re-asked within
    the window, and a recovered target lets the gate succeed."""

    monkeypatch.setattr(posture, "RETRY_WINDOW_SECONDS", 1.0)
    monkeypatch.setattr(posture, "RETRY_POLL_SECONDS", 0.01)
    calls: list[int] = []

    def flaky_attempt(urls: list[str]) -> list:
        del urls
        calls.append(1)
        if len(calls) < 3:
            return [
                posture.TargetOutcome(
                    url="https://example.com/",
                    reached=False,
                    results=(),
                    availability_error="connection refused",
                )
            ]
        return [
            posture.TargetOutcome(
                url="https://example.com/",
                reached=True,
                results=(
                    posture._pass("HTTPS only", "https"),
                    posture._pass("HSTS (Strict-Transport-Security)", "max-age=31536000"),
                    posture._pass("X-Content-Type-Options", "nosniff"),
                ),
            )
        ]

    monkeypatch.setattr(posture, "_attempt", flaky_attempt)

    exit_code = main(
        ["--backend-url", "https://example.com/", "--frontend-url", "https://example.com/"]
    )

    assert exit_code == 0
    assert len(calls) == 3
