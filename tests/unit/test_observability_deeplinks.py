"""C1b #707: the deep-link derivations over the vendor Settings.

Pure functions over configuration - no database, no network - so every URL shape
and every "vendor not configured" branch is pinned here rather than against a
deployment (error-handling-observability.md §5, coding-standards §2).

The three properties that matter operationally: an unconfigured vendor yields an
ABSENT link rather than an error, nothing derived from ``SENTRY_DSN`` carries the
DSN's key half back out, and the concurrency link names the metric the platform
actually records - so an operator who clicks it lands on a signal, not on an empty
query.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, unquote

import pytest

from modules.observability.domain.deeplinks import (
    grafana_link,
    grafana_metric_link,
    langfuse_link,
    sentry_link,
)
from observability.otel import HTTP_INFLIGHT_METRIC

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


# ------------------------------------------------------ grafana metric (B5 #729)


def _explore_payload(link: str) -> dict[str, object]:
    """The decoded ``left`` pane Grafana's Explore reads."""
    left = parse_qs(link.split("?", 1)[1])["left"][0]
    payload: dict[str, object] = json.loads(unquote(left))
    return payload


def test_the_concurrency_link_is_an_explore_pane_filtered_to_the_recorded_metric() -> None:
    """The link must reach the signal the platform records, not a metric of its own.

    True concurrency lives in the tracing backend, so this link is the whole of the
    answer. A URL naming a metric the backend never records would be a broken link
    on the one figure this read deliberately does NOT store.
    """
    link = grafana_metric_link(_GRAFANA)

    assert link is not None
    assert link.startswith(f"{_GRAFANA}/explore?left=")
    payload = _explore_payload(link)
    queries = payload["queries"]
    assert isinstance(queries, list)
    assert queries == [{"expr": HTTP_INFLIGHT_METRIC}]
    # A relative range, so the pane opens on the last hour rather than the epoch.
    assert payload["range"] == {"from": "now-1h", "to": "now"}
    # No datasource is hard-coded: Explore resolves the deployment's default, which
    # is the one receiving the platform's own metrics.
    assert "datasource" not in payload


def test_the_concurrency_link_defaults_to_the_inflight_gauge_and_honours_an_override() -> None:
    default = _explore_payload(grafana_metric_link(_GRAFANA) or "")
    override = _explore_payload(
        grafana_metric_link(_GRAFANA, metric="caresetu.http.server.duration", window="now-15m")
        or ""
    )

    assert default["queries"] == [{"expr": "caresetu.http.server.inflight"}]
    assert override["queries"] == [{"expr": "caresetu.http.server.duration"}]
    assert override["range"] == {"from": "now-15m", "to": "now"}


def test_the_concurrency_link_absorbs_a_trailing_slash_and_escapes_the_metric() -> None:
    link = grafana_metric_link(f"{_GRAFANA}/", metric="caresetu.http.server.inflight")

    assert link is not None
    assert link.startswith(f"{_GRAFANA}/explore?left=")
    # Percent-encoded: Grafana expects the pane payload encoded, and an unencoded
    # `{` in a query string is a URL a proxy may reject.
    assert "{" not in link.split("?left=", 1)[1]


@pytest.mark.parametrize("configured", [None, "", "   "])
def test_an_unconfigured_grafana_yields_no_concurrency_link(configured: str | None) -> None:
    assert grafana_metric_link(configured) is None


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
