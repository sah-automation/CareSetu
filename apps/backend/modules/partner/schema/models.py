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
PHASE-8 #601 adds the ``partner_pin_centroids`` reference dataset the doctor
profile's practice position resolves against: an all-India PIN-code vocabulary
with its centroid coordinates, seeded by migration, keyed by no row of ours.
PHASE-8 #606 (#599) gives ``partner_profiles`` the shape the profile redesign
writes into - a clinic name, a multi-valued specialty selection, the structured
address parts, multi-valued consulting days and consulting hours as prose - and
widens the directory entry's specialty to the same multi-valued shape, dropping
the CHECK constraint that could not hold a twenty-value vocabulary.
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
    Integer,
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
    # The building the practice is in, distinct from ``practice_name``, which is
    # the doctor's own name and stays the only patient-searchable name (#608
    # writes both).
    Column("clinic_name", String(120), nullable=True),
    # A DENORMALISED DISPLAY PROJECTION of the structured ``address_*`` parts
    # below, not a source of truth - and that is why it must never be edited by
    # hand. Three projections still read it: the private doctor profile view, the
    # operator verification queue row, and the operator per-partner detail row.
    # It has TWO writers: registration (``insert_registered_profile``) still
    # writes the pre-structured value it captured at sign-up, unchanged, and the
    # address section write (#609) rewrites it from the structured parts via
    # ``format_display_address``. ``NOT NULL`` for as long as registration is a
    # writer, which is why the column keeps its name, type and nullability
    # through #606 rather than being replaced.
    #
    # Practice location/geo is mandatory for every partner type (FEAT-014).
    Column("practice_address", Text, nullable=False),
    # The practice POSITION, not the practice address. SERVER-WRITTEN ONLY since
    # #606: no update schema accepts coordinates, so a client cannot place its own
    # pin, and #609 derives this from the declared ``address_pin`` against the
    # PIN centroids (#601). Deliberately not nullable - registration must write
    # it, and a partner whose position cannot be resolved is a gap in the PIN
    # dataset, not a column that should hold NULL.
    Column("practice_latitude", Numeric(9, 6), nullable=False),
    Column("practice_longitude", Numeric(9, 6), nullable=False),
    # The structured address, as declared by the doctor (#606). Five optional
    # parts mirroring ``AddressParts`` in ``domain/practice_position.py`` (#603);
    # every one is nullable because a half-finished address is a state a doctor
    # can hold. The display column above is what readers see.
    #
    # ``address_pin`` is deliberately NOT a foreign key to
    # ``partner_pin_centroids``, for the same reason ``service_area_id`` carries
    # none: it is a same-schema value the write resolves through the domain, so a
    # PIN that is malformed or absent from the dataset returns a field-level
    # error rather than failing the save on a data reason. The six-digit format
    # CHECK below is a format rule, not a vocabulary the domain has to own, and
    # it holds without a foreign key.
    Column("address_line", String(200), nullable=True),
    Column("address_landmark", String(200), nullable=True),
    Column("address_locality", String(120), nullable=True),
    Column("address_city", String(120), nullable=True),
    Column("address_pin", String(6), nullable=True),
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
    Column(
        "consultation_fee_paise",
        BigInteger,
        nullable=True,
    ),
    Column("photo_ref", String(255), nullable=True),
    Column("experience_years", Integer, nullable=True),
    # The kind of care this doctor offers, as a SELECTION rather than one label:
    # a district practice spans more than one, and the overlap search (#612)
    # matches on membership (#608 writes this column). Same multi-valued storage
    # shape as ``consulting_days`` and ``languages`` because that is the only
    # shape a closed-list validator can walk member by member. Validated against
    # ``Specialty`` in ``domain/vocabularies.py`` (#602), which owns roughly
    # twenty values - application-level, never a CHECK constraint, which is why
    # the column carries none.
    Column("specialties", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    # The languages this doctor consults in, validated against ``ConsultLanguage``
    # (#602). The column shape has not changed since #449; only its contents
    # have, from hand-typed free text ("Separate with commas") to selections of a
    # closed list. A pre-#606 row's hand-typed values were reset to the empty
    # array by migration #606 and never parsed.
    Column("languages", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("about", Text, nullable=True),
    # SUPERSEDED by ``consulting_hours`` (#606), retained rather than dropped.
    # It was a single free-text blob typed against a placeholder reading "e.g.
    # Mon-Sat, 9am-1pm"; splitting it into a closed day selection plus hours as
    # prose is what #610 writes. Nothing new writes this column and nothing does
    # now: #611 retired the whole-form write that last addressed it, so it is
    # inert rather than gone - kept until a migration of its own drops it (#606
    # deferred that deliberately). Its existing values are NOT parsed into the
    # two new columns - recovering chips from hand-typed free text is guesswork,
    # and a wrong guess is worse than an empty prompt.
    Column("availability", Text, nullable=True),
    # The days this doctor consults on, as a selection against ``ConsultingDay``
    # (#602), written by #610. "A week, not a working week" - the closed list
    # carries Saturday and Sunday because a weekend clinic is ordinary practice.
    Column("consulting_days", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    # The hours this doctor consults in, as PROSE (#610). Deliberately not
    # structured: no weekly template, no per-day slots, nothing that implies a
    # booking system the platform does not have. It is the half of the old
    # ``availability`` blob that is genuinely the doctor's own words.
    Column("consulting_hours", Text, nullable=True),
    Column(
        "notification_preferences",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    ),
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
    CheckConstraint(
        "consultation_fee_paise IS NULL OR consultation_fee_paise >= 0",
        name="ck_partner_profiles_consultation_fee",
    ),
    # Years of experience, a real range and not a sanity bound (#606, tightening
    # the pre-existing 0..100). 100 is not a value a practising doctor can hold:
    # medical entry in India is around 22-24, so the oldest plausible first
    # registration puts the ceiling near 60, and 60 leaves headroom over it. The
    # bound matters most at the TOP of the range - the field exists for the
    # longest-career doctors, so it must not refuse a legitimate value - which is
    # why the ceiling is 60 and not something tighter. Four places carry it and
    # they move together: this CHECK, the migration, and the ``Field`` bounds on
    # the update and view models. The profile page's own client-side LIMITS stays
    # 0..100, a superset that never refuses a legitimate value; #608/#611 own it.
    CheckConstraint(
        "experience_years IS NULL OR experience_years BETWEEN 0 AND 60",
        name="ck_partner_profiles_experience_years",
    ),
    # A format rule, not a vocabulary: the domain resolves whether a declared PIN
    # exists and what position it carries (#601's centroids, #603's
    # ``resolve_pin_code``), which no CHECK can express. Mirrors the centroid
    # table's own key CHECK.
    CheckConstraint(
        "address_pin IS NULL OR address_pin ~ '^[0-9]{6}$'",
        name="ck_partner_profiles_address_pin",
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
    # The doctor's declared specialty selection, copied from
    # ``partner_profiles.specialties`` at index time. MULTI-VALUED and nullable
    # since #606: a doctor practises more than one kind of care, the overlap
    # search (#612) matches on membership, and the column holds the same
    # JSONB-array shape the profile does.
    #
    # NULLABLE on purpose, unlike the profile's own ``specialties``. The value
    # is that selection copied verbatim by ``refresh_directory_entry`` (#607) -
    # the entry is a projection of the profile row and holds no vocabulary rule
    # of its own - so a doctor who has declared an empty selection carries
    # ``[]``. NULL is what every row written before #606 carries, and the
    # readers treat the two alike: the search's membership predicate fails
    # both, and ``representative_specialty`` projects both to no specialty.
    #
    # VALIDATION IS APPLICATION-LEVEL, and deliberately so. The retired
    # ``ck_partner_directory_index_specialty`` CHECK hard-coded the original four
    # values and could not follow #602's twenty-value pick-list, which is the
    # lockstep this comment used to describe. A CHECK cannot express "every
    # member is one of twenty values, and a non-doctor carries none" as readably
    # as the domain can: ``require_specialty``/``require_specialties`` in
    # ``domain/vocabularies.py`` validate a submitted value member by member, and
    # the search keeps its explicit ``partner_type = 'doctor'`` pin rather than
    # relying on "labs carry no specialty". The trade is that the database no
    # longer enforces the vocabulary; see ADR-0012, whose decision this amends.
    Column("specialty", JSONB, nullable=True),
    # Read-side active flag derived from partner status (de-index on activation
    # loss / credential invalidation). True when the partner is [Active].
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "partner_type IN ('doctor', 'lab', 'chemist')",
        name="ck_partner_directory_index_partner_type",
    ),
    # The specialty CHECK constraint is GONE (#606) - see the column comment for
    # why application-level validation against the domain vocabulary replaced it
    # and what was given up. Nothing else on this table changed.
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


partner_pin_centroids = Table(
    "partner_pin_centroids",
    MODULE_METADATA,
    # PHASE-8 #601: the all-India PIN centroid reference dataset the doctor
    # profile's practice position is resolved against. A vocabulary, not an
    # entity: the PIN is the natural key and there is no row of ours to point
    # at, so this table carries no foreign key (ADR-0003 also forbids the
    # cross-schema reference a FK would imply).
    #
    # The PIN is a fixed-width 6-character code and is stored as text, never as
    # an integer, so the value is never numerically reinterpreted. The
    # coordinate columns match the profile's practice position precision
    # (Numeric(9, 6)) so a resolved centroid drops straight into the
    # derived-position write.
    #
    # ``district`` and ``region`` are the read-only confirmation the doctor sees
    # back for the PIN they typed, so they are stored as the source publishes
    # them and need no translation table on the read side. ``region`` is India
    # Post's ``RegionName``, which is the placeholder ``DivReportingCircle``
    # wherever a circle publishes no region subdivision; that is stored as
    # published rather than substituted.
    Column("pin", String(6), primary_key=True),
    # The post office serving this PIN. A PIN is served by several offices and
    # the key admits one, so this is a representative office name, not a claim
    # that the PIN has a single office.
    Column("office_name", String(80), nullable=False),
    Column("district", String(80), nullable=False),
    Column("region", String(80), nullable=False),
    Column("latitude", Numeric(9, 6), nullable=False),
    Column("longitude", Numeric(9, 6), nullable=False),
    CheckConstraint("pin ~ '^[0-9]{6}$'", name="ck_partner_pin_centroids_pin_format"),
    CheckConstraint(
        "latitude BETWEEN -90 AND 90",
        name="ck_partner_pin_centroids_latitude",
    ),
    CheckConstraint(
        "longitude BETWEEN -180 AND 180",
        name="ck_partner_pin_centroids_longitude",
    ),
)


partner_outbox = outbox_table("partner_outbox", "partner", MODULE_METADATA)
