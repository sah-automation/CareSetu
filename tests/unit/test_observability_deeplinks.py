"""C1b #707, widened by B3 (#736): the deep-link derivations over the vendor Settings.

Pure functions over configuration - no database, no network - so every URL shape
and every "vendor not configured" branch is pinned here rather than against a
deployment (error-handling-observability.md §5, coding-standards §2).

The properties that matter operationally: an unconfigured vendor yields an ABSENT
link rather than an error; nothing derived from ``SENTRY_DSN`` carries the DSN's key
half back out; the concurrency link names the metric the platform actually records -
so an operator who clicks it lands on a signal, not on an empty query; and after
#736 **every link carries its filter**, because a bare base URL is the thing this
read stopped returning.
"""

from __future__ import annotations

import json
from typing import get_args
from urllib.parse import parse_qs, unquote
from uuid import uuid4

import pytest

from modules.intake.domain.events import AiTaskType
from modules.observability.domain.deeplinks import (
    DEFAULT_GRAFANA_WINDOW,
    LANGFUSE_SPAN_NAMES,
    MAX_TRACE_ID_LENGTH,
    clean_trace_id,
    grafana_dashboard_link,
    grafana_explore_link,
    grafana_link,
    grafana_metric_link,
    langfuse_actor_link,
    langfuse_session_link,
    langfuse_trace_link,
    langfuse_traces_link,
    sentry_issues_link,
    sentry_trace_link,
)
from observability.otel import HTTP_INFLIGHT_METRIC

_GRAFANA = "https://caresetu.grafana.net"
_LANGFUSE_HOST = "https://us.cloud.langfuse.com"
_LANGFUSE_KEY = "pk-lf-1234"
_SENTRY_DSN = "https://abc123def456@o4242.ingest.us-central1.sentry.io/7654321"
_TRACE = "c7f2a1b0d3e4f5061728394a5b6c7d8e"


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


def test_the_sentry_link_is_prefiltered_to_this_service() -> None:
    """An operator must not have to rebuild the query to reach their own errors."""
    link = sentry_issues_link(_SENTRY_DSN, service="caresetu-api")

    assert link is not None
    assert link.startswith("https://o4242.sentry.io/issues/?project=7654321&query=")
    assert parse_qs(link.split("?", 1)[1])["query"] == ['service:"caresetu-api"']


def test_the_sentry_link_narrows_further_to_the_error_type_it_was_asked_for() -> None:
    link = sentry_issues_link(_SENTRY_DSN, service="caresetu-api", error_type="ValueError")

    assert link is not None
    assert parse_qs(link.split("?", 1)[1])["query"] == [
        'service:"caresetu-api" error.type:"ValueError"'
    ]


def test_a_sentry_link_with_no_service_is_absent_rather_than_bare() -> None:
    """A link that cannot carry its filter is no link - that is the #736 rule."""
    assert sentry_issues_link(_SENTRY_DSN, service="") is None
    assert sentry_issues_link(_SENTRY_DSN, service="   ") is None


def test_the_sentry_trace_link_searches_the_trace_id_tag_the_platform_stamps() -> None:
    """The join key has to be the platform's OWN trace id, or the search finds nothing."""
    link = sentry_trace_link(_SENTRY_DSN, trace_id=_TRACE)

    assert link is not None
    assert parse_qs(link.split("?", 1)[1])["query"] == [f'trace_id:"{_TRACE}"']


def test_no_sentry_link_without_a_trace_to_search_for() -> None:
    assert sentry_trace_link(_SENTRY_DSN, trace_id=None) is None


def test_an_openai_compatible_model_id_keeps_its_langfuse_view() -> None:
    """``openai/gpt-4o`` carries a slash, and refusing it would drop a real link.

    The path rule forbids a slash because a path segment must not navigate; a query
    filter is percent-encoded instead, so it may carry one.
    """
    link = langfuse_traces_link(_LANGFUSE_HOST, _LANGFUSE_KEY, model="openai/gpt-4o")

    assert link is not None
    assert parse_qs(link.split("?", 1)[1])["model"] == ["openai/gpt-4o"]


