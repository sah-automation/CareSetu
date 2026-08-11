"""MOD-009: domain errors for the ``settlement`` module (coding-standards §3).

Phase 1 carries the module base error only; the hierarchy grows
with the tickets that introduce real validation.
"""

from __future__ import annotations


class SettlementError(Exception):
    """Base error for the settlement module."""
