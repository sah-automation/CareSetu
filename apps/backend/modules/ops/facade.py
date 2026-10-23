"""MOD-014 Configuration: typed public sync API.

The only legal cross-module import target for the ``ops``
module (coding-standards §2, ADR-0003). #764 is the scaffold only;
the effective-settings read and writes land in later PHASE-14B tickets.
"""

from __future__ import annotations


class OpsFacade:
    """Typed public facade for ops (scaffold)."""
