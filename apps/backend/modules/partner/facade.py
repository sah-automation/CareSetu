"""MOD-002 Partner network management: typed public sync API.

The only legal cross-module import target for the ``partner``
module (coding-standards §2, ADR-0003). Typed methods arrive with
Phase 2; this scaffold carries no business logic.
"""

from __future__ import annotations


class PartnerFacade:
    """Typed public facade for partner (scaffold)."""
