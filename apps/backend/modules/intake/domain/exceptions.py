"""MOD-005: domain errors for the ``intake`` module (coding-standards §3).

Phase 1 carries the module base error only; the hierarchy grows
with the tickets that introduce real validation.
"""

from __future__ import annotations


class IntakeError(Exception):
    """Base error for the intake module."""
