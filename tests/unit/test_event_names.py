"""Tickets #54/#55: legacy snake_case event-name gate - fixture tests.

Feeds throwaway text files to ``scripts.check_event_names`` and asserts the
gate rejects the legacy snake_case spelling of a ``patient.*`` event while
passing the dot-notation form, skips the ``patient_*_envelope`` builder
function names, skips binary files, and that the real tracked repo is
currently clean.

The legacy spelling is assembled at runtime (never written out) so the gate's
repo-wide scan cannot trip on this file's own fixtures.
"""

import subprocess
from pathlib import Path

import pytest
from scripts.check_event_names import (
    EventNameViolation,
    check_event_names,
    main,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

_LEGACY = "patient_" + "auth_failed"
_DOT_NOTATION = "patient." + "auth_failed"


def _write(root: Path, name: str, content: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _tokens(violations: tuple[EventNameViolation, ...]) -> list[str]:
    return [violation.token for violation in violations]


def _tracked_repo_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=repo_root, capture_output=True)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    files = [
        repo_root / raw.decode("utf-8", "replace") for raw in result.stdout.split(b"\x00") if raw
    ]
    return [path for path in files if path.is_file()]


def test_dot_notation_form_passes(tmp_path: Path) -> None:
    path = _write(tmp_path, "clean.md", f"Emit {_DOT_NOTATION} on rejection.\n")

    assert check_event_names([path]) == ()


def test_legacy_snake_case_form_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "dirty.md", f"Emit {_LEGACY} on rejection.\n")

    violations = check_event_names([path])
    assert len(violations) == 1
    assert violations[0].path == path
    assert violations[0].line == 1
    assert _tokens(violations) == [_LEGACY]


def test_builder_function_name_is_not_flagged(tmp_path: Path) -> None:
    path = _write(tmp_path, "events.py", "def patient_registered_envelope(...): ...\n")

    assert check_event_names([path]) == ()


def test_binary_file_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "blob.bin"
    path.write_bytes(b"\x00" + _LEGACY.encode() + b"\x00")

    assert check_event_names([path]) == ()


def test_repo_is_clean() -> None:
    assert check_event_names(_tracked_repo_files(REPO_ROOT)) == ()


def test_main_with_no_files_falls_back_to_the_full_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    dirty = _write(repo, "dirty.md", f"Emit {_LEGACY} on rejection.\n")
    subprocess.run(["git", "add", dirty.name], cwd=repo, check=True)
    monkeypatch.chdir(repo)

    assert main([]) == 1

    subprocess.run(["git", "rm", "--cached", "-q", dirty.name], cwd=repo, check=True)
    assert main([]) == 0