def test_the_langfuse_trace_link_cannot_be_walked_backwards() -> None:
    """``..`` survives a URL-safe charset and ``quote`` leaves a dot alone."""
    assert langfuse_trace_link(_LANGFUSE_HOST, _LANGFUSE_KEY, trace_id="..") is None
    assert langfuse_trace_link(_LANGFUSE_HOST, _LANGFUSE_KEY, trace_id=".") is None


def test_a_filter_value_cannot_close_a_sentry_search_term() -> None:
    """The filter lands in a quoted Sentry value, so a quote in it must not survive."""
    assert sentry_issues_link(_SENTRY_DSN, service='api" OR project:1') is None
    assert sentry_issues_link(_SENTRY_DSN, service="api service:2") is None


def test_the_sentry_link_never_echoes_the_dsn_key_half() -> None:
    assert "abc123def456" not in (sentry_issues_link(_SENTRY_DSN, service="caresetu-api") or "")


@pytest.mark.parametrize("configured", [None, "", "   "])
def test_unconfigured_sentry_is_an_absent_link(configured: str | None) -> None:
    assert sentry_issues_link(configured, service="caresetu-api") is None
    assert sentry_trace_link(configured, trace_id=_TRACE) is None


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
    assert sentry_issues_link(dsn, service="caresetu-api") is None
    assert sentry_trace_link(dsn, trace_id=_TRACE) is None


# ----------------------------------------------------------------- langfuse


def test_the_langfuse_traces_view_is_filtered_by_model_and_task() -> None:
    link = langfuse_traces_link(_LANGFUSE_HOST, _LANGFUSE_KEY, model="gpt-4o", task_type="draft")

    assert link is not None
    assert link.startswith(f"{_LANGFUSE_HOST}/project/{_LANGFUSE_KEY}/traces?")
    assert parse_qs(link.split("?", 1)[1]) == {
        "model": ["gpt-4o"],
        # ``draft`` records under ``ai_draft_rx`` - the name its ``@observe`` span
        # carries, NOT the task type verbatim, which would find nothing.
        "name": ["ai_draft_rx"],
    }


def test_a_single_filter_is_enough_to_make_the_view_a_filtered_one() -> None:
    by_model = langfuse_traces_link(_LANGFUSE_HOST, _LANGFUSE_KEY, model="gpt-4o")
    by_task = langfuse_traces_link(_LANGFUSE_HOST, _LANGFUSE_KEY, task_type="structure")

    assert by_model is not None and "model=gpt-4o" in by_model
    assert by_task is not None and "name=ai_structure" in by_task


def test_a_langfuse_view_with_no_filter_is_absent_rather_than_bare() -> None:
    assert langfuse_traces_link(_LANGFUSE_HOST, _LANGFUSE_KEY) is None


def test_the_span_name_table_covers_real_task_types_and_real_span_names() -> None:
    """The mapping is the link's only route to the matching traces, so it is pinned.

    Every key has to be a task type the platform actually declares, and every value
    a span name an adapter's ``@observe`` actually writes - a value that drifts from
    the span turns this link into a search for nothing.
    """
    assert set(LANGFUSE_SPAN_NAMES) <= set(get_args(AiTaskType))
    assert set(LANGFUSE_SPAN_NAMES.values()) == {
        "ai_transcribe",
        "ai_structure",
        "ai_draft_rx",
    }


def test_a_task_with_no_observed_span_still_lands_on_the_model_it_was_looking_at() -> None:
    """``summarize`` is a declared task type with no ``@observe`` span yet.

    Inventing a span name for it would search for a span nobody writes, so the link
    keeps the model filter and names no span: it lands on the model's traces, which
    is an answer, rather than on an empty result set.
    """
    link = langfuse_traces_link(
        _LANGFUSE_HOST, _LANGFUSE_KEY, model="gpt-4o", task_type="summarize"
    )

    assert link is not None
    assert parse_qs(link.split("?", 1)[1]) == {"model": ["gpt-4o"]}


