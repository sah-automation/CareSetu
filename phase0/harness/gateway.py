"""Phase 0 harness — provider-agnostic gateway port.

The seam that mirrors the future MOD-005 AI gateway: every candidate provider
(transcribe → structure, typed, async) plugs in here, so the Phase 7 winner's
adapter can be adopted through the same interface. Throwaway research code for
PHASE-0 (issues #2 / #4 / #5); not production.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from phase0.harness.models import StructureResult, TranscribeResult


class Gateway(Protocol):
    """Provider-agnostic AI gateway port (audio → transcript → structure).

    Async, typed, mirrors ``MOD-005``'s AI gateway. A provider may also
    collapse transcribe + structure into a single multimodal call; that
    finding is recorded per-provider, not as a second port method.
    """

    @property
    def name(self) -> str: ...

    async def transcribe(self, audio_path: Path, clip_id: str) -> TranscribeResult: ...

    async def structure(self, transcript: str, clip_id: str) -> StructureResult: ...
