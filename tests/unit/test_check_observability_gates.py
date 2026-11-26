"""#753: the CI gate boot-smoke's posture report must cover every batch-3 gate.

``scripts/check_observability_gates.py`` prints ``_gate_posture`` before it
boots, and ``ci.yml`` reads that line in both matrix legs (gates off, gates on).
A gate missing from the report is a gate CI exercises silently - the boot could
be proving one thing while the log claims another. These tests pin the report's
shape: the three #753 feature gates named, defaulting off, and flipping with
their settings.
"""

from scripts.check_observability_gates import _gate_posture

from app.config import Settings


def test_the_posture_report_names_every_batch3_gate_at_its_default() -> None:
    settings = Settings()

    posture = _gate_posture(settings)

    assert posture["error_capture"] is False
    assert posture["evaluation"] is False
    assert posture["annotation_queue"] is False


def test_the_posture_report_reflects_the_batch3_gates_turned_on() -> None:
    settings = Settings(
        error_capture_enabled=True,
        evaluation_enabled=True,
        annotation_queue_enabled=True,
    )

    posture = _gate_posture(settings)

    assert posture["error_capture"] is True
    assert posture["evaluation"] is True
    assert posture["annotation_queue"] is True
