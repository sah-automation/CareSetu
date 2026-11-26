"""MOD-012: domain errors for the ``doctor`` module (coding-standards §3).

The console is a facade-only composition seam, so its error surface is small:
one base and one refusal. Owning the refusal here (instead of reusing another
module's) keeps the doctor's 403 envelope and its log tag bound to the module
that decided it, rather than coupled to whichever module happens to register
its handler first.
"""

from __future__ import annotations


class DoctorConsoleError(Exception):
    """Base error for the doctor console module."""


class DoctorConsoleAccessDeniedError(DoctorConsoleError):
    """No live consent grant authorizes this doctor's read of the patient.

    The direct photo stream fails closed with this refusal: nothing is
    returned to the client and the route maps it to the 403
    ``DOCTOR_CONSOLE_ACCESS_DENIED`` envelope (api-standards §2).
    """
