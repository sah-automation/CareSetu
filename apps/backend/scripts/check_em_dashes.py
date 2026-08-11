"""No-em-dash gate (Ticket #49).

Every tracked text file must avoid the U+2014 em-dash; the repo's docs and
briefs mandate plain hyphen-minus ``-`` instead. This gate scans the files
pre-commit passes it and fails when one contains U+2014, so the rule cannot
regress. Under ``npm run lint`` and CI (``pre-commit run --all-files``) that
is every repo file; on ``git commit`` it is the staged files.

Stdlib-only by design: like the other check_*.py gates, this runs on a bare
interpreter in pre-commit and CI without third-party dependencies.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

EM_DASH = "\u2014"
_BINARY_SNIFF_BYTES = 1024


@dataclass(frozen=True)
class EmDashViolation:
    """One U+2014 occurrence located in a scanned text file."""

    path: Path
    line: int


def _is_binary(path: Path) -> bool:
    """A NUL byte in the first chunk marks a non-text (binary) file."""
    with path.open("rb") as handle:
        return b"\x00" in handle.read(_BINARY_SNIFF_BYTES)


def scan_file(path: Path) -> list[EmDashViolation]:
    """Lines of ``path`` containing U+2014; empty for binary/non-UTF-8 files."""
    if _is_binary(path):
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    violations: list[EmDashViolation] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if EM_DASH in line:
            violations.append(EmDashViolation(path, line_number))
    return violations


def check_em_dashes(files: list[Path]) -> tuple[EmDashViolation, ...]:
    """Every U+2014 across ``files``, ordered by path then line."""
    violations = [violation for path in files for violation in scan_file(path)]
    return tuple(sorted(violations, key=lambda v: (str(v.path), v.line)))


def main(argv: list[str] | None = None) -> int:
    """Scan the given files; exit 1 when any U+2014 is found."""
    parser = argparse.ArgumentParser(
        description="Scan files for U+2014 em-dashes (Ticket #49).",
    )
    parser.add_argument("files", nargs="*", type=Path, help="files to scan")
    args = parser.parse_args(argv)
    files = [path for path in args.files if path.is_file()]
    violations = check_em_dashes(files)
    for violation in violations:
        print(
            f"{violation.path}:{violation.line}: em-dash (U+2014) found, use a simple '-'",
            file=sys.stderr,
        )
    if violations:
        print(f"em-dash check FAILED: {len(violations)} occurrence(s)", file=sys.stderr)
        return 1
    print("em-dash check OK: no U+2014 in scanned files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
