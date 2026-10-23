"""MOD-014: domain errors for the ``ops`` module (coding-standards §3).

#764 carries the module base error only; the hierarchy grows
with the tickets that introduce real validation.
"""

from __future__ import annotations


class OpsError(Exception):
    """Base error for the ops module."""
