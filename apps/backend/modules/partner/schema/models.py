"""MOD-002: SQLAlchemy models for the ``partner`` schema only (ADR-0003).

Table namespace rule (coding-standards §2, T6a checker #26): every table is
prefixed with ``partner_`` and lives in the ``partner`` schema. PHASE-5 T1
(#244) lands the storage foundation the partner onboarding and gated
activation flow builds on: an open ``partner_profiles`` record carrying the
partner type and lifecycle status, the ``partner_service_areas`` vocabulary
it defaults to (Daltonganj at launch), the ``partner_credentials`` (credential
type, verified flag, expiry, encrypted artifact refs) submitted for review,
and the operator ``partner_verifications`` queue (per-round decision state).
The transactional outbox mirrors the shared ``bus/outbox_ddl.py`` shape
(single source of truth, ADR-0002); the ``consumed_events`` subscriber ledger
lives in the same schema but is materialized only by the migration and
addressed through ``bus.outbox_ddl.consumed_events_table``, never this
metadata (its name carries no module prefix by shared contract).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from bus.outbox_ddl import outbox_table

MODULE_METADATA = MetaData(schema="partner")


partner_service_areas = Table(
    "partner_service_areas",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    # Launch scope is Daltonganj (REQ-008); partners default here when they do
    # not declare a service area. Name is the human vocabulary the operator
    # console and Phase 6 search sort against.
    Column("name", String(80), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("name", name="uq_partner_service_areas_name"),
)


partner_profiles = Table(
    "partner_profiles",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    # The owning partner identity from MOD-001 (created sync at registration,
    # ADR-0010). No cross-schema FK - identity ids are gateway principals
    # (ADR-0003 module isolation).
    Column("identity_id", BigInteger, nullable=False),
    Column("partner_type", String(20), nullable=False),
    Column("status", String(30), nullable=False, server_default=text("'Registered'")),
    Column("practice_name", String(120), nullable=True),
    # Practice location/geo is mandatory for every partner type (FEAT-014).
    Column("practice_address", Text, nullable=False),
    Column("practice_latitude", Numeric(9, 6), nullable=False),
    Column("practice_longitude", Numeric(9, 6), nullable=False),
    # Optional service area, defaulting to Daltonganj (launch scope) when the
    # partner does not declare one; decided at the application layer.
    Column("service_area_id", BigInteger, nullable=True),
    # Rejected-partner recovery (PHASE-5 T09, #253): a one-time appeal flag
    # consumed on first use, and the re-submission throttle counters a rejected
    # partner exercises when re-applying. All three live on the profile (the
    # partner-wide verification lifecycle), never in iam/Redis - the throttle is
    # a domain/business rule protecting the operator queue (NFR-001, ADR-0008).
    Column("appeal_used", Boolean, nullable=False, server_default=text("false")),
    Column("re_submission_count", BigInteger, nullable=False, server_default=text("0")),
    Column("re_submission_blocked_until", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("identity_id", name="uq_partner_profiles_identity"),
    CheckConstraint(
        "partner_type IN ('doctor', 'lab', 'chemist')",
        name="ck_partner_profiles_partner_type",
    ),
    CheckConstraint(
        "status IN ('Registered', 'Under Verification', 'Active', 'Rejected')",
        name="ck_partner_profiles_status",
    ),
    CheckConstraint(
        "practice_longitude BETWEEN -180 AND 180",
        name="ck_partner_profiles_longitude",
    ),
    CheckConstraint(
        "practice_latitude BETWEEN -90 AND 90",
        name="ck_partner_profiles_latitude",
    ),
)


partner_credentials = Table(
    "partner_credentials",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column(
        "profile_id",
        BigInteger,
        ForeignKey("partner_profiles.id", name="fk_partner_credentials_profile"),
        nullable=False,
    ),
    # Closed enum per partner type (ADR-0008): doctor registers with medical
    # registration + qualification docs, labs with a lab license/accreditation,
    # chemists with a drug license / pharmacist registration.
    Column("credential_type", String(40), nullable=False),
    # The verification round this credential was submitted in
    # (S13, #266). Round-gates the duplicate gate: only the CURRENT round's
    # credential types are live for a re-offer, so a previously-rejected type
    # can be re-offered in a fresh round without tripping the duplicate check.
    Column("round", BigInteger, nullable=False, server_default=text("1")),
    Column("verified", Boolean, nullable=False, server_default=text("false")),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    # Close-out bookkeeping for a credential that is no longer valid (PHASE-6
    # T01, #307; ADR-0011). ``expires_at`` is the recorded renewal date; the
    # three columns below record WHY/HOW a credential stopped being valid:
    # ``revoked_at`` is the instant the close-out was recorded (expiry sweep or
    # operator revocation), ``revoked_by`` the acting authority/operator
    # (a UUID principal), and ``invalidation_reason`` the closed reason
    # (expired | revoked | reverification_failed). NULL means the credential is
    # still live (nothing has closed it out). These serve the lazy read-hide +
    # daily-sweep derivation - never a background scanner.
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("revoked_by", UUID, nullable=True),
    Column("invalidation_reason", String(40), nullable=True),
    # References into encrypted object storage under the ``partner/`` prefix
    # (security-phii-standards). Never the document bytes themselves.
    Column("artifact_refs", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    # US-27 credential-document cleanup (ticket #263): the moment a permanent
    # rejection schedules document removal is ``now() + cleanup window``. NULL
    # means no cleanup is scheduled (credential still live / under review). The
    # ``purge_expired_credentials`` facade seam deletes the row (and its
    # artifact files) once ``cleanup_due_at <= now`` and the profile is still
    # ``[Rejected]``.
    Column("cleanup_due_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "credential_type IN ("
        "'medical_registration', 'qualification_certificate', "
        "'lab_license', 'accreditation', "
        "'drug_license', 'pharmacist_registration'"
        ")",
        name="ck_partner_credentials_credential_type",
    ),
    # Lockstep with the CredentialInvalidatedReason vocabulary (domain
    # credentials.py): a close-out reason is one of expired | revoked |
    # reverification_failed. NULL means the credential is still live (no
    # close-out recorded) - never a reason value.
    CheckConstraint(
        "invalidation_reason IS NULL OR invalidation_reason IN "
        "('expired', 'revoked', 'reverification_failed')",
        name="ck_partner_credentials_invalidation_reason",
    ),
    Index("ix_partner_credentials_profile", "profile_id"),
    # Partial so the 30-day purge scan touches only scheduled rows.
    Index(
        "ix_partner_credentials_cleanup_due",
        "cleanup_due_at",
        postgresql_where=text("cleanup_due_at IS NOT NULL"),
    ),
    # Partial so the daily expiry close-out sweep (PHASE-6 T04b #316, remediation
    # #323) touches only live verified candidates instead of scanning the whole
    # credential table. The close-out marker (``invalidation_reason IS NULL``) is
    # the sweep's idempotency key, so replayed passes find nothing to scan.
    Index(
        "ix_partner_credentials_expiry_due",
        "expires_at",
        postgresql_where=text(
            "expires_at IS NOT NULL AND invalidation_reason IS NULL AND verified"
        ),
    ),
)


partner_verifications = Table(
    "partner_verifications",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column(
        "profile_id",
        BigInteger,
        ForeignKey("partner_profiles.id", name="fk_partner_verifications_profile"),
        nullable=False,
    ),
    # Per-round counter so the audit trail and the operator queue distinguish
    # first-time verification from re-submission / appeal rounds.
    Column("round", BigInteger, nullable=False, server_default=text("1")),
    Column("status", String(20), nullable=False, server_default=text("'queued'")),
    Column("decision", String(20), nullable=True),
    # Required on reject - the specific failure surfaced to the partner and
    # recorded in the audit trail.
    Column("decision_reason", Text, nullable=True),
    # The operator identity (an iam gateway principal) who decided this round.
    # No cross-schema FK - operator ids come from MOD-001 (ADR-0003 isolation).
    Column("decision_by", BigInteger, nullable=True),
    # Per-round trail: when this round entered the operator queue and when it
    # was decided.
    Column("verification_started_at", DateTime(timezone=True), nullable=True),
    Column("decided_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "status IN ('queued', 'in_review', 'approved', 'rejected')",
        name="ck_partner_verifications_status",
    ),
    CheckConstraint(
        "decision IN ('approved', 'rejected')",
        name="ck_partner_verifications_decision",
    ),
    Index("ix_partner_verifications_queue", "status", "created_at"),
    Index("ix_partner_verifications_profile", "profile_id", "round"),
)


partner_directory_index = Table(
    "partner_directory_index",
    MODULE_METADATA,
    # One row per [Active] partner (ADR-0012): the partner id is the PK and
    # FK back to its profile. No cross-schema FK - the directory entry is a
    # read-side cache of the partner's own profile, so it may carry the
    # directly-forked profile fields without an iam read (ADR-0003 isolation).
    Column(
        "partner_id",
        BigInteger,
        ForeignKey("partner_profiles.id", name="fk_partner_directory_index_partner"),
        primary_key=True,
    ),
    # Forked from partner_profiles at index time (practice location is already
    # NOT NULL there, PHASE-5 T01). Mirroring them here keeps the directory a
    # self-contained read-side cache for distance sort (FEAT-004) without a
    # join back to the profile on every search (MOD-002 NFR: search p95 < 250 ms
    # cached).
    Column("practice_latitude", Numeric(9, 6), nullable=False),
    Column("practice_longitude", Numeric(9, 6), nullable=False),
    Column("partner_type", String(20), nullable=False),
    # Closed pick-list, doctors only (ADR-0012, glossary). Labs and chemists
    # carry NULL - the field is never free-form. Kept in lockstep with the
    # Specialty vocabulary (domain credentials.py).
    Column("specialty", String(40), nullable=True),
    # Read-side active flag derived from partner status (de-index on activation
    # loss / credential invalidation). True when the partner is [Active].
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "partner_type IN ('doctor', 'lab', 'chemist')",
        name="ck_partner_directory_index_partner_type",
    ),
    # Specialty only from the closed list, and only for doctors (ADR-0012,
    # glossary). Labs and chemists must always carry NULL - the field is never
    # free-form. Kept in lockstep with the Specialty vocabulary (domain
    # credentials.py).
    CheckConstraint(
        "specialty IS NULL OR (partner_type = 'doctor' AND specialty IN "
        "('General Physician', 'Pediatrician', 'Gynecologist', 'Dentist'))",
        name="ck_partner_directory_index_specialty",
    ),
    CheckConstraint(
        "practice_longitude BETWEEN -180 AND 180",
        name="ck_partner_directory_index_longitude",
    ),
    CheckConstraint(
        "practice_latitude BETWEEN -90 AND 90",
        name="ck_partner_directory_index_latitude",
    ),
    # Search filters by partner type, then geo distance; avoid paying an extra
    # seq scan when filtering by a type. Active-only reads are the common case.
    Index("ix_partner_directory_index_type_active", "partner_type", "is_active"),
)


partner_outbox = outbox_table("partner_outbox", "partner", MODULE_METADATA)
