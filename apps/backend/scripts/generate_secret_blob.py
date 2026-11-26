#!/usr/bin/env python3
"""Generate APP_SECRETS_JSON from individual environment variables.

This script reads the 12 individual secret values from the environment
and outputs a single JSON blob suitable for storing as APP_SECRETS_JSON
in Google Secret Manager.

Usage:
    export DATABASE_URL="..."
    export GATEWAY_JWT_SIGNING_KEY="..."
    # ... set all 12 secrets as env vars ...
    python scripts/generate_secret_blob.py

Or source a .env file first:
    source .env.production && python scripts/generate_secret_blob.py

The output is a JSON object printed to stdout. Pipe to a file or
directly to `gcloud secrets create` / `gcloud secrets versions add`.
"""

import json
import os
import sys

from app.config import SECRET_BLOB_KEY_MAP


def main() -> int:
    # Build the secret blob from environment variables
    secret_blob: dict[str, str] = {}
    missing: list[str] = []

    for blob_key, env_name in SECRET_BLOB_KEY_MAP.items():
        value = os.environ.get(env_name.upper())
        if value is None:
            # Also try the exact blob key as env var name (for convenience)
            value = os.environ.get(blob_key.upper())
        if value is not None:
            secret_blob[blob_key] = value
        else:
            missing.append(env_name.upper())

    if missing:
        print(f"Warning: missing environment variables: {', '.join(missing)}", file=sys.stderr)
        print(
            "These will be omitted from the blob (app will fall back to individual env vars).",
            file=sys.stderr,
        )

    # Output as compact JSON
    json.dump(secret_blob, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
