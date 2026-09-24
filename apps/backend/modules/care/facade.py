"""MOD-006 care: the module's public cross-module facade seams (ADR-0003).

The module isolation gate (scripts/check_module_boundaries, ADR-0003) lets
other modules import a ``<module>.facade`` package only. Care's state machines
live in ``case_facade.py``/``rx_facade.py``; this file is the facade-only
front door other modules import through - so a seam like the open-case doctor
resolution (#534) is reachable exactly once and the internal case/rx pair can
move freely behind it.
"""

from __future__ import annotations

from modules.care.care_models import CaseDetailView as CaseDetailView
from modules.care.case_facade import CaseConsoleFacade

__all__ = ["CaseConsoleFacade", "CaseDetailView"]
