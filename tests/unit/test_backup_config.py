"""PHASE-1 T8b (#32): daily backup scaffolding lint - fixture tests.

Feeds throwaway ``deploy/cron/`` trees to ``scripts.check_backup_config`` and
asserts the acceptance criteria: the three committed files must exist and be
non-empty, ``backup.sh`` must be ``#!/usr/bin/env bash``, fail loud
(``set -euo pipefail``), invoke ``pg_dump`` into ``$BACKUP_DIR``, and carry no
committed secret; the cron file must schedule ``backup.sh`` daily; and the
README must document the RPO floor (RPO <= 24 h, daily cadence). The real
committed ``deploy/cron/`` tree must pass the same gate.
"""

from pathlib import Path

from scripts.check_backup_config import (
    DEFAULT_DEPLOY_ROOT,
    BackupViolation,
    check_backup_config,
)


def _write(root: Path, script: str, cron: str, readme: str) -> Path:
    cron_dir = root / "cron"
    cron_dir.mkdir(parents=True, exist_ok=True)
    (cron_dir / "backup.sh").write_text(script, encoding="utf-8")
    (cron_dir / "caresetu-backup.cron").write_text(cron, encoding="utf-8")
    (cron_dir / "README.md").write_text(readme, encoding="utf-8")
    return root


def _messages(violations: tuple[BackupViolation, ...]) -> list[str]:
    return [violation.message for violation in violations]


def _valid_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

: "${PGHOST:=localhost}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=caresetu}"
: "${PGUSER:=caresetu}"
: "${PGPASSWORD:=}"
: "${BACKUP_PASSPHRASE:=}"
: "${BACKUP_DIR:=/var/backups/caresetu}"

if [ -z "${BACKUP_PASSPHRASE}" ]; then
  exit 1
fi

mkdir -p "${BACKUP_DIR}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP_FILE="${BACKUP_DIR}/caresetu-${PGDATABASE}-${STAMP}.enc"

pg_dump --host="${PGHOST}" --dbname="${PGDATABASE}" --format=custom \\
  | openssl enc -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -out "${DUMP_FILE}"

if [ ! -s "${DUMP_FILE}" ]; then
  exit 1
fi
"""


def _valid_cron() -> str:
    return """# CareSetu daily backup cron.
30 1 * * * /opt/caresetu/deploy/cron/backup.sh >> /var/log/caresetu/backup.log 2>&1
"""


def _valid_readme() -> str:
    return """# CareSetu daily backup job

