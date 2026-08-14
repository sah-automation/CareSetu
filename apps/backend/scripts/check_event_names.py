"""Legacy snake_case event-name gate (tickets #54/#55 root cause).

The ``Envelope`` and ``HandlerRegistry`` enforce the ``domain.action``
grammar, so the legacy snake_case telemetry spelling (the underscore form of a
``patient.*`` or ``otp.*`` event, e.g. ``patient.auth_failed`` or ``otp.sent``)
can never be emitted at runtime. The failure mode is docs, tests, and log
markers carrying the legacy spelling, which keeps re-briefing agents wrong.
This gate scans the whole tree when invoked with no files (``git ls-files -z``,
as pre-commit does repo-wide) and fails when a file contains the legacy
snake_case form of a canonical gated event.

The forbidden spellings are derived from the canonical dot-notation names in
``bus.events`` (the single source of truth), never hardcoded here, so a new
canonical event automatically gates its legacy form. Matching uses word
boundaries, so the ``patient_registered_envelope`` and ``otp_sent_envelope``
builder function names (which merely prefix the token) are not flagged.

Stdlib-only by design: like the other check_*.py gates, this runs on a bare
interpreter in pre-commit and CI without third-party dependencies.
"""

from __future__ import annotations

import argparse
import re
import subprocess  # nosec B404 - git enumeration with a fixed argv list, no shell
import sys
from dataclasses import dataclass
from pathlib import Path

_GATED_DOMAINS = ("patient", "otp")
_BINARY_SNIFF_BYTES = 1024
_BACKEND_PACKAGE = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class EventNameViolation:
    """One legacy snake_case event spelling located in a scanned text file."""

    path: Path
    line: int
    token: str


def _legacy_tokens() -> tuple[str, ...]:
    """The forbidden snake_case spellings, derived from ``bus.events``.

    The import is deferred and the backend package is put on ``sys.path`` by
    hand so the gate stays stdlib-only: ``bus/events.py`` (and ``bus/__init__``)
    import nothing third-party.
    """
    sys.path.insert(0, str(_BACKEND_PACKAGE))
    import bus.events as events

    return tuple(
        value.replace(".", "_")
        for name, value in vars(events).items()
        if name.startswith("EVENT_") and value.split(".", 1)[0] in _GATED_DOMAINS
    )


def _patterns() -> list[re.Pattern[str]]:
    return [re.compile(rf"\b{re.escape(token)}\b") for token in _legacy_tokens()]


def _is_binary(path: Path) -> bool:
    """A NUL byte in the first chunk marks a non-text (binary) file."""
    with path.open("rb") as handle:
        return b"\x00" in handle.read(_BINARY_SNIFF_BYTES)


def scan_file(path: Path, patterns: list[re.Pattern[str]]) -> list[EventNameViolation]:
    """Lines of ``path`` containing a legacy snake_case event name."""
    if _is_binary(path):
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    violations: list[EventNameViolation] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern in patterns:
            match = pattern.search(line)
            if match is not None:
                violations.append(EventNameViolation(path, line_number, match.group(0)))
    return violations


def check_event_names(files: list[Path]) -> tuple[EventNameViolation, ...]:
    """Every legacy snake_case event spelling across ``files``."""
    patterns = _patterns()
    violations = [violation for path in files for violation in scan_file(path, patterns)]
    return tuple(sorted(violations, key=lambda v: (str(v.path), v.line, v.token)))


def _tracked_repo_files(repo_root: Path) -> list[Path]:
    """Every git-tracked, on-disk file under ``repo_root`` (``git ls-files -z``)."""
    result = subprocess.run(  # nosec B603 B607 - hardcoded argv, no shell, no user input
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.decode("utf-8", "replace"))
    files: list[Path] = []
    for raw in result.stdout.split(b"\x00"):
        if raw:
            path = repo_root / raw.decode("utf-8", "replace")
            if path.is_file():
                files.append(path)
    return files


def main(argv: list[str] | None = None) -> int:
    """Scan the given files (or the whole tree via ``git ls-files`` when none);
    exit 1 when a legacy event name is found."""
    parser = argparse.ArgumentParser(
        description="Scan files for legacy snake_case event names (tickets #54/#55).",
    )
    parser.add_argument("files", nargs="*", type=Path, help="files to scan")
    args = parser.parse_args(argv)
    files = [path for path in args.files if path.is_file()]
    if not args.files:
        files = _tracked_repo_files(Path.cwd())
    violations = check_event_names(files)
    for violation in violations:
        print(
            f"{violation.path}:{violation.line}: legacy snake_case event name "
            f"{violation.token!r}, use 'domain.action' dot-notation",
            file=sys.stderr,
        )
    if violations:
        print(
            f"event-name check FAILED: {len(violations)} occurrence(s)",
            file=sys.stderr,
        )
        return 1
    print("event-name check OK: no legacy snake_case event names in scanned files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
