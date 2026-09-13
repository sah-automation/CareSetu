"""PHASE-7 T10 (#407): frontend/backend intake threshold parity.

The recorder page can no longer silently diverge from the backend: a drift in
the record ceiling, usability floor, or the attempt/backoff ladders is now
caught by this test instead of shipping silently (coding-standards S9.2
"single source of truth - never duplicate the same value across languages").

The backend module constants are the source of truth; this test reads the
frontend ``voice.ts`` source off disk and asserts its exported constants equal
the Python domain constants:

- ``MAX_RECORD_MS`` (180 s ceiling) == ``MAX_AUDIO_DURATION_MS``
- ``MIN_RECORD_MS`` (3 s usability floor) == ``MIN_AUDIO_DURATION_MS``
- ``MAX_RECORD_ATTEMPTS`` (3) == ``MAX_RECORD_ATTEMPTS``
- ``MAX_UPLOAD_ATTEMPTS`` (3) == ``MAX_UPLOAD_ATTEMPTS``
- ``UPLOAD_RETRY_BASE_MS`` (500 ms) == the facade's ``_upload_backoff_delay``
  base (0.5 s)

Client-only UI pacing constants (``INTAKE_POLL_INTERVAL_MS`` /
``MAX_INTAKE_POLLS``) are deliberately NOT pinned - they pace the polling UX
and have no backend counterpart.
"""

from __future__ import annotations

import re
from pathlib import Path

from modules.intake.domain.state_machine import (
    MAX_AUDIO_DURATION_MS,
    MIN_AUDIO_DURATION_MS,
)
from modules.intake.domain.state_machine import (
    MAX_RECORD_ATTEMPTS as BACKEND_MAX_RECORD_ATTEMPTS,
)
from modules.intake.facade import MAX_UPLOAD_ATTEMPTS, _upload_backoff_delay

VOICE_TS = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "frontend"
    / "src"
    / "lib"
    / "intake"
    / "voice.ts"
)

_EXPORT_RE = re.compile(r"export const (\w+) = (\d[\d_]*)", re.MULTILINE)


_FRONTEND_CONSTANTS = {
    name: int(literal.replace("_", ""))
    for name, literal in _EXPORT_RE.findall(VOICE_TS.read_text(encoding="utf-8"))
}


def test_frontend_record_thresholds_match_backend_domain() -> None:
    assert _FRONTEND_CONSTANTS["MAX_RECORD_MS"] == MAX_AUDIO_DURATION_MS
    assert _FRONTEND_CONSTANTS["MIN_RECORD_MS"] == MIN_AUDIO_DURATION_MS


def test_frontend_record_attempt_ladder_matches_backend_domain() -> None:
    assert _FRONTEND_CONSTANTS["MAX_RECORD_ATTEMPTS"] == BACKEND_MAX_RECORD_ATTEMPTS


def test_frontend_upload_ladder_matches_backend_facade() -> None:
    assert _FRONTEND_CONSTANTS["MAX_UPLOAD_ATTEMPTS"] == MAX_UPLOAD_ATTEMPTS
    # First retry (attempt 2) backs off base * 2**0 = 0.5 s.
    assert _FRONTEND_CONSTANTS["UPLOAD_RETRY_BASE_MS"] == round(_upload_backoff_delay(2) * 1000)
