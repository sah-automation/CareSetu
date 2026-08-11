"""Ticket #49: no-em-dash gate - fixture tests.

Feeds throwaway text files to ``scripts.check_em_dashes`` and asserts the
gate rejects U+2014 (em-dash) while passing plain ASCII, skips binary and
non-UTF-8 files, and that the real tracked repo is currently clean.
"""

import subprocess
from pathlib import Path

from scripts.check_em_dashes import (
    EmDashViolation,
    check_em_dashes,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write(root: Path, name: str, content: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _lines(violations: tuple[EmDashViolation, ...]) -> list[int]:
    return [violation.line for violation in violations]


def _tracked_repo_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=repo_root, capture_output=True)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    files = [
        repo_root / raw.decode("utf-8", "replace") for raw in result.stdout.split(b"\x00") if raw
    ]
    return [path for path in files if path.is_file()]


def test_clean_file_passes(tmp_path: Path) -> None:
    path = _write(tmp_path, "clean.md", "Use a simple dash - never an em-dash.\n")

    assert check_em_dashes([path]) == ()


def test_em_dash_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "dirty.md", "This is an em-dash \u2014 right here.\n")

    violations = check_em_dashes([path])
    assert len(violations) == 1
    assert violations[0].path == path
    assert violations[0].line == 1


def test_multiple_lines_reported_in_order(tmp_path: Path) -> None:
    path = _write(tmp_path, "dirty.txt", "one \u2014\nclean\nthree \u2014 four \u2014\n")

    assert _lines(check_em_dashes([path])) == [1, 3]


def test_binary_file_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "blob.bin"
    path.write_bytes(b"\x00\xe2\x80\x94\x00")

    assert check_em_dashes([path]) == ()


def test_non_utf8_file_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "legacy.txt"
    path.write_bytes(b"\x97\n")

    assert check_em_dashes([path]) == ()


def test_repo_is_clean() -> None:
    assert check_em_dashes(_tracked_repo_files(REPO_ROOT)) == ()
