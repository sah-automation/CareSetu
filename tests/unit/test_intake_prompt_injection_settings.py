"""#780: the prompt-injection heuristics gate is opt-in.

The screen runs only when ``PROMPT_INJECTION_HEURISTICS_ENABLED`` is true. The
default is inert so the advisory check cannot add outbox rows (or a failure
mode) to an environment that has not opted in.
"""

from __future__ import annotations

import pytest

from app.config import (
    DEFAULT_PROMPT_INJECTION_HEURISTICS_ENABLED,
    Settings,
    get_settings,
)


def test_prompt_injection_heuristics_are_off_by_default() -> None:
    assert DEFAULT_PROMPT_INJECTION_HEURISTICS_ENABLED is False
    assert Settings().prompt_injection_heuristics_enabled is False


def test_prompt_injection_heuristics_gate_reads_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROMPT_INJECTION_HEURISTICS_ENABLED", "true")

    assert get_settings().prompt_injection_heuristics_enabled is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_prompt_injection_heuristics_gate_accepts_false_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("PROMPT_INJECTION_HEURISTICS_ENABLED", value)

    assert get_settings().prompt_injection_heuristics_enabled is False
