"""v9.3__runtime_capture_and_product - the runtime-capture and product table set (B8 #726)

PHASE-14A B8 (#726, plan-phase14 §8): the second and last of the spec's two
additive observability migrations (#717 decision 43). The v9.2 set made AI spend
attributable; this one makes RUNTIME and PRODUCT behaviour queryable from the
same system of record. Four tables, all created here, of which this ticket writes
one:

``observability_error_events`` - the captured server-error stream. One row per
DISTINCT failure fingerprint, carrying ``occurrences`` and ``last_seen_at`` so a
loop of identical failures collapses into a single entry instead of burying every
other error (#717 decision 14). The ``fingerprint`` column is UNIQUE and is the
collapse key; it is derived only from the STABLE attributes of a failure -
templated route, method, status code, error kind and error code - never from the
trace id or the timestamp, because a fingerprint containing either of those
collapses nothing (#717 decision 14, and the handoff note that fixes it here for
the #730 error feed to read).

``route_template`` is the ROUTE TEMPLATE, not the concrete request path. The
capture seam resolves it from the MATCHED route and never from
``request.url.path``, which is what keeps telemetry cardinality bounded and keeps
an identifier out of it (#717 decision 13); the column is what that rule is
worth, so the seam that fills it is the seam under test. Every column here is
PHI-free by construction: no body, no query string, no header, no exception text -
only the envelope's fixed code, which error-handling-observability §1 already
requires to be a stable, human-safe string.

``observability_http_minute`` - the per-minute HTTP counter (#717 decision 15):
one row per ``(minute, route template, method, status class)`` rather than one
write per request, which is what makes throughput and error rate queryable from
Postgres beyond the free tier's fourteen-day retention at a bounded write cost.
``status_class`` is the COLLAPSED class (``2xx`` / ``3xx`` / ``4xx`` / ``5xx``) and
never a raw status code, checked here, so series cardinality cannot explode
(#717 decisions 15 and 37). ``errors`` is the 5xx subset of ``requests``, carried
alongside rather than re-derived, so the error rate is a stored numerator over a
stored denominator instead of a second scan of the table.

``observability_product_events`` - the product event ledger (#717 decision 22).
One row per consumed product event, carrying the occurrence timestamp, a
PSEUDONYMOUS actor key (never the raw identity reference), the session key, the
trace identifier that joins the platform (#717 decision 41), the funnel name, the
step, the outcome and the duration.
``event_id`` is UNIQUE so "one row per event" is enforced rather than assumed: the
consumed-event ledger already makes a redelivery of the SAME event a no-op, and
this makes a SECOND event identifier collide visibly instead of double-counting a
funnel step - the same belt-and-braces #723 takes on ``ai_job_ref``. ``actor_kind``
and ``actor_key`` are both nullable and both NULL together: a step a machine
finished (a background structuring pass completing a workflow) has no human
behind it, and recording a placeholder actor there would inflate the active-user
count that decision 26 derives from exactly this column.

``observability_product_daily`` - the daily product rollup the long windows and
the cohorts read, so a thirty-day query never scans the raw ledger
(#717 decision 22). Recomputed in full each pass, never incremented, exactly as
``observability_attribution_daily`` is: a late-arriving actor key is filled in by
the next pass without double counting. It carries ``events``, ``actor_count`` (the
distinct pseudonymous actors - the daily-active-user numerator decision 26 needs),
and ``total_duration_ms`` with ``duration_samples``. The SUM and not a median,
deliberately: a median cannot be derived from a total, and carrying a column that
looks like a median because it was computed from the aggregate is how a funnel's
"thinking time" quietly becomes a mean. A reader needing the median takes it from
the ledger over its own window.

Both product tables carry ``outcome`` from the CLOSED vocabulary decision 23
fixes - ``completed``, ``abandoned``, ``errored`` - plus ``re_recorded``, which
decision 25 gives its own outcome because a corrected attempt is not scored as a
failure of the original. A CHECK constraint makes a fourth value a migration, not
a silent third state (the same rule ``observability_rollup_runs.mode`` follows).

Every identity on both product tables is a one-way domain-separated hash produced
by ``domain.pseudonym.actor_key``; the raw reference never reaches this schema, and
no clinical content is carried on any of the four tables (ADR-0025 D7,
security-phii-standards). Nothing here alters an existing table's semantics - all
four are additive creations. Table names follow the namespace prefix rule
(coding-standards §2) - ``observability_*`` - and there are no cross-schema foreign
keys, so the ``migration-check`` FK scan stays clean (ADR-0003).

Written by hand (ADR-0003 - a migration never imports current source), in the
raw ``op.execute`` DDL idiom of ``v7_0__init_intake``.

Revision ID: c7a4e9b1d268
Revises: e7c4a19d5b83
Create Date: 2026-10-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7a4e9b1d268"
down_revision: str | Sequence[str] | None = "e7c4a19d5b83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # observability_error_events - the captured server-error stream
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE observability.observability_error_events (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            -- The collapse key (#717 decision 14). UNIQUE because "one row per
            -- distinct failure" is the grain that keeps an error storm from
            -- burying every other error; without it the drain would append a row
            -- per occurrence and the feed (#730) would have to do the collapsing.
            fingerprint VARCHAR(64) NOT NULL,
            route_template VARCHAR(200) NOT NULL,
            method VARCHAR(10) NOT NULL,
            status_code INT NOT NULL,
            -- The COLLAPSED status class, never the raw code, so a run of 500/502
            -- on one route is one entry rather than several.
            status_class VARCHAR(3) NOT NULL,
            -- ``unhandled_exception`` (an exception escaped the module handlers)
            -- or ``server_error_response`` (a 5xx was answered without one). Both
            -- are captured, so a swallowed exception is not invisible
            -- (#717 story 27).
            kind VARCHAR(30) NOT NULL,
            -- The envelope's stable code - a fixed, human-safe string, never
            -- internal detail (error-handling-observability §1).
            code VARCHAR(64) NOT NULL DEFAULT '',
            -- The cross-tool join key (#717 decision 41): the same id the logs,
            -- the tracing backend and the AI backend carry, so one click reaches
            -- the trace. The MOST RECENT occurrence's, which is the one an
            -- operator jumping from the feed wants.
            trace_id VARCHAR(64) NOT NULL,
            -- 1 on first sight; the drain INCREMENTS this on a repeat, which is
            -- how a loop is reported as a count rather than as noise.
            occurrences INT NOT NULL DEFAULT 1,
            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_observability_error_events_fingerprint UNIQUE (fingerprint),
            CONSTRAINT ck_observability_error_events_status_class
                CHECK (status_class IN ('2xx', '3xx', '4xx', '5xx')),
            CONSTRAINT ck_observability_error_events_kind
                CHECK (kind IN ('unhandled_exception', 'server_error_response')),
            CONSTRAINT ck_observability_error_events_occurrences
                CHECK (occurrences >= 1)
        )
        """
    )
    # The feed reads newest first over a bounded window; a fingerprint that
    # recurs is updated in place, so last_seen_at leads. Ascending, matching
    # ``schema/models.py`` and every other index in this schema: a plain btree is
    # scanned in either direction, so the descending form bought nothing and the
    # two declarations drifting apart would mislead the next reader.
    op.execute(
        "CREATE INDEX ix_observability_error_events_last_seen "
        "ON observability.observability_error_events (last_seen_at)"
    )
    op.execute(
        "CREATE INDEX ix_observability_error_events_route "
        "ON observability.observability_error_events (route_template)"
    )

    # ------------------------------------------------------------------
    # observability_http_minute - the per-minute HTTP counter (#727 reads it)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE observability.observability_http_minute (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            -- Truncated to the minute in UTC: the grain the whole table exists for
            -- (#717 decision 15).
            minute_ts TIMESTAMPTZ NOT NULL,
            route_template VARCHAR(200) NOT NULL,
            method VARCHAR(10) NOT NULL,
            status_class VARCHAR(3) NOT NULL,
            requests BIGINT NOT NULL DEFAULT 0,
            -- The 5xx subset of ``requests``, carried alongside so the error rate
            -- is a stored numerator over a stored denominator. NEVER larger than
            -- ``requests``: the CHECK below is what stops a writer from reporting
            -- more failures than traffic.
            errors BIGINT NOT NULL DEFAULT 0,
            CONSTRAINT uq_observability_http_minute_scope
                UNIQUE (minute_ts, route_template, method, status_class),
            CONSTRAINT ck_observability_http_minute_status_class
                CHECK (status_class IN ('2xx', '3xx', '4xx', '5xx')),
            CONSTRAINT ck_observability_http_minute_errors
                CHECK (errors >= 0 AND errors <= requests),
            CONSTRAINT ck_observability_http_minute_requests
                CHECK (requests >= 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_observability_http_minute_ts "
        "ON observability.observability_http_minute (minute_ts)"
    )

    # ------------------------------------------------------------------
    # observability_product_events - the product event ledger (#739 writes it)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE observability.observability_product_events (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            -- The delivered event's own id, UNIQUE: the ledger row's identity IS
            -- the event that reported it. The consumed-event ledger already makes
            -- a redelivery of the same id a no-op; this makes a second event id
            -- about the same occurrence a visible constraint violation rather than
            -- a silently doubled funnel step.
            event_id UUID NOT NULL,
            occurred_at TIMESTAMPTZ NOT NULL,
            -- ``patient`` or ``doctor``, NULLABLE together with ``actor_key``: a
            -- step a machine finished has no human behind it, and a placeholder
            -- actor there would inflate the active-user count decision 26 derives
            -- from this column.
            actor_kind VARCHAR(20),
            -- A one-way domain-separated hash of the identity reference
            -- (``domain.pseudonym.actor_key``), never the raw reference.
            actor_key VARCHAR(64),
            -- The session the step belongs to, so a funnel is one journey rather
            -- than a pile of unrelated events.
            session_key VARCHAR(64) NOT NULL,
            -- The cross-tool join key (#717 decision 41). NOT NULL: decision 41
            -- and the product spec both make the trace id the thing that lets any
            -- funnel number be traced back to the real user journey.
            trace_id VARCHAR(64) NOT NULL,
            -- The registry-driven funnel and step names (#717 decision 23): adding
            -- a step is a registry entry, never a migration.
            funnel VARCHAR(50) NOT NULL,
            step VARCHAR(50) NOT NULL,
            outcome VARCHAR(20) NOT NULL,
            -- The step's own duration, nullable: not every event marks a span.
            duration_ms INT,
            CONSTRAINT uq_observability_product_events_event UNIQUE (event_id),
            CONSTRAINT ck_observability_product_events_actor_kind
                CHECK (actor_kind IS NULL OR actor_kind IN ('patient', 'doctor')),
            -- Actor kind and key are set together or not at all - a key with no
            -- kind cannot be attributed to a half and would be counted twice by a
            -- reader that groups by kind.
            CONSTRAINT ck_observability_product_events_actor_pair
                CHECK ((actor_kind IS NULL) = (actor_key IS NULL)),
            CONSTRAINT ck_observability_product_events_outcome
                CHECK (outcome IN ('completed', 'abandoned', 'errored', 're_recorded')),
            CONSTRAINT ck_observability_product_events_duration
                CHECK (duration_ms IS NULL OR duration_ms >= 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_observability_product_events_occurred "
        "ON observability.observability_product_events (occurred_at)"
    )
    op.execute(
        "CREATE INDEX ix_observability_product_events_funnel_step "
        "ON observability.observability_product_events (funnel, step, outcome)"
    )
    # Daily active users are the DISTINCT actors over a day, so the actor leads
    # its own composite index.
    op.execute(
        "CREATE INDEX ix_observability_product_events_actor "
        "ON observability.observability_product_events (actor_key, occurred_at)"
    )
    op.execute(
        "CREATE INDEX ix_observability_product_events_trace "
        "ON observability.observability_product_events (trace_id)"
    )

    # ------------------------------------------------------------------
    # observability_product_daily - the daily product rollup (#739 computes it)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE observability.observability_product_daily (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            event_date DATE NOT NULL,
            funnel VARCHAR(50) NOT NULL,
            step VARCHAR(50) NOT NULL,
            outcome VARCHAR(20) NOT NULL,
            -- Every counter is written in FULL by each pass rather than
            -- incremented, which is what makes a late-arriving actor key
            -- idempotent: the next pass fills it in without double counting -
            -- the same rule observability_attribution_daily follows (decision 6).
            events BIGINT NOT NULL DEFAULT 0,
            -- Distinct pseudonymous actors over the day. This is the
            -- daily-active-user numerator decision 26 derives from the ledger,
            -- counted here so a long window never re-counts the raw ledger.
            actor_count INT NOT NULL DEFAULT 0,
            -- The SUM of step durations and how many steps carried one. A SUM, not
            -- a median: a median cannot be derived from a total, and a column that
            -- looks like a median because it was computed from an aggregate is how
            -- a funnel's thinking time quietly becomes a mean. A reader needing the
            -- median takes it from the ledger over its own window.
            total_duration_ms BIGINT NOT NULL DEFAULT 0,
            duration_samples BIGINT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_observability_product_daily_scope
                UNIQUE (event_date, funnel, step, outcome),
            CONSTRAINT ck_observability_product_daily_outcome
                CHECK (outcome IN ('completed', 'abandoned', 'errored', 're_recorded')),
            CONSTRAINT ck_observability_product_daily_counts
                CHECK (events >= 0 AND actor_count >= 0 AND total_duration_ms >= 0
                       AND duration_samples >= 0),
            CONSTRAINT ck_observability_product_daily_samples
                CHECK (duration_samples <= events)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_observability_product_daily_date_funnel "
        "ON observability.observability_product_daily (event_date, funnel)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS observability.observability_product_daily")
    op.execute("DROP TABLE IF EXISTS observability.observability_product_events")
    op.execute("DROP TABLE IF EXISTS observability.observability_http_minute")
    op.execute("DROP TABLE IF EXISTS observability.observability_error_events")