def test_the_langfuse_trace_link_is_the_single_trace_view() -> None:
    assert (
        langfuse_trace_link(_LANGFUSE_HOST, _LANGFUSE_KEY, trace_id=_TRACE)
        == f"{_LANGFUSE_HOST}/project/{_LANGFUSE_KEY}/trace/{_TRACE}"
    )


def test_the_langfuse_actor_and_session_views_filter_on_the_platforms_own_keys() -> None:
    actor = langfuse_actor_link(_LANGFUSE_HOST, _LANGFUSE_KEY, actor_key="a" * 64)
    session = langfuse_session_link(_LANGFUSE_HOST, _LANGFUSE_KEY, session_key="b" * 64)

    assert actor == f"{_LANGFUSE_HOST}/project/{_LANGFUSE_KEY}/users?userId={'a' * 64}"
    assert session == f"{_LANGFUSE_HOST}/project/{_LANGFUSE_KEY}/sessions?sessionId={'b' * 64}"


@pytest.mark.parametrize("context", [None, "", "   "])
def test_the_langfuse_trace_link_needs_a_trace(context: str | None) -> None:
    assert langfuse_trace_link(_LANGFUSE_HOST, _LANGFUSE_KEY, trace_id=context) is None


@pytest.mark.parametrize("context", [None, "", "   "])
def test_the_langfuse_actor_link_needs_an_actor_key(context: str | None) -> None:
    assert langfuse_actor_link(_LANGFUSE_HOST, _LANGFUSE_KEY, actor_key=context) is None


@pytest.mark.parametrize("context", [None, "", "   "])
def test_the_langfuse_session_link_needs_a_session_key(context: str | None) -> None:
    assert langfuse_session_link(_LANGFUSE_HOST, _LANGFUSE_KEY, session_key=context) is None


def test_langfuse_links_drop_a_trailing_slash_on_the_host() -> None:
    assert langfuse_traces_link(f"{_LANGFUSE_HOST}/", _LANGFUSE_KEY, model="gpt-4o") == (
        f"{_LANGFUSE_HOST}/project/{_LANGFUSE_KEY}/traces?model=gpt-4o"
    )


@pytest.mark.parametrize(
    "host,key",
    [(None, _LANGFUSE_KEY), (_LANGFUSE_HOST, None), ("", ""), (None, None)],
)
def test_a_half_configured_langfuse_is_an_absent_link(host: str | None, key: str | None) -> None:
    """``Settings`` refuses a half key pair; a half pair here is still no link."""
    assert langfuse_traces_link(host, key, model="gpt-4o") is None
    assert langfuse_trace_link(host, key, trace_id=_TRACE) is None
    assert langfuse_actor_link(host, key, actor_key="a" * 64) is None
    assert langfuse_session_link(host, key, session_key="b" * 64) is None


# ------------------------------------------------------ grafana dashboard (#736)


def test_the_dashboard_link_lands_on_the_dashboard_with_its_range_and_variables_set() -> None:
    """The whole point of #736: not a blank canvas, not a bare base URL."""
    link = grafana_dashboard_link(
        _GRAFANA, service="caresetu-api", environment="production", window="now-24h"
    )

    assert link is not None
    assert link.startswith(f"{_GRAFANA}/d/caresetu-observability/caresetu-observability?")
    assert parse_qs(link.split("?", 1)[1]) == {
        "from": ["now-24h"],
        "to": ["now"],
        "var-service": ["caresetu-api"],
        "var-env": ["production"],
    }


def test_the_dashboard_link_still_names_a_range_when_there_are_no_variables() -> None:
    """A relative range is a filter too - the pane must never open on the epoch."""
    link = grafana_dashboard_link(_GRAFANA)

    assert link is not None
    assert parse_qs(link.split("?", 1)[1]) == {"from": ["now-6h"], "to": ["now"]}


