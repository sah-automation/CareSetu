"""MOD-005 Intake workflows: typed public sync API.

The only legal cross-module import target for the ``intake``
module (coding-standards §2, ADR-0003). Typed methods arrive with
Phase 2; this scaffold carries no business logic.
"""

from __future__ import annotations


class IntakeFacade:
    """Typed public facade for intake (scaffold)."""
