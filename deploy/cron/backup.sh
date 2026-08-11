#!/usr/bin/env bash
# CareSetu daily Postgres backup (PHASE-1 T8b, #32).
#
# Dumps the single CareSetu PostgreSQL instance in PostgreSQL custom format
# (`pg_dump -Fc`) and encrypts it at rest (AES-256-CBC via `openssl enc` with a
# PBKDF2-derived key) into BACKUP_DIR with a UTC-timestamped filename. Fails
# loud on any error and prunes dumps older than BACKUP_RETENTION_DAYS.
#
# At-rest encryption of backups is a top-level rule
# (docs/standards/security-phii-standards.md §1) - these dumps are PHI, so the
# script refuses to write an unencrypted dump: BACKUP_PASSPHRASE must be set
# (from the VM environment / secret manager, never committed here).
#
# The daily cadence is the NFR-004 durability floor: recovery point objective
# (RPO) <= 24 h. The monthly restore-validation drill is PHASE-14 (roadmap
# §2.14, GAP-012). The CI smoke test (`.github/workflows/ci.yml`,
# `backup-smoke`) runs this exact script against a throwaway database and
# decrypts + restores the dump.
#
# No secrets are committed: every connection parameter and the encryption
# passphrase come from the environment. On the staging VM these are set by the
# crontab env block or a `.pgpass` file - never hardcoded here.

set -euo pipefail

: "${PGHOST:=localhost}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=caresetu}"
: "${PGUSER:=caresetu}"
: "${PGPASSWORD:=}"
: "${BACKUP_PASSPHRASE:=}"
: "${BACKUP_DIR:=/var/backups/caresetu}"
: "${BACKUP_RETENTION_DAYS:=14}"

if [ -z "${BACKUP_PASSPHRASE}" ]; then
  echo "backup FAILED: BACKUP_PASSPHRASE is unset; refusing to write an unencrypted dump" >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP_FILE="${BACKUP_DIR}/caresetu-${PGDATABASE}-${STAMP}.enc"

pg_dump \
  --host="${PGHOST}" \
  --port="${PGPORT}" \
  --username="${PGUSER}" \
  --dbname="${PGDATABASE}" \
  --format=custom \
  | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
      -pass "env:BACKUP_PASSPHRASE" \
      -out "${DUMP_FILE}"

if [ ! -s "${DUMP_FILE}" ]; then
  echo "backup FAILED: ${DUMP_FILE} is empty" >&2
  exit 1
fi

find "${BACKUP_DIR}" -name "caresetu-${PGDATABASE}-*.enc" -type f \
  -mtime "+${BACKUP_RETENTION_DAYS}" -delete

echo "backup OK: ${DUMP_FILE}"
