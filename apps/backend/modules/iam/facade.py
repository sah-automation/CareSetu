"""MOD-001 Identity and access management: typed public sync API.

The only legal cross-module import target for the ``iam``
module (coding-standards §2, ADR-0003). Typed methods arrive with
Phase 2; this scaffold carries no business logic.
"""

from __future__ import annotations


class IamFacade:
    """Typed public facade for iam (scaffold)."""
