"""MOD-004 Consent management: typed public sync API.

The only legal cross-module import target for the ``consent``
module (coding-standards §2, ADR-0003). Typed methods arrive with
Phase 2; this scaffold carries no business logic.
"""

from __future__ import annotations


class ConsentFacade:
    """Typed public facade for consent (scaffold)."""
