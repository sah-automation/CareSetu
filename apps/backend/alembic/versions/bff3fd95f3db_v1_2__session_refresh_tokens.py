"""v1.2__session_refresh_tokens - rotating opaque refresh tokens on iam_sessions

PHASE-2 T7 (#58): sessions survive long past the 15-minute access window. Each
``iam_sessions`` row gains the refresh capability - ``refresh_token_hash`` is
the SHA-256 of an opaque, high-entropy refresh token (never the token itself,
mirroring the OTP "hashed at rest" rule) and ``refresh_expires_at`` carries the
~30-day sliding lifetime. A refresh rotates in place: the old row is revoked
(``revoked_at``) and a fresh row records the new access jti with the new
refresh hash, so a replayed old token finds its row and is rejected as revoked.
The unique index guards the hash lookup; NULLs (pre-migration rows) do not
conflict.

Revision ID: bff3fd95f3db
Revises: f28edd542d14
Create Date: 2026-08-13

"""

from collections.abc import Sequence

from alembic import op

revision: str = "bff3fd95f3db"
down_revision: str | Sequence[str] | None = "f28edd542d14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE iam.iam_sessions
            ADD COLUMN refresh_token_hash VARCHAR(256),
            ADD COLUMN refresh_expires_at TIMESTAMPTZ
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_iam_sessions_refresh_hash ON iam.iam_sessions (refresh_token_hash)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_iam_sessions_refresh_hash")
    op.execute(
        """
        ALTER TABLE iam.iam_sessions
            DROP COLUMN refresh_expires_at,
            DROP COLUMN refresh_token_hash
        """
    )
