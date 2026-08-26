"""MOD-003: domain errors for the ``health`` module (coding-standards §3).

The hierarchy grows with the tickets that introduce real validation. The
record-read errors map to the shared error envelope in
``modules/health/adapters/routes.py`` (api-standards §2).
"""

from __future__ import annotations


class HealthError(Exception):
    """Base error for the health module."""


class RecordNotFoundError(HealthError):
    """No record exists under the requested id (404 ``RECORD_NOT_FOUND``)."""


class RecordAccessDeniedError(HealthError):
    """The caller is not the owner of the requested record.

    The denial has already been recorded in the access history ledger before
    this is raised (KPI-006: 100% of record accesses logged); the route maps
    it to the 403 ``RECORD_ACCESS_DENIED`` envelope.
    """
