"""PHASE-1 T8b (#32): daily backup scaffolding lint.

Lints ``deploy/cron/`` - the NFR-004 durability floor: a daily ``pg_dump`` of
the single CareSetu PostgreSQL instance, encrypted at rest, plus its cron
schedule. ``pg_dump``, ``openssl`` and a cron daemon are not available in the
lint pass (the real dump is exercised by the CI ``backup-smoke`` job against a
throwaway database), so "the scaffold is sound" is a deterministic lint pass
that asserts the contract:

- the three committed files exist and are non-empty;
- ``backup.sh`` starts with ``#!/usr/bin/env bash``, fails loud
  (``set -euo pipefail``), invokes ``pg_dump`` piped through ``openssl``
  (at-rest encryption - ``docs/standards/security-phii-standards.md`` §1)
  writing into ``$BACKUP_DIR``, and contains no committed secret (no literal
  ``PGPASSWORD=<value>`` / ``BACKUP_PASSPHRASE=<value>``, no ``--password=``
  on the command line);
- ``caresetu-backup.cron`` schedules ``backup.sh`` daily (numeric minute/hour,
  ``* * *`` for day-of-month/month/day-of-week);
- ``README.md`` documents the RPO floor (RPO <= 24 h, daily cadence);
- no unsubstituted placeholders remain (``CHANGE_ME``, ``example.com``, ...).

Stdlib-only by design: like the edge config gate, this runs on a bare
interpreter in pre-commit and CI without third-party dependencies.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DEPLOY_ROOT = REPO_ROOT / "deploy"

CRON_DIR_NAME = "cron"
BACKUP_SCRIPT_NAME = "backup.sh"
CRON_FILE_NAME = "caresetu-backup.cron"
README_NAME = "README.md"

BASH_SHEBANG = "#!/usr/bin/env bash"
FAIL_LOUD_MARKER = "set -euo pipefail"
PGDUMP_CMD = "pg_dump"
OPENSSL_CMD = "openssl"
BACKUP_DIR_REFS = ("$BACKUP_DIR", "${BACKUP_DIR}")
BACKUP_PASSPHRASE_REFS = ("$BACKUP_PASSPHRASE", "${BACKUP_PASSPHRASE}")

CRON_MINUTE_MAX = 59
CRON_HOUR_MAX = 23

PLACEHOLDER_MARKERS = (
    "CHANGE_ME",
    "YOUR_DOMAIN",
    "YOUR_HOST",
    "REPLACE_ME",
    "example.com",
    "TODO",
    "FIXME",
)

# minute(0-59) hour(0-23) * * * <command calling backup.sh>
CRON_DAILY_PATTERN = re.compile(
    r"^\s*(?P<minute>\d{1,2})\s+(?P<hour>\d{1,2})\s+\*\s+\*\s+\*\s+(?P<command>.+?)\s*$"
)


@dataclass(frozen=True)
class BackupViolation:
    """One rule break in the backup scaffolding under ``deploy/cron/``."""

    path: Path
    message: str


def _exists_violation(path: Path) -> BackupViolation | None:
    """A violation when ``path`` is not a present file, else ``None``."""
    if not path.is_file():
        return BackupViolation(path, f"missing {path}")
    return None


def _placeholder_violations(path: Path, display_name: str) -> list[BackupViolation]:
    """A violation per unsubstituted placeholder found in ``path``."""
    source = path.read_text(encoding="utf-8")
    violations: list[BackupViolation] = []
    for marker in PLACEHOLDER_MARKERS:
        if marker in source:
            violations.append(
                BackupViolation(path, f"unsubstituted placeholder left in {display_name}: {marker}")
            )
    return violations


def _script_secret_violation(path: Path) -> BackupViolation | None:
    """A violation when ``backup.sh`` commits a connection or encryption secret."""
    source = path.read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if "--password=" in stripped:
            return BackupViolation(
                path, "backup.sh must not pass a password on the pg_dump command line"
            )
        if "PGPASSWORD=" in stripped:
            value = stripped.split("PGPASSWORD=", 1)[1].strip()
            if value and not value.startswith("${"):
                return BackupViolation(path, "backup.sh must not commit a literal PGPASSWORD")
        if "BACKUP_PASSPHRASE=" in stripped:
            value = stripped.split("BACKUP_PASSPHRASE=", 1)[1].strip()
            if value and not value.startswith("${"):
                return BackupViolation(
                    path, "backup.sh must not commit a literal BACKUP_PASSPHRASE"
                )
    return None


def _script_violations(path: Path) -> list[BackupViolation]:
    """Assert the ``backup.sh`` contract; the file must exist and be non-empty."""
    missing = _exists_violation(path)
    if missing is not None:
        return [missing]
    source = path.read_text(encoding="utf-8")
    if not source.strip():
        return [BackupViolation(path, f"empty {BACKUP_SCRIPT_NAME}")]
    violations: list[BackupViolation] = []
    first_line = source.splitlines()[0] if source.splitlines() else ""
    if first_line != BASH_SHEBANG:
        violations.append(
            BackupViolation(path, f"{BACKUP_SCRIPT_NAME} must start with {BASH_SHEBANG}")
        )
    if FAIL_LOUD_MARKER not in source:
        violations.append(BackupViolation(path, f"{BACKUP_SCRIPT_NAME} must {FAIL_LOUD_MARKER}"))
    if PGDUMP_CMD not in source:
        violations.append(BackupViolation(path, f"{BACKUP_SCRIPT_NAME} must invoke {PGDUMP_CMD}"))
    if OPENSSL_CMD not in source:
        violations.append(
            BackupViolation(
                path,
                f"{BACKUP_SCRIPT_NAME} must encrypt at rest via {OPENSSL_CMD} "
                "(security-phii-standards.md §1)",
            )
        )
    if not any(ref in source for ref in BACKUP_DIR_REFS):
        violations.append(
            BackupViolation(path, f"{BACKUP_SCRIPT_NAME} must write into $BACKUP_DIR")
        )
    if not any(ref in source for ref in BACKUP_PASSPHRASE_REFS):
        violations.append(
            BackupViolation(
                path,
                f"{BACKUP_SCRIPT_NAME} must read the encryption passphrase from the environment",
            )
        )
    secret = _script_secret_violation(path)
    if secret is not None:
        violations.append(secret)
    violations.extend(_placeholder_violations(path, BACKUP_SCRIPT_NAME))
    return violations


def _cron_violations(path: Path) -> list[BackupViolation]:
    """Assert the cron file schedules ``backup.sh`` daily."""
    missing = _exists_violation(path)
    if missing is not None:
        return [missing]
    source = path.read_text(encoding="utf-8")
    if not source.strip():
        return [BackupViolation(path, f"empty {CRON_FILE_NAME}")]
    violations: list[BackupViolation] = []
    active_lines: list[re.Match[str]] = []
    for line in source.splitlines():
        match = CRON_DAILY_PATTERN.match(line)
        if match is not None:
            active_lines.append(match)
    if not active_lines:
        violations.append(
            BackupViolation(path, f"{CRON_FILE_NAME} must schedule {BACKUP_SCRIPT_NAME} daily")
        )
    for match in active_lines:
        if int(match.group("minute")) > CRON_MINUTE_MAX:
            violations.append(
                BackupViolation(path, f"cron minute out of range: {match.group('minute')}")
            )
        if int(match.group("hour")) > CRON_HOUR_MAX:
            violations.append(
                BackupViolation(path, f"cron hour out of range: {match.group('hour')}")
            )
        if BACKUP_SCRIPT_NAME not in match.group("command"):
            violations.append(BackupViolation(path, f"cron command must call {BACKUP_SCRIPT_NAME}"))
    violations.extend(_placeholder_violations(path, CRON_FILE_NAME))
    return violations


def _readme_violations(path: Path) -> list[BackupViolation]:
    """Assert the README documents the RPO floor and daily cadence."""
    missing = _exists_violation(path)
    if missing is not None:
        return [missing]
    source = path.read_text(encoding="utf-8")
    if not source.strip():
        return [BackupViolation(path, f"empty {README_NAME}")]
    violations: list[BackupViolation] = []
    if "RPO" not in source:
        violations.append(BackupViolation(path, f"{README_NAME} must document the RPO"))
    if "24 h" not in source and "24h" not in source:
        violations.append(BackupViolation(path, f"{README_NAME} must document RPO <= 24 h"))
    if "daily" not in source.lower():
        violations.append(BackupViolation(path, f"{README_NAME} must document the daily cadence"))
    violations.extend(_placeholder_violations(path, README_NAME))
    return violations


def check_backup_config(deploy_root: Path = DEFAULT_DEPLOY_ROOT) -> tuple[BackupViolation, ...]:
    """Lint ``deploy/cron/`` against the daily backup contract.

    Returns every violation, sorted by message, so the output is deterministic
    and the unit tests can assert on exact violations.
    """
    cron_dir = deploy_root / CRON_DIR_NAME
    violations: list[BackupViolation] = []
    violations.extend(_script_violations(cron_dir / BACKUP_SCRIPT_NAME))
    violations.extend(_cron_violations(cron_dir / CRON_FILE_NAME))
    violations.extend(_readme_violations(cron_dir / README_NAME))
    return tuple(sorted(violations, key=lambda violation: violation.message))


def main(argv: list[str] | None = None) -> int:
    """Run the backup scaffolding lint; exit 1 on violations."""
    parser = argparse.ArgumentParser(
        description="Lint deploy/cron/ (PHASE-1 T8b, #32).",
    )
    parser.add_argument(
        "--deploy-root",
        type=Path,
        default=DEFAULT_DEPLOY_ROOT,
        help=f"path to the deploy directory (default: {DEFAULT_DEPLOY_ROOT})",
    )
    args = parser.parse_args(argv)
    violations = check_backup_config(args.deploy_root)
    for violation in violations:
        print(f"{violation.path}: {violation.message}", file=sys.stderr)
    if violations:
        print(f"backup config check FAILED: {len(violations)} violation(s)", file=sys.stderr)
        return 1
    print("backup config check OK: deploy/cron/ satisfies the NFR-004 daily backup contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