def test_the_dashboard_link_hardcodes_no_organisation() -> None:
    """An org id guessed into the URL would send one operator to another org's stack."""
    link = grafana_dashboard_link(_GRAFANA, service="caresetu-api")

    assert link is not None
    assert "orgId" not in link


def test_a_window_the_platform_cannot_read_falls_back_rather_than_being_passed_through() -> None:
    """A range expression is neither quoted nor escape-proof, so it is not trusted."""
    dashboard = grafana_dashboard_link(_GRAFANA, window='now-6h"} or epoch')
    explore = grafana_explore_link(_GRAFANA, trace_id=_TRACE, window="now-6h or epoch")

    assert dashboard is not None
    assert parse_qs(dashboard.split("?", 1)[1])["from"] == [DEFAULT_GRAFANA_WINDOW]
    assert _explore_payload(explore or "")["range"] == {
        "from": DEFAULT_GRAFANA_WINDOW,
        "to": "now",
    }


@pytest.mark.parametrize("configured", [None, "", "   "])
def test_an_unconfigured_grafana_has_no_dashboard(configured: str | None) -> None:
    assert grafana_dashboard_link(configured, service="caresetu-api") is None


# ----------------------------------------------------- grafana explore (#736)


def test_the_explore_link_carries_the_platforms_own_trace_id() -> None:
    """A reconstructed id would land on an empty trace, so the id must survive intact."""
    link = grafana_explore_link(_GRAFANA, trace_id=_TRACE)

    assert link is not None
    assert link.startswith(f"{_GRAFANA}/explore?left=")
    payload = _explore_payload(link)
    assert payload["traceId"] == _TRACE
    assert payload["range"] == {"from": "now-6h", "to": "now"}


def test_there_is_no_explore_pane_without_a_trace() -> None:
    assert grafana_explore_link(_GRAFANA, trace_id=None) is None


@pytest.mark.parametrize("configured", [None, "", "   "])
def test_an_unconfigured_grafana_has_no_explore_pane(configured: str | None) -> None:
    assert grafana_explore_link(configured, trace_id=_TRACE) is None


# --------------------------------------------------------- the trace id rule


def test_a_clean_trace_id_is_the_stored_one_unchanged() -> None:
    assert clean_trace_id(_TRACE) == _TRACE


def test_surrounding_whitespace_is_trimmed_but_the_identifier_is_never_rebuilt() -> None:
    assert clean_trace_id(f"  {_TRACE}  ") == _TRACE


@pytest.mark.parametrize("value", [None, "", "   "])
def test_an_absent_trace_id_is_absent(value: str | None) -> None:
    assert clean_trace_id(value) is None


def test_a_trace_id_that_cannot_be_stored_is_refused() -> None:
    """It would never join to a row, so a link carrying it would be a broken link.

    The stored column is ``VARCHAR(64)`` and the platform mints a 32-character hex
    id, so anything longer or carrying a separator the URL would have to escape is
    not an identifier this platform can look up.
    """
    assert clean_trace_id("a" * (MAX_TRACE_ID_LENGTH + 1)) is None
    assert clean_trace_id("abc def") is None
    assert clean_trace_id("abc/def") is None
    assert clean_trace_id("abc'def") is None
    assert len(_TRACE) <= MAX_TRACE_ID_LENGTH


def test_every_trace_id_the_gateway_would_store_passes_the_link_rule() -> None:
    """The link rule is the platform's rule, not a stricter invention.

    ``app.gateway.trace`` mints ``uuid4().hex`` unless the caller supplied a
    printable, unspaced ``X-Request-Id``, and error capture clamps what it stores to
    ``VARCHAR(64)``. Anything that row could hold has to survive :func:`clean_trace_id`,
    or a link built from a real stored id would be refused.
    """
    minted = uuid4().hex
    supplied = uuid4().hex.upper()

    assert clean_trace_id(minted) == minted
    assert clean_trace_id(supplied) == supplied
    assert clean_trace_id("x" * MAX_TRACE_ID_LENGTH) == "x" * MAX_TRACE_ID_LENGTH
