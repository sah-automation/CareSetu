"""MOD-002: domain errors for the ``partner`` module (coding-standards §3).

Phase 1 carries the module base error only; the hierarchy grows
with the tickets that introduce real validation.
"""

from __future__ import annotations


class PartnerError(Exception):
    """Base error for the partner module."""
