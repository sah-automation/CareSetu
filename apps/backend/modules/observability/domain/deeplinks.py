"""MOD-013: deriving the operator observability deep links from Settings.

C1b (#707), widened by B5 (#729) with :func:`grafana_metric_link` and by B3 (#736)
into **parameterised link sets**. Pure functions over the vendor configuration - no
database, no HTTP, no network - so every URL shape is unit-tested without a
deployment (error-handling-observability.md §5, coding-standards §2).

Two rules decide every function here, and they are the same two rules everywhere:

**An unconfigured vendor is an ABSENT link, never a failure.** The plan's vendor
clients are env-gated and no-op when unconfigured (plan-phase14 §4), and the operator
page renders whatever links come back. A read that raised because ``SENTRY_DSN`` was
empty would turn "this deployment does not ship to Sentry" into an operator-facing
500, so each derivation returns ``None`` for a missing or unparseable value and the
route answers 200 with that key absent.

**A link that cannot carry its filter is ABSENT, never bare** (#736). The three base
URLs this module used to return were the whole of the problem: an operator who
clicked one landed on an empty canvas and had to rebuild the query by hand. So no
derivation here returns a URL it could not have filtered - the Sentry issues view
requires a service, the Langfuse trace list requires a model or a task, the Explore
pane requires a trace. A deployment that has Grafana but no traces still answers with
a dashboard (which always carries its range), and one that has Sentry but no known
service simply has no Sentry link.

**The trace id is echoed, never reconstructed** (#736). Whatever id a platform read
handed the caller - the error feed's ``trace_id``, the AI spend row's - goes into the
links unchanged, because a trace id the platform never stored produces a URL that
lands on nothing. :func:`clean_trace_id` is the one rule for what an identifier may
be, and it is the platform's own rule rather than a new one (see that function's
docstring for where it comes from).

Only the ``sentry_dsn`` derivation reads something secret-shaped, and it keeps
nothing: the DSN's key half is dropped before the URL is built, so a ``/deeplinks``
answer is safe to log and to render (security-phii-standards).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from types import MappingProxyType
from urllib.parse import quote, urlencode, urlsplit

from observability.otel import HTTP_INFLIGHT_METRIC
from observability.trace_ids import MAX_TRACE_ID_LENGTH as _MAX_TRACE_ID_LENGTH

#: TRUE request concurrency, as a tracing-backend signal (B5 #729, #717 decision
#: 17). Requests in flight at this instant - the only honest place saturation
#: lives, because a Postgres-resident count would be a snapshot of a number that
#: changes every millisecond and would read as though it were the real one. The
#: operator reliability read LINKS here rather than storing anything.
#:
#: The NAME is declared by ``observability.otel`` - the instrument that records
#: it - and imported here, beside the link that points at it, because the link is
#: the read's public contract: a metric name spelled once means the recorded
#: signal and the URL that opens it cannot drift apart. The shared package
#: imports nothing from ``modules`` (coding-standards §2), so the dependency runs
#: contract -> instrument and never the other way.
#:
#: Unlabelled by design: one series for the whole service. Under the free tier's
#: ten-thousand-active-series ceiling that is deliberate - a metric labelled per
#: route would spend a series per endpoint to answer a question the total answers.


#: The Grafana dashboard the operator link opens (#736).
#:
#: A UID, not a title, because a title is what a human renames and a UID is what a
#: URL can promise. **#748 provisions the dashboards as repository files and must
#: declare this exact UID** in the provisioned dashboard JSON - if the two disagree,
#: every Grafana link in the operator console opens a 404, which is why the constant
#: lives here beside the link that uses it rather than in the deployment's
#: configuration.
GRAFANA_DASHBOARD_UID = "caresetu-observability"

#: The dashboard's default window. A RELATIVE range, so the pane opens on recent
#: history rather than on an epoch the operator then has to widen by hand.
DEFAULT_GRAFANA_WINDOW = "now-6h"

#: Ceiling on how far the operator can reach back from the default window, enforced
#: only as a length: Grafana's own parser owns the grammar, and a window this
#: derivation cannot recognise falls back to :data:`DEFAULT_GRAFANA_WINDOW` rather
#: than being passed through into a link that opens nothing.
MAX_GRAFANA_WINDOW_LENGTH = 32

#: The longest trace id the platform can store: ``observability_ai_job_spend``,
#: ``observability_error_events`` and ``observability_product_events`` all declare
#: ``trace_id VARCHAR(64)``, and error capture clamps to that before it writes.
#:
#: The number is owned by the shared package (``observability.trace_ids``) because
#: the gateway has to enforce the SAME bound before it stores one: a client-supplied
#: id longer than the column would reach the product ledger unclamped and wedge
#: that write. One constant, one rule, both sides of the seam.
MAX_TRACE_ID_LENGTH = _MAX_TRACE_ID_LENGTH

#: Ceiling for the platform's other pseudonymous identifiers - the ``actor_key`` and
#: ``session_key`` the product-event ledger stores, both ``VARCHAR(64)``.
MAX_KEY_LENGTH = 64

#: The Langfuse span name each platform ``task_type`` records under (#736).
#:
#: The platform's task vocabulary is ``AiTaskType`` (``modules.intake.domain.events``)
#: but a Langfuse trace is found by the NAME its ``@observe`` span was declared with,
#: and the two are not the same word: ``draft`` records as ``ai_draft_rx``. Filtering
#: on the task type verbatim would search for a span nobody writes.
#:
#: A task type with no observed span has no entry, and its link then carries whatever
#: other filter was asked for and names no span - landing on those traces rather than
#: on an empty result set for a span that was never written.
LANGFUSE_SPAN_NAMES: Mapping[str, str] = MappingProxyType(
    {
        "transcribe": "ai_transcribe",
        "structure": "ai_structure",
        "draft": "ai_draft_rx",
    }
)

#: What a link may put in a path segment. Printable, no whitespace, no separator a
#: URL would have to escape, and never a bare dot segment - so an identifier can
#: never rewrite the query around it, break out of a Sentry/Langfuse filter value, or
#: walk a path segment backwards.
_SAFE_SEGMENT = re.compile(r"\A[A-Za-z0-9._-]+\Z")

#: What a link may put in a QUERY filter value. Looser than :data:`_SAFE_SEGMENT`
#: because it is never a path segment and :func:`urllib.parse.urlencode` escapes it
#: anyway: ``model`` in particular carries a slash for every OpenAI-compatible id
#: (``openai/gpt-4o``), and rejecting those would drop the Langfuse link for a whole
#: class of real models. The quote and the whitespace stay out, so the value still
#: cannot close a Sentry search term and add another.
_SAFE_FILTER = re.compile(r"\A[A-Za-z0-9._:/-]+\Z")


def _clean(url: str | None) -> str | None:
    """A configured URL without surrounding whitespace, or ``None`` when unset.

    An empty or whitespace-only value is "not configured" - the Settings default
    for every vendor is the empty string, and an operator who blanks the variable
    has switched the vendor off rather than pointed it at the empty URL.
    """
    if url is None:
        return None
    trimmed = url.strip()
    return trimmed or None


def _clean_safe(value: str | None, *, pattern: re.Pattern[str], max_length: int) -> str | None:
    """A value safe to place in a URL where ``pattern`` says it may go, or ``None``.

    Whitespace is trimmed rather than escaped, and anything that still fails the
    pattern or is longer than the column it would have been read from is refused
    outright. Refusing is the point: escaping such a value into a vendor's grammar
    would let a caller-supplied string change what the link FILTERS on, and the link
    is a navigation aid, not an input.
    """
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed or len(trimmed) > max_length or not pattern.match(trimmed):
        return None
    # ``..`` and ``.`` survive the charset, and ``quote`` leaves a dot alone - so a
    # dot-only segment has to be refused here or a path link could walk upwards.
    return None if set(trimmed) == {"."} else trimmed


def _clean_segment(value: str | None, *, max_length: int) -> str | None:
    """An identifier safe to place in a URL PATH, or ``None``."""
    return _clean_safe(value, pattern=_SAFE_SEGMENT, max_length=max_length)


def _clean_filter(value: str | None, *, max_length: int) -> str | None:
    """A value safe to place in a URL QUERY filter, or ``None``."""
    return _clean_safe(value, pattern=_SAFE_FILTER, max_length=max_length)


def clean_trace_id(trace_id: str | None) -> str | None:
    """A trace id this platform could have stored, or ``None``.

    The single rule the deep links share for their join key (#717 decision 44): the
    identifier is passed through exactly as a platform read produced it, and a value
    the platform could never have written is dropped rather than guessed at.

    The rule this enforces is the platform's own, not a fresh one. The gateway
    (``app.gateway.trace``) mints ``uuid4().hex`` - 32 lowercase hex characters -
    unless the caller supplied an ``X-Request-Id`` header it accepts, which it
    does only for a value matching the shared identifier shape
    (``observability.trace_ids``), and error capture clamps what it stores to
    ``VARCHAR(64)`` (``observability.error_capture``). So the set of identifiers
    the platform can actually hold is exactly what
    :func:`observability.trace_ids.is_safe_trace_id` accepts, and this accepts
    exactly that - a value no read could have produced does not.
    """
    return _clean_segment(trace_id, max_length=MAX_TRACE_ID_LENGTH)


def _clean_window(window: str | None) -> str:
    """A Grafana-relative range, or the default when the caller gave an unusable one.

    A window is a range expression (``now-6h``, ``now-6h/d``), not an identifier, so
    it is not quoted and not escape-proof - which is why one that does not look like
    a range falls back to :data:`DEFAULT_GRAFANA_WINDOW` instead of being passed
    through into a link that would open on nothing.
    """
    return _clean_filter(window, max_length=MAX_GRAFANA_WINDOW_LENGTH) or DEFAULT_GRAFANA_WINDOW


def grafana_link(grafana_url: str | None) -> str | None:
    """The configured Grafana base URL, or ``None`` when none is set.

    Taken verbatim from ``GRAFANA_URL``: it is a human-facing stack URL, and no
    transform can improve on what the operator configured. A single trailing
    slash is dropped so a caller can append a dashboard path without producing
    a double slash.
    """
    base = _clean(grafana_url)
    if base is None:
        return None
    return base.rstrip("/")


def grafana_dashboard_link(
    grafana_url: str | None,
    *,
    dashboard_uid: str = GRAFANA_DASHBOARD_UID,
    window: str = DEFAULT_GRAFANA_WINDOW,
    service: str | None = None,
    environment: str | None = None,
) -> str | None:
    """A Grafana dashboard with its time range and template variables set (#736).

    Story 57: the link has to land on the answer, not on a blank canvas. Three
    things make that true and all three are in the URL:

    * ``/d/<uid>`` names the dashboard :data:`GRAFANA_DASHBOARD_UID`, which #748
      provisions. The slug is the UID again, because Grafana uses the trailing
      segment for the tab title and a slug that disagreed with the UID would put a
      name on screen the dashboard does not have.
    * ``from``/``to`` are RELATIVE. A dashboard opened on ``now-6h``..``now`` shows
      recent history; the same dashboard opened without them shows whatever the
      dashboard's own default is, which on a fresh provisioning is empty.
    * ``var-service`` / ``var-env`` set the dashboard's template variables, so the
      panels are already narrowed to this deployment rather than to everything the
      datasource holds.

    ``orgId`` is deliberately absent: guessing one would send an operator into
    another organisation's stack, and Grafana resolves the viewer's own org when the
    parameter is missing.

    ``dashboard_uid`` is a keyword so a caller provisioning dashboards can point at
    the one it declared; it defaults to :data:`GRAFANA_DASHBOARD_UID` because that is
    the dashboard this deployment ships.
    """
    base = grafana_link(grafana_url)
    uid = _clean_segment(dashboard_uid, max_length=MAX_KEY_LENGTH)
    if base is None or uid is None:
        return None
    params = {"from": _clean_window(window), "to": "now"}
    for key, value in (("var-service", service), ("var-env", environment)):
        segment = _clean_filter(value, max_length=MAX_KEY_LENGTH)
        if segment is not None:
            params[key] = segment
    slug = quote(uid, safe="")
    return f"{base}/d/{slug}/{slug}?{urlencode(params)}"


def grafana_metric_link(
    grafana_url: str | None, *, metric: str = HTTP_INFLIGHT_METRIC, window: str = "now-1h"
) -> str | None:
    """A Grafana **Explore** pane already filtered to ``metric``, or ``None``.

    B5 (#729). The one place true request concurrency is reported: it is a live
    signal in the tracing backend, so this read LINKS to it rather than storing an
    approximation of it in Postgres. An approximation stored beside the real thing
    is worse than no number at all - it would be read as the figure.

    Explore rather than a dashboard, because this repository has shipped no
    dashboard for the metric: an Explore pane asks the question, while a named
    dashboard link would point at a page that does not exist. The default metric is
    :data:`HTTP_INFLIGHT_METRIC` - requests in flight - which is the number the
    platform records and therefore the only one this link may promise to reach.

    No ``datasource`` key is emitted on purpose. Explore then resolves the default
    datasource, which is the one configured to receive the platform's own metrics -
    and hard-coding a datasource UID would put a value in the URL that this
    deployment may not have. The ``left`` payload is percent-encoded, which is what
    Grafana expects; ``window`` is a Grafana-relative range, so the pane lands on
    the last hour rather than on the epoch.
    """
    base = grafana_link(grafana_url)
    if base is None:
        return None
    left = json.dumps(
        {"queries": [{"expr": metric}], "range": {"from": window, "to": "now"}},
        separators=(",", ":"),
    )
    return f"{base}/explore?left={quote(left, safe='')}"


def grafana_explore_link(
    grafana_url: str | None, *, trace_id: str | None, window: str = DEFAULT_GRAFANA_WINDOW
) -> str | None:
    """An Explore pane opened on ONE trace, or ``None``.

    Story 58, and the one link where the join key is the whole payload: ``traceId``
    is the platform's own stored id (:func:`clean_trace_id`), so an operator who
    clicked it from an error row reaches that row's trace rather than a fresh empty
    search.

    The window rides along for the same reason the dashboard's does. A pane with a
    trace id and no range still opens on whatever Explore last used, which on a fresh
    browser profile is the epoch - the trace would be found and the surrounding
    history would look like nothing happened.
    """
    base = grafana_link(grafana_url)
    trace = clean_trace_id(trace_id)
    if base is None or trace is None:
        return None
    left = json.dumps(
        {"traceId": trace, "range": {"from": _clean_window(window), "to": "now"}},
        separators=(",", ":"),
    )
    return f"{base}/explore?left={quote(left, safe='')}"


def sentry_project(sentry_dsn: str | None) -> tuple[str, str] | None:
    """``(org_host, project_id)`` from a Sentry DSN, or ``None`` when unparseable.

    A DSN is ``https://<public_key>@<org_host>/<project_id>``. The browser-facing
    equivalent is ``https://<org>.sentry.io/issues/?project=<project_id>``, and
    only the ORG id and the PROJECT id are carried across - the key half is
    dropped here rather than echoed anywhere.

    Returns ``None`` for a DSN that does not parse: a malformed or self-hosted
    value is a deployment an operator has to fix in Sentry, not a link this
    route should guess at.
    """
    dsn = _clean(sentry_dsn)
    if dsn is None:
        return None

    parts = urlsplit(dsn)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    project_id = parts.path.strip("/")
    if not project_id:
        return None

    # ``<public_key>@o<org_id>.ingest.<region>.sentry.io`` -> ``o<org_id>``.
    # The org id leads the host after the ``@``; self-hosted hosts carry no
    # numeric org, so they are left without a link rather than mis-linked.
    host = parts.netloc.rsplit("@", 1)[-1]
    org_host = host.split(".")[0]
    if not org_host.startswith("o") or not org_host[1:].isdigit():
        return None
    return org_host, project_id


def _sentry_issues_query(sentry_dsn: str | None, terms: list[str]) -> str | None:
    """The issues view of one Sentry project, pre-filtered by ``terms``, or ``None``."""
    project = sentry_project(sentry_dsn)
    if project is None:
        return None
    org_host, project_id = project
    return (
        f"https://{org_host}.sentry.io/issues/?project={project_id}"
        f"&query={quote(' '.join(terms), safe='')}"
    )


def sentry_issues_link(
    sentry_dsn: str | None, *, service: str, error_type: str | None = None
) -> str | None:
    """The project's issues view already filtered to THIS service (#736).

    Story 59. ``service`` is required, not optional: the service filter is the
    reason the link is worth having at all, and without it the derivation would
    reproduce exactly the bare URL #736 removed. ``error_type`` narrows further when
    the caller knows one - the error feed's own failure class - and is left out
    otherwise rather than filled with a guess.

    Sentry's own search grammar joins space-separated terms with AND, so one query
    narrows on both dimensions at once. Values are quoted and are refused outright
    if they contain a space or a quote, so a caller-supplied string cannot close the
    value and add a term of its own.
    """
    service_segment = _clean_filter(service, max_length=MAX_KEY_LENGTH)
    if service_segment is None:
        return None
    terms = [f'service:"{service_segment}"']
    error_segment = _clean_filter(error_type, max_length=MAX_KEY_LENGTH)
    if error_segment is not None:
        terms.append(f'error.type:"{error_segment}"')
    return _sentry_issues_query(sentry_dsn, terms)


def sentry_trace_link(sentry_dsn: str | None, *, trace_id: str | None) -> str | None:
    """The project's issues view filtered to one trace, or ``None``.

    Filters on the ``trace_id`` tag the platform stamps onto every captured event
    (``observability.sentry._attach_trace_id``) - the same identifier the error feed
    shows the operator, so clicking through from a row reaches that row's events
    rather than the project's whole issue list.
    """
    trace = clean_trace_id(trace_id)
    if trace is None:
        return None
    return _sentry_issues_query(sentry_dsn, [f'trace_id:"{trace}"'])


def _langfuse_project(host: str | None, public_key: str | None) -> str | None:
    """``<host>/project/<public_key>``, or ``None`` when the workspace is unconfigured.

    ``LANGFUSE_HOST`` is the API base and the project view lives one path below it,
    keyed by the public key. Both halves are required - ``Settings`` refuses a
    half-configured key pair, and a workspace with no key has no single project to
    link to.

    The public key is not a secret (it identifies the project, the secret key
    authenticates it), and it is the only way to name the project in the URL.
    """
    base = _clean(host)
    key = _clean(public_key)
    if base is None or key is None:
        return None
    return f"{base.rstrip('/')}/project/{quote(key, safe='')}"


def langfuse_traces_link(
    host: str | None,
    public_key: str | None,
    *,
    model: str | None = None,
    task_type: str | None = None,
) -> str | None:
    """The trace list filtered to one model and/or task, or ``None``.

    Story 60. ``model`` is Langfuse's own field and the platform records it on
    every AI span, so it filters directly. ``task_type`` is the platform's word and
    Langfuse's is the SPAN NAME, so it goes through :data:`LANGFUSE_SPAN_NAMES` -
    ``draft`` reaches ``ai_draft_rx``, which is what the adapters actually wrote.

    At least one filter is required: the unfiltered trace list is the bare project
    view under another name, and #736 stopped returning those. A task type with no
    observed span (:data:`LANGFUSE_SPAN_NAMES`) drops the name filter and keeps the
    model one - the view still shows those traces instead of an empty result.
    """
    project = _langfuse_project(host, public_key)
    if project is None:
        return None
    params: dict[str, str] = {}
    # A QUERY filter, so the looser charset: an OpenAI-compatible id such as
    # ``openai/gpt-4o`` carries a slash and is refused by the path rule.
    model_segment = _clean_filter(model, max_length=MAX_KEY_LENGTH)
    if model_segment is not None:
        params["model"] = model_segment
    task_segment = _clean_filter(task_type, max_length=MAX_KEY_LENGTH)
    span_name = LANGFUSE_SPAN_NAMES.get(task_segment) if task_segment is not None else None
    if span_name is not None:
        params["name"] = span_name
    if not params:
        return None
    return f"{project}/traces?{urlencode(params)}"


def langfuse_trace_link(
    host: str | None, public_key: str | None, *, trace_id: str | None
) -> str | None:
    """One AI trace by the platform's trace id, or ``None``.

    ``trace_id`` is in Langfuse's span metadata allow-list (``observability.langfuse_span``),
    so it is the same identifier the platform stored and the same one the Grafana and
    Sentry links carry - which is what makes the three tools joinable.
    """
    project = _langfuse_project(host, public_key)
    trace = clean_trace_id(trace_id)
    if project is None or trace is None:
        return None
    return f"{project}/trace/{quote(trace, safe='')}"


def langfuse_actor_link(
    host: str | None, public_key: str | None, *, actor_key: str | None
) -> str | None:
    """One actor's whole AI history, filtered by the platform's pseudonymous key.

    Story 61. ``actor_key`` is the one-way ``domain.pseudonym.actor_key`` hash the
    product-event ledger stores (never a raw identity reference), so the link names
    an actor the same way every other surface does - and cannot be used to recover
    who that actor is (security-phii-standards).
    """
    project = _langfuse_project(host, public_key)
    actor = _clean_filter(actor_key, max_length=MAX_KEY_LENGTH)
    if project is None or actor is None:
        return None
    return f"{project}/users?{urlencode({'userId': actor})}"


def langfuse_session_link(
    host: str | None, public_key: str | None, *, session_key: str | None
) -> str | None:
    """One session's traces, filtered by the platform's pseudonymous session key.

    The companion to :func:`langfuse_actor_link` for the other half of the question
    an operator asks after clicking through from a funnel: not "what has this person
    done" but "what happened in this one journey".
    """
    project = _langfuse_project(host, public_key)
    session = _clean_filter(session_key, max_length=MAX_KEY_LENGTH)
    if project is None or session is None:
        return None
    return f"{project}/sessions?{urlencode({'sessionId': session})}"
