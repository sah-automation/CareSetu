"""MOD-010 Notifications: typed public sync API.

The only legal cross-module import target for the ``notify``
module (coding-standards §2, ADR-0003). Typed methods arrive with
Phase 2; this scaffold carries no business logic.
"""

from __future__ import annotations


class NotifyFacade:
    """Typed public facade for notify (scaffold)."""
