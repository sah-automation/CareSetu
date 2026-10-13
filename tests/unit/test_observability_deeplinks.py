"""C1b #707: the deep-link derivations over the vendor Settings.

Pure functions over configuration - no database, no network - so every URL shape
and every "vendor not configured" branch is pinned here rather than against a
deployment (error-handling-observability.md §5, coding-standards §2).

The two properties that matter operationally: an unconfigured vendor yields an
ABSENT link rather than an error, and nothing derived from ``SENTRY_DSN``
carries the DSN's key half back out.
"""

from __future__ import annotations

import pytest

from modules.observability.domain.deeplinks import grafana_link, langfuse_link, sentry_link

_GRAFANA = "https://caresetu.grafana.net"
_LANGFUSE_HOST = "https://us.cloud.langfuse.com"
_LANGFUSE_KEY = "pk-lf-1234"
_SENTRY_DSN = "https://abc123def456@o4242.ingest.us-central1.sentry.io/7654321"


# ------------------------------------------------------------------ grafana


def test_grafana_link_is_the_configured_base() -> None:
    assert grafana_link(_GRAFANA) == _GRAFANA


def test_grafana_link_drops_a_trailing_slash_so_paths_append_cleanly() -> None:
    assert grafana_link(f"{_GRAFANA}/") == _GRAFANA


@pytest.mark.parametrize("configured", [None, "", "   "])
def test_unconfigured_grafana_is_an_absent_link(configured: str | None) -> None:
    assert grafana_link(configured) is None


# ------------------------------------------------------------------- sentry


def test_sentry_link_names_the_orgs_issues_view() -> None:
    assert sentry_link(_SENTRY_DSN) == "https://o4242.sentry.io/issues/?project=7654321"


def test_sentry_link_never_echoes_the_dsn_key_half() -> None:
    assert "abc123def456" not in (sentry_link(_SENTRY_DSN) or "")


@pytest.mark.parametrize("configured", [None, "", "   "])
def test_unconfigured_sentry_is_an_absent_link(configured: str | None) -> None:
    assert sentry_link(configured) is None


@pytest.mark.parametrize(
    "dsn",
    [
        "not-a-url",
        "https://key@o1.ingest.sentry.io",  # no project id
        "sentry.example.com/key@o1.ingest.sentry.io/9",  # no scheme
        "https://key@sentry.example.com/9",  # self-hosted: no numeric org
        "https://key@ingest.us-central1.sentry.io/9",  # host with no org segment
    ],
)
def test_an_unparseable_sentry_dsn_is_an_absent_link_not_a_guess(dsn: str) -> None:
    assert sentry_link(dsn) is None


# ----------------------------------------------------------------- langfuse


def test_langfuse_link_names_the_project_view() -> None:
    assert (
        langfuse_link(_LANGFUSE_HOST, _LANGFUSE_KEY) == f"{_LANGFUSE_HOST}/project/{_LANGFUSE_KEY}"
    )


def test_langfuse_link_drops_a_trailing_slash_on_the_host() -> None:
    assert (
        langfuse_link(f"{_LANGFUSE_HOST}/", _LANGFUSE_KEY)
        == f"{_LANGFUSE_HOST}/project/{_LANGFUSE_KEY}"
    )


@pytest.mark.parametrize(
    "host,key", [(None, _LANGFUSE_KEY), (_LANGFUSE_HOST, None), ("", ""), (None, None)]
)
def test_a_half_configured_langfuse_is_an_absent_link(host: str | None, key: str | None) -> None:
    """``Settings`` refuses a half key pair; a half pair here is still no link."""
    assert langfuse_link(host, key) is None
