"""Profile-media facade seam (ADR-0003, parent #529 / ticket #532).

The module-isolation rule (coding-standards §2) only admits cross-module
imports via ``facade.py``. The ``iam`` (patient photo) and ``partner`` (doctor
photo) profiles read/write photo keys through this seam: a caller module
imports the port, the factory, and the two role ``prefix`` constants from here,
never from ``adapters/`` directly. The concrete backends under ``adapters/``
stay internal - callers program against the port (built for them at the
composition root) and pass ``PATIENT_PREFIX`` / ``DOCTOR_PREFIX``, so they
cannot pick a backend themselves. The composition root (``app/main.py``,
outside the module tree) may import the concrete builder from ``adapters/`` as
it does for intake media.
"""

from modules.profile_media.adapters.media_store import (
    DOCTOR_PREFIX,
    PATIENT_PREFIX,
    ProfileMediaStore,
    build_profile_media_store,
)

__all__ = [
    "DOCTOR_PREFIX",
    "PATIENT_PREFIX",
    "ProfileMediaStore",
    "build_profile_media_store",
]
