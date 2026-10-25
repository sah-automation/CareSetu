"""MOD-013: Public CSP report collector (PHASE-14B Batch 2, #776).

A public, rate-limited endpoint that accepts both CSP report formats
(legacy ``report-uri`` and modern ``report-to``), normalizes the report,
aggregates daily by directive, disposition, blocked source, and document
path, returns 204, and never stores raw reports.

Both CSP report formats:
- Legacy (``Content-Type: application/csp-report``): ``{"csp-report":
  {...}}``
- Modern (``Content-Type: application/reports+json``):
  ``[{"type": "csp-violation", "body": {...}}]``
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.config import Settings
from app.gateway.errors import (
    CODE_RATE_LIMIT_EXCEEDED,
    MESSAGE_RATE_LIMIT_EXCEEDED,
    error_response,
)
from modules.observability.facade import ObservabilityFacade

router = APIRouter(tags=["csp-collector"])

# In-memory rate limit buckets: {key: (expires_at, count)}
_csp_buckets: dict[str, tuple[float, int]] = {}


def _csp_rate_limit_key(request: Request, settings: Settings) -> str:
    """Rate limit key: per client IP."""
    client = request.client
    return f"csp:{client.host if client is not None else 'unknown'}"


def _check_csp_rate_limit(request: Request, settings: Settings) -> None:
    """Check and enforce CSP collector rate limit."""
    import time

    now = time.monotonic()
    key = _csp_rate_limit_key(request, settings)
    bucket = _csp_buckets.get(key)

    if bucket is None or bucket[0] <= now:
        _csp_buckets[key] = (now + settings.csp_collector_rate_limit_window_seconds, 1)
        return

    if bucket[1] >= settings.csp_collector_rate_limit_max_requests:
        # Prune expired buckets if over capacity
        if len(_csp_buckets) > settings.csp_collector_max_buckets:
            expired = [k for k, (expires_at, _) in _csp_buckets.items() if expires_at <= now]
            for k in expired:
                del _csp_buckets[k]

        response = error_response(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code=CODE_RATE_LIMIT_EXCEEDED,
            message=MESSAGE_RATE_LIMIT_EXCEEDED,
            request=request,
            headers={"Retry-After": str(settings.csp_collector_rate_limit_window_seconds)},
        )
        body = response.body
        if isinstance(body, memoryview):
            body = body.tobytes()
        detail = body.decode("utf-8")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
        )

    _csp_buckets[key] = (bucket[0], bucket[1] + 1)


class LegacyCspReport(BaseModel):
    """Legacy CSP report format (report-uri)."""

    csp_report: dict[str, object] = Field(..., alias="csp-report")


class ModernCspReportEntry(BaseModel):
    """Single entry in modern CSP report format (report-to)."""

    type: str
    body: dict[str, object]


ModernCspReport = list[ModernCspReportEntry]


class NormalizedCspViolation(BaseModel):
    """Normalized CSP violation fields for aggregation."""

    directive: str
    disposition: str
    blocked_source: str
    document_uri: str


def _strip_query_string(uri: str) -> str:
    """Strip query string and fragment from a URI."""
    if not uri:
        return ""
    parsed = urlparse(uri)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _cap_string(value: str, max_length: int) -> str:
    """Cap string at max_length, preserving the start."""
    if len(value) <= max_length:
        return value
    return value[:max_length]


def _normalize_legacy_report(
    report: dict[str, object], settings: Settings
) -> NormalizedCspViolation:
    """Normalize a legacy CSP report (csp-report format)."""
    # CSP report fields (kebab-case in spec, but may vary)
    directive = str(report.get("violated-directive") or report.get("effective-directive") or "")
    disposition = str(report.get("disposition") or "enforce")
    blocked_source = str(report.get("blocked-uri") or report.get("blockedURI") or "")
    document_uri = str(report.get("document-uri") or report.get("documentURI") or "")

    # Normalize
    document_uri = _strip_query_string(document_uri)
    directive = _cap_string(directive, settings.csp_collector_max_directive_length)
    disposition = _cap_string(disposition, settings.csp_collector_max_disposition_length)
    blocked_source = _cap_string(blocked_source, settings.csp_collector_max_blocked_source_length)
    document_uri = _cap_string(document_uri, settings.csp_collector_max_document_uri_length)

    return NormalizedCspViolation(
        directive=directive,
        disposition=disposition,
        blocked_source=blocked_source,
        document_uri=document_uri,
    )


def _normalize_modern_report(body: dict[str, object], settings: Settings) -> NormalizedCspViolation:
    """Normalize a modern CSP report body (report-to format)."""
    # Modern format uses the same field names as legacy
    directive = str(body.get("violated-directive") or body.get("effective-directive") or "")
    disposition = str(body.get("disposition") or "enforce")
    blocked_source = str(body.get("blocked-uri") or body.get("blockedURI") or "")
    document_uri = str(body.get("document-uri") or body.get("documentURI") or "")

    # Normalize
    document_uri = _strip_query_string(document_uri)
    directive = _cap_string(directive, settings.csp_collector_max_directive_length)
    disposition = _cap_string(disposition, settings.csp_collector_max_disposition_length)
    blocked_source = _cap_string(blocked_source, settings.csp_collector_max_blocked_source_length)
    document_uri = _cap_string(document_uri, settings.csp_collector_max_document_uri_length)

    return NormalizedCspViolation(
        directive=directive,
        disposition=disposition,
        blocked_source=blocked_source,
        document_uri=document_uri,
    )


@router.post(
    "/v1/csp-report",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Collect CSP violation reports (public, rate-limited)",
    include_in_schema=False,  # Public endpoint, not part of operator API
)
async def collect_csp_report(
    request: Request,
    content_type: str | None = Header(None, alias="Content-Type"),
    content_length: int | None = Header(None, alias="Content-Length"),
) -> None:
    """Collect CSP violation reports from browsers.

    Accepts both legacy (application/csp-report) and modern (application/reports+json)
    CSP report formats. Normalizes the report, strips query strings, caps field
    lengths, and increments the daily aggregate counter. Returns 204 No Content.

    Rate limited to 60 requests per minute per IP. Oversized reports (>16 KB) are
    rejected with 413. Never stores raw reports, query strings, or PHI.
    """
    from typing import cast

    facade = cast(ObservabilityFacade, request.app.state.observability_facade)
    settings = cast(Settings, request.app.state.settings)

    # Check if CSP reporting is enabled
    if not settings.csp_report_only_enabled:
        # Silently accept but don't process when disabled
        return

    # Rate limit check
    _check_csp_rate_limit(request, settings)

    # Check content length
    if content_length is not None and content_length > settings.csp_collector_max_report_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Report exceeds {settings.csp_collector_max_report_bytes} bytes limit",
        )

    # Read body with size limit
    body = await request.body()
    if len(body) > settings.csp_collector_max_report_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Report exceeds {settings.csp_collector_max_report_bytes} bytes limit",
        )

    if not body:
        # Empty body - nothing to process
        return

    # Parse and normalize based on content type
    violations: list[NormalizedCspViolation] = []

    try:
        if content_type and "application/reports+json" in content_type:
            # Modern format: array of report objects
            import json

            reports = json.loads(body.decode("utf-8"))
            if not isinstance(reports, list):
                return  # Invalid format, silently ignore

            for entry in reports:
                if not isinstance(entry, dict):
                    continue
                if entry.get("type") != "csp-violation":
                    continue
                body_data = entry.get("body")
                if not isinstance(body_data, dict):
                    continue
                violations.append(_normalize_modern_report(body_data, settings))

        elif content_type and "application/csp-report" in content_type:
            # Legacy format: {"csp-report": {...}}
            import json

            data = json.loads(body.decode("utf-8"))
            if not isinstance(data, dict):
                return
            csp_report = data.get("csp-report") or data.get("csp_report")
            if not isinstance(csp_report, dict):
                return
            violations.append(_normalize_legacy_report(csp_report, settings))

        else:
            # Unknown content type - silently ignore per CSP spec
            return

    except Exception:
        # Invalid JSON or other parse error - silently ignore
        # We never log raw reports (PHI/secret risk)
        return

    # Aggregate violations
    aggregate_date = datetime.now(UTC).date()

    for violation in violations:
        # Skip empty directive (malformed report)
        if not violation.directive:
            continue

        await facade.accumulate_csp_aggregate(
            aggregate_date=aggregate_date,
            directive=violation.directive,
            disposition=violation.disposition,
            blocked_source=violation.blocked_source,
            document_uri=violation.document_uri,
        )
