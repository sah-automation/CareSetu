"""MOD-013: domain errors for the ``observability`` module (coding-standards §3).

Phase 1 carries the module base error only; the hierarchy grows
with the tickets that introduce real validation (the B4 consumer and B5
rollup read paths).
"""

from __future__ import annotations


class ObservabilityError(Exception):
    """Base error for the observability module."""
