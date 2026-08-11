"""MOD-011 Audit: typed public sync API.

The only legal cross-module import target for the ``audit``
module (coding-standards §2, ADR-0003). Typed methods arrive with
Phase 2; this scaffold carries no business logic.
"""

from __future__ import annotations


class AuditFacade:
    """Typed public facade for audit (scaffold)."""
