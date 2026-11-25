#!/usr/bin/env bash
# Create or update the APP_SECRETS_JSON secret in Google Secret Manager.
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - GCP project set (gcloud config set project PROJECT_ID)
#   - All 12 individual secrets available as environment variables
#     (or in a .env file that you source first)
#
# Usage:
#   source .env.production  # or export each secret manually
#   ./scripts/create_secret_blob.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Generate the JSON blob
cd "${PROJECT_ROOT}/apps/backend"
BLOB_JSON=$(uv run python scripts/generate_secret_blob.py)

if [[ -z "${BLOB_JSON}" || "${BLOB_JSON}" == "{}" ]]; then
    echo "Error: generated blob is empty. Check that secrets are set in environment." >&2
    exit 1
fi

echo "Generated secret blob (keys only):"
echo "${BLOB_JSON}" | python3 -c "import sys, json; print(list(json.load(sys.stdin).keys()))"

# Create or update the secret in Google Secret Manager
SECRET_NAME="APP_SECRETS_JSON"

if gcloud secrets describe "${SECRET_NAME}" >/dev/null 2>&1; then
    echo "Updating existing secret: ${SECRET_NAME}"
    printf "%s" "${BLOB_JSON}" | gcloud secrets versions add "${SECRET_NAME}" --data-file=-
else
    echo "Creating new secret: ${SECRET_NAME}"
    printf "%s" "${BLOB_JSON}" | gcloud secrets create "${SECRET_NAME}" --data-file=- --replication-policy=automatic
fi

echo "Done. Secret ${SECRET_NAME} is ready for Cloud Run deployment."
