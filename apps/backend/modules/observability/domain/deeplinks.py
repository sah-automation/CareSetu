"""MOD-013: deriving the operator observability deep links from Settings.

C1b (#707). Pure functions over the vendor configuration - no database, no HTTP,
no network - so every URL shape is unit-tested without a deployment
(error-handling-observability.md §5, coding-standards §2).

The rule these share: **an unconfigured vendor is an ABSENT link, never a
failure**. The plan's vendor clients are env-gated and no-op when unconfigured
(plan-phase14 §4), and the operator page renders whatever links come back. A
read that raised because ``SENTRY_DSN`` was empty would turn "this deployment
does not ship to Sentry" into an operator-facing 500, so each derivation returns
``None`` for a missing or unparseable value and the route answers 200 with that
key absent.

Only the ``sentry_dsn`` derivation reads something secret-shaped, and it keeps
nothing: the DSN's key half is dropped before the URL is built, so a
``/deeplinks`` answer is safe to log and to render (security-phii-standards).
"""

from __future__ import annotations

from urllib.parse import urlsplit

#: ``observability_deeplinks`` vendor keys, in the order the view declares them.
VENDOR_GRAFANA = "grafana"
VENDOR_SENTRY = "sentry"
VENDOR_LANGFUSE = "langfuse"


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


def sentry_link(sentry_dsn: str | None) -> str | None:
    """The issues view of the project a Sentry DSN points at, or ``None``.

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

    return f"https://{org_host}.sentry.io/issues/?project={project_id}"


def langfuse_link(host: str | None, public_key: str | None) -> str | None:
    """The project view of a configured Langfuse workspace, or ``None``.

    ``LANGFUSE_HOST`` is the API base and the project view lives one path below
    it, keyed by the public key: ``<host>/project/<public_key>``. Both halves are
    required - ``Settings`` refuses a half-configured key pair, and a workspace
    with no key has no single project to link to.

    The public key is not a secret (it identifies the project, the secret key
    authenticates it), and it is the only way to name the project in the URL.
    """
    base = _clean(host)
    key = _clean(public_key)
    if base is None or key is None:
        return None
    return f"{base.rstrip('/')}/project/{key}"