RPO <= 24 h, daily cadence (NFR-004 floor).
"""


def test_valid_fixture_passes(tmp_path: Path) -> None:
    root = _write(tmp_path, _valid_script(), _valid_cron(), _valid_readme())

    assert check_backup_config(root) == ()


def test_real_deploy_cron_passes() -> None:
    violations = check_backup_config(DEFAULT_DEPLOY_ROOT)

    assert violations == ()


def test_missing_script_rejected(tmp_path: Path) -> None:
    root = _write(tmp_path, "", _valid_cron(), _valid_readme())
    (root / "cron" / "backup.sh").unlink()

    messages = _messages(check_backup_config(root))

    assert any("missing" in message and "backup.sh" in message for message in messages)


def test_missing_cron_rejected(tmp_path: Path) -> None:
    root = _write(tmp_path, _valid_script(), "", _valid_readme())
    (root / "cron" / "caresetu-backup.cron").unlink()

    messages = _messages(check_backup_config(root))

    assert any("missing" in message and "cron" in message for message in messages)


def test_missing_readme_rejected(tmp_path: Path) -> None:
    root = _write(tmp_path, _valid_script(), _valid_cron(), "")
    (root / "cron" / "README.md").unlink()

    messages = _messages(check_backup_config(root))

    assert any("missing" in message and "README" in message for message in messages)


def test_empty_script_rejected(tmp_path: Path) -> None:
    root = _write(tmp_path, "  \n\n", _valid_cron(), _valid_readme())

    messages = _messages(check_backup_config(root))

    assert any("empty" in message and "backup.sh" in message for message in messages)


def test_missing_shebang_rejected(tmp_path: Path) -> None:
    script = _valid_script().replace("#!/usr/bin/env bash\n", "")
    root = _write(tmp_path, script, _valid_cron(), _valid_readme())

    messages = _messages(check_backup_config(root))

    assert any("shebang" in message or "#!/usr/bin/env bash" in message for message in messages)


def test_missing_fail_loud_rejected(tmp_path: Path) -> None:
    script = _valid_script().replace("set -euo pipefail\n", "")
    root = _write(tmp_path, script, _valid_cron(), _valid_readme())

    messages = _messages(check_backup_config(root))

    assert any("set -euo pipefail" in message for message in messages)


def test_missing_pg_dump_rejected(tmp_path: Path) -> None:
    script = _valid_script().replace("pg_dump", "psql")
    root = _write(tmp_path, script, _valid_cron(), _valid_readme())

    messages = _messages(check_backup_config(root))

    assert any("pg_dump" in message for message in messages)


def test_missing_backup_dir_rejected(tmp_path: Path) -> None:
    script = _valid_script().replace("${BACKUP_DIR}", "${DUMP_DIR}")
    root = _write(tmp_path, script, _valid_cron(), _valid_readme())

    messages = _messages(check_backup_config(root))

    assert any("$BACKUP_DIR" in message for message in messages)


def test_missing_openssl_rejected(tmp_path: Path) -> None:
    script = _valid_script().replace("openssl", "gpg")
    root = _write(tmp_path, script, _valid_cron(), _valid_readme())

    messages = _messages(check_backup_config(root))

    assert any("openssl" in message for message in messages)


def test_missing_passphrase_rejected(tmp_path: Path) -> None:
    script = _valid_script().replace("${BACKUP_PASSPHRASE}", "${BACKUP_KEY}")
    root = _write(tmp_path, script, _valid_cron(), _valid_readme())

    messages = _messages(check_backup_config(root))

    assert any("passphrase" in message for message in messages)


def test_literal_password_rejected(tmp_path: Path) -> None:
    script = _valid_script().replace(': "${PGPASSWORD:=}"', "PGPASSWORD=supersecret")
    root = _write(tmp_path, script, _valid_cron(), _valid_readme())

    messages = _messages(check_backup_config(root))

    assert any("literal PGPASSWORD" in message for message in messages)


def test_literal_backup_passphrase_rejected(tmp_path: Path) -> None:
    script = _valid_script().replace(': "${BACKUP_PASSPHRASE:=}"', "BACKUP_PASSPHRASE=supersecret")
    root = _write(tmp_path, script, _valid_cron(), _valid_readme())

    messages = _messages(check_backup_config(root))

    assert any("literal BACKUP_PASSPHRASE" in message for message in messages)


def test_password_flag_rejected(tmp_path: Path) -> None:
    script = _valid_script().replace("--format=custom", "--password=supersecret --format=custom")
    root = _write(tmp_path, script, _valid_cron(), _valid_readme())

    messages = _messages(check_backup_config(root))

    assert any("must not pass a password" in message for message in messages)


def test_placeholder_in_script_rejected(tmp_path: Path) -> None:
    root = _write(tmp_path, _valid_script() + "# TODO rotate key\n", _valid_cron(), _valid_readme())

    messages = _messages(check_backup_config(root))

    assert any("placeholder" in message and "TODO" in message for message in messages)


def test_weekly_schedule_rejected(tmp_path: Path) -> None:
    cron = _valid_cron().replace("30 1 * * * ", "30 1 * * 0 ")
    root = _write(tmp_path, _valid_script(), cron, _valid_readme())

    messages = _messages(check_backup_config(root))

    assert any("daily" in message and "schedule" in message for message in messages)


def test_cron_not_calling_backup_sh_rejected(tmp_path: Path) -> None:
    cron = _valid_cron().replace("backup.sh", "cleanup.sh")
    root = _write(tmp_path, _valid_script(), cron, _valid_readme())

    messages = _messages(check_backup_config(root))

    assert any("backup.sh" in message for message in messages)


def test_cron_placeholder_rejected(tmp_path: Path) -> None:
    root = _write(tmp_path, _valid_script(), _valid_cron() + "# CHANGE_ME\n", _valid_readme())

    messages = _messages(check_backup_config(root))

    assert any("placeholder" in message and "CHANGE_ME" in message for message in messages)


def test_readme_missing_rpo_rejected(tmp_path: Path) -> None:
    readme = _valid_readme().replace("RPO <= 24 h", "backups each day")
    root = _write(tmp_path, _valid_script(), _valid_cron(), readme)

    messages = _messages(check_backup_config(root))

    assert any("RPO" in message for message in messages)


def test_readme_missing_24h_rejected(tmp_path: Path) -> None:
    readme = _valid_readme().replace("RPO <= 24 h", "RPO under a day")
    root = _write(tmp_path, _valid_script(), _valid_cron(), readme)

    messages = _messages(check_backup_config(root))

    assert any("24 h" in message for message in messages)


def test_readme_missing_daily_rejected(tmp_path: Path) -> None:
    readme = _valid_readme().replace("daily", "hourly")
    root = _write(tmp_path, _valid_script(), _valid_cron(), readme)

    messages = _messages(check_backup_config(root))

    assert any("daily" in message for message in messages)
