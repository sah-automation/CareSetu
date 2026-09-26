"""MOD-001: Identity sub-facade (ADR-0006, ticket #169).

Extracts the identity registration lifecycle from the coordinator
``IamFacade``: ``register_patient`` and its result model
``RegisterPatientResult``.  The sub-facade accepts an ``OtpSender`` port
(from ``domain/shared.py``) instead of adapter types, and imports
lockout/challenge helpers from ``domain/shared.py``.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.config import DEFAULT_PROFILE_MEDIA_MAX_UPLOAD_BYTES
from bus.outbox_writer import write_outbox
from modules.iam.domain import events
from modules.iam.domain.exceptions import (
    IamError,
    PatientProfileNotSetError,
    ProfilePhotoTransferError,
    ProfilePhotoValidationError,
)
from modules.iam.domain.otp import (
    MAX_ATTEMPTS,
    OTP_TTL_SECONDS,
    RESEND_COOLDOWN_SECONDS,
)
from modules.iam.domain.phone import normalize_phone
from modules.iam.domain.shared import (
    OtpSender as OtpSender,
)
from modules.iam.domain.shared import (
    _issue_challenge,
    _lock_identity_row,
    _reissue_otp_challenge,
)
from modules.iam.outbox import IAM_OUTBOX_TABLE
from modules.iam.schema.models import iam_identities, iam_patient_profiles
from modules.iam.session_facade import grant_operator_role
from modules.profile_media.facade import PATIENT_PREFIX, ProfileMediaStore

_IAM_SCHEMA = "iam"


class RegisterPatientResult(BaseModel):
    """Outcome of the begin-or-resume entry, as the PWA renders it (spec #51 sec 2.1/2.4).

    ``sent``: a challenge was issued (first-time registration or an
    out-of-cooldown login) and the challenge fields seed the countdown ring,
    the resend cooldown, and the attempts-left strip; ``is_existing``/``flow``
    tell the client which notice to show. ``cooldown``/``locked``/``suspended``:
    the entry was refused exactly like a resend - no fresh challenge was issued
    and no SMS was sent - and the PWA stays on the phone step with the matching
    countdown or lockout state. ``no_identity`` is impossible on this path: the
    single begin-or-resume entry always resolves to an identity.
    """

    outcome: Literal["sent", "cooldown", "locked", "suspended"]
    phone_e164: str
    identity_id: int
    challenge_id: int | None = None
    is_existing: bool
    flow: Literal["register", "login"]
    expires_in_seconds: int | None = None
    cooldown_remaining_seconds: int | None = None
    attempts_left: int | None = None
    lockout_remaining_seconds: int | None = None


class PartnerCredentialCreatedResult(BaseModel):
    """Outcome of creating a partner credential account (ADR-0010, ticket #245).

    The identity is created ``[Unverified]`` with no role grant, so it is
    login-capable via phone-OTP from the moment the partner registers but holds
    no ``partner`` role scope until activation (the role grant is the
    activation-gated step, T03 #246). ``identity_id`` and ``phone_e164`` let
    the ``partner`` module persist its own row in the same transaction.
    """

    identity_id: int
    phone_e164: str


class OperatorInvitedResult(BaseModel):
    """Outcome of inviting a new operator (T07, ticket #250).

    The invited identity is created ``[Unverified]`` with an ``Active``
    ``operator`` role grant, so the invited phone can complete MFA at first
    login and then hold the ``operator`` scope - there is no self-registration
    path, only this credentialed operator-invites-operator flow.
    """

    identity_id: int
    phone_e164: str


class PatientProfile(BaseModel):
    """The patient's profile-completion data (PHASE-8.1 T1, #482; FEAT-008).

    One row per identity, persisted in ``iam.iam_patient_profiles`` so a
    returning patient is asked only once. ``area``, the emergency contact, and
    the photo reference are optional and unsettable; ``preferred_language``
    mirrors what the PWA's locale picker chose (en/hi) and persists with the
    profile but never drives the app locale (ticket #488 keeps its own store).
    Extra fields are refused (``extra="forbid"``, the iam surface convention)
    so a client typo cannot silently widen the stored shape. String bounds
    mirror the ``VARCHAR`` column widths so an over-long value is a 422 at the
    edge, never a ``DataError`` 500 at the database (api-standards §2).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    age: int = Field(gt=0, lt=150)
    gender: str = Field(min_length=1, max_length=20)
    preferred_language: str = Field(min_length=1, max_length=20)
    area: str | None = Field(default=None, max_length=255)
    emergency_contact: str | None = Field(default=None, max_length=32)
    photo_ref: str | None = Field(default=None, max_length=255)


#: JPG/PNG/WebP are the only profile-photo content types admitted (US-20).
MEDIA_TYPE_JPEG: Final[str] = "image/jpeg"
MEDIA_TYPE_PNG: Final[str] = "image/png"
MEDIA_TYPE_WEBP: Final[str] = "image/webp"
ALLOWED_PHOTO_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {MEDIA_TYPE_JPEG, MEDIA_TYPE_PNG, MEDIA_TYPE_WEBP}
)

#: Profile-photo size ceiling (US-20): any photo over the configured ceiling is
#: refused. NOT an independent literal: it aliases the settings default, which
#: is the single source of the value (coding-standards §9.2). The composition
#: root injects the resolved ``PROFILE_MEDIA_MAX_UPLOAD_BYTES`` into
#: ``IdentityFacade`` so raising the env var moves the patient and doctor photo
#: limits together; this alias is only the no-argument default.
MAX_PROFILE_PHOTO_BYTES: Final[int] = DEFAULT_PROFILE_MEDIA_MAX_UPLOAD_BYTES

#: Attempts (initial + retries) the profile-photo write ladder makes before it
#: gives up on a flaky store (NFR-PERF-002, mirroring the intake upload ladder).
MAX_PROFILE_PHOTO_ATTEMPTS: Final[int] = 3


def _profile_photo_backoff_delay(attempt: int) -> float:
    """Exponential backoff (seconds) before retry ``attempt`` (loop count, 2+).

    Retry ordinal ``r = attempt - 1`` scales ``base * 2**(r-1)``, so the two
    retries after the first failure back off 0.5s then 1.0s.
    """
    return 0.5 * (2.0 ** (attempt - 2))


def validate_profile_photo(
    media_type: str | None,
    data: bytes,
    *,
    max_bytes: int = MAX_PROFILE_PHOTO_BYTES,
) -> None:
    """Enforce the profile-photo contract (US-20): JPEG/PNG/WebP only, size cap.

    The canonical type is derived from the upload's content type (the
    ``; charset=``-style suffix is stripped and the value lowercased); GIF and
    every other type are refused, and the byte size must fit ``max_bytes`` - the
    resolved ``PROFILE_MEDIA_MAX_UPLOAD_BYTES`` the caller injects, so the
    patient and doctor photo ceilings move together (coding-standards §9.2).
    A violation raises :class:`ProfilePhotoValidationError` with a human-safe
    message for the 422 envelope.
    """
    mime = (media_type or "").split(";", 1)[0].strip().lower()
    if mime not in ALLOWED_PHOTO_MEDIA_TYPES:
        raise ProfilePhotoValidationError(
            "profile photo must be JPEG, PNG, or WebP (GIF is not supported)"
        )
    if len(data) > max_bytes:
        raise ProfilePhotoValidationError(
            f"profile photo must be {max_bytes // (1024 * 1024)}MB or smaller"
        )


def _sniff_image_media_type(data: bytes) -> str:
    """Answer the stored photo's media type from its magic bytes.

    The stored bytes were accepted under their declared JPEG/PNG/WebP type, so
    a well-formed photo sniffs to one of the three admitted types; the
    octet-stream fallback catches a declared type whose bytes did not actually
    match its content (uploads validate the declared type only), so the streamed
    read still answers an honest ``Content-Type`` instead of a mismatched one.
    Kept here so the read needs no stored metadata next to the opaque object
    key (ADR-0020 D2: refs only in SQL).
    """
    if data.startswith(b"\xff\xd8\xff"):
        return MEDIA_TYPE_JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return MEDIA_TYPE_PNG
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return MEDIA_TYPE_WEBP
    return "application/octet-stream"


@dataclass(frozen=True)
class PhotoContent:
    """Decrypted profile-photo bytes plus their sniffed media type (US-20).

    The streamed read answer: the route renders ``data`` with ``media_type``
    as the ``Content-Type``. Never a public URL - the photo lives in the
    private ``profile-media`` store and is only ever streamed through the
    backend for the session owner.
    """

    data: bytes
    media_type: str


def _default_clock() -> datetime:
    return datetime.now(UTC)


class IdentityFacade:
    """Identity sub-facade: registration and identity lifecycle (ADR-0006)."""

    def __init__(
        self,
        engine: AsyncEngine,
        otp_sender: OtpSender,
        clock: Callable[[], datetime] = _default_clock,
        *,
        media_store: ProfileMediaStore | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        photo_max_bytes: int = MAX_PROFILE_PHOTO_BYTES,
    ) -> None:
        self._engine = engine
        self._otp_sender = otp_sender
        self._clock = clock
        # The profile-photo ceiling comes from the one settings source
        # (``PROFILE_MEDIA_MAX_UPLOAD_BYTES``, injected at the composition root),
        # so the patient's photo path and the doctor's share a single value
        # (coding-standards §9.2).
        self._photo_max_bytes = photo_max_bytes
        # US-20 (#533): the private profile-media store backs the patient's
        # profile photo. Injected at the composition root; None is the
        # unconfigured state the photo methods refuse loudly.
        self._media_store = media_store
        self._sleep = sleep

    async def register_patient(self, phone: str) -> RegisterPatientResult:
        """Begin-or-resume: create the identity on first use, else resolve it.

        The phone is normalized server-side to +91 E.164 (the country code is
        never trusted from the client). Concurrency converges via the unique
        ``phone_e164`` index: ``INSERT ... ON CONFLICT DO NOTHING`` then a
        re-read, never SELECT-then-INSERT (spec #51 section 2.3). A new identity is
        created ``[Unverified]`` and emits ``patient.registered``; a repeat
        phone resolves to the existing identity (no duplicate).

        The existing-phone login branch enforces the same anti-spam gate as a
        resend (spec #51 section 2.4, ADR-0004): while the phone is inside the >= 60 s
        resend cooldown measured from the last issuance, in the brute-force
        lockout, or ``Suspended``, the entry is refused - no fresh challenge is
        issued, no ``otp.sent`` is written, and no SMS is sent - so an attacker
        cannot defeat the cooldown by calling register repeatedly or poke a
        locked phone back into the OTP flow. The identity row is locked
        ``FOR UPDATE`` so the refusal reads stable guard state and concurrent
        writers serialize. First-time registration and out-of-cooldown login
        share the resend's latest-wins issuance via the shared re-issue
        primitive ``_reissue_otp_challenge`` (WI-4, #335), which defines the
        cooldown/lockout semantics once for both paths: the pending challenge is
        invalidated before a fresh hashed one is issued (the old code can no
        longer verify), ``otp.sent`` lands in the iam outbox in the same
        transaction as the change, and the EXT-001 adapter delivers it as a
        background task afterwards - the request never blocks on the provider
        (PHASE-2 REM T4, #86).
        """
        phone_e164 = normalize_phone(phone)
        now = self._clock()

        async with self._engine.begin() as connection:
            inserted = await connection.execute(
                postgresql_insert(iam_identities)
                .values(phone_e164=phone_e164)
                .on_conflict_do_nothing(index_elements=["phone_e164"])
            )
            is_new = inserted.rowcount == 1
            if is_new:
                identity_id = (
                    await connection.execute(
                        select(iam_identities.c.id).where(iam_identities.c.phone_e164 == phone_e164)
                    )
                ).scalar_one()
                await write_outbox(
                    connection,
                    _IAM_SCHEMA,
                    IAM_OUTBOX_TABLE,
                    events.patient_registered_envelope(identity_id, phone_e164),
                )
                challenge_id, otp = await _issue_challenge(
                    connection,
                    identity_id=identity_id,
                    phone_e164=phone_e164,
                    now=now,
                )
            else:
                locked = await _lock_identity_row(
                    connection, iam_identities.c.phone_e164 == phone_e164
                )
                if locked is None:
                    raise IamError("existing identity disappeared between the insert and the lock")
                identity_id = locked.identity_id

                reissue = await _reissue_otp_challenge(
                    connection,
                    identity_id=identity_id,
                    phone_e164=phone_e164,
                    identity_status=locked.status,
                    lockout_until=locked.lockout_until,
                    now=now,
                )
                if reissue.outcome != "sent":
                    return RegisterPatientResult(
                        outcome=reissue.outcome,
                        phone_e164=phone_e164,
                        identity_id=reissue.identity_id,
                        is_existing=True,
                        flow="login",
                        cooldown_remaining_seconds=reissue.cooldown_remaining_seconds,
                        lockout_remaining_seconds=reissue.lockout_remaining_seconds,
                    )
                challenge_id, otp = reissue.sent_challenge()

        await self._otp_sender(phone_e164, otp)

        return RegisterPatientResult(
            outcome="sent",
            phone_e164=phone_e164,
            identity_id=identity_id,
            challenge_id=challenge_id,
            is_existing=not is_new,
            flow="login" if not is_new else "register",
            expires_in_seconds=OTP_TTL_SECONDS,
            cooldown_remaining_seconds=RESEND_COOLDOWN_SECONDS,
            attempts_left=MAX_ATTEMPTS,
        )

    async def create_credential_account(
        self, phone: str, connection: AsyncConnection | None = None
    ) -> PartnerCredentialCreatedResult:
        """Create a login-capable identity for a newly registered partner (ADR-0010, #245).

        Called synchronously by the ``partner`` module inside the same
        transaction as partner registration, so a partner's phone-OTP login
        works the moment they register. Unlike ``register_patient`` this does
        NOT issue a challenge or grant a role: the identity is created
        ``[Unverified]`` with no ``partner`` role grant, so a later activation
        (T03, #246) is the gated step that grants the role and unlocks
        patient-facing scope.

        ``connection`` lets the caller (the ``partner`` facade) share its own
        open transaction so the identity insert commits atomically with the
        partner profile and the partner module's ``partner.registered``
        (ADR-0010: "in the same registration transaction boundary"). The
        ``partner.registered`` event is MOD-002's, so the iam seam emits no
        same-key event here - the registry's one-shape-per-name contract holds
        (internal-modules §4.2, producer MOD-002). When omitted the
        method opens its own transaction, preserving the standalone seam shape
        the iam tests exercise. Concurrency converges via the unique
        ``phone_e164`` index (``INSERT ... ON CONFLICT DO NOTHING`` then a
        re-read, never SELECT-then-INSERT).
        """
        phone_e164 = normalize_phone(phone)

        async def _run(connection: AsyncConnection) -> int:
            await connection.execute(
                postgresql_insert(iam_identities)
                .values(phone_e164=phone_e164)
                .on_conflict_do_nothing(index_elements=["phone_e164"])
            )
            identity_id = (
                await connection.execute(
                    select(iam_identities.c.id).where(iam_identities.c.phone_e164 == phone_e164)
                )
            ).scalar_one()
            return int(identity_id)

        if connection is not None:
            identity_id = await _run(connection)
        else:
            async with self._engine.begin() as connection:
                identity_id = await _run(connection)

        return PartnerCredentialCreatedResult(identity_id=identity_id, phone_e164=phone_e164)

    async def create_operator_account(
        self,
        phone: str,
        invited_by_identity_id: int,
        connection: AsyncConnection | None = None,
    ) -> OperatorInvitedResult:
        """Invite a new operator: create a credentialed, MFA-bound account (T07, #250).

        Operators are a trusted closed group that never self-registers - the
        only way to grow the queue-running group is an existing operator
        inviting a new phone. The invited identity is created ``[Unverified]``
        and immediately granted an ``Active`` ``operator`` role, so a session
        can be issued only after the invited phone completes MFA at first
        login (the second factor precedes session minting in ``issue_operator_session``).

        Unlike ``create_credential_account`` (a partner is login-capable with
        no role until activation), the operator role grant is handed over at
        invite time - MFA, not a separate activation step, is the gate that
        binds the account. ``invited_by_identity_id`` names the inviting
        operator for the ``operator.invited`` audit event, emitted in the same
        transaction as the identity insert. ``connection`` lets the caller
        share an open transaction; when omitted the method opens its own,
        preserving the standalone seam shape the iam tests exercise. Concurrency
        converges via the unique ``phone_e164`` index (``INSERT ... ON CONFLICT
        DO NOTHING`` then a re-read); a duplicate phone resolves to the existing
        identity with the role grant still ensured and no duplicate event.
        """
        phone_e164 = normalize_phone(phone)

        async def _run(connection: AsyncConnection) -> int:
            inserted = await connection.execute(
                postgresql_insert(iam_identities)
                .values(phone_e164=phone_e164)
                .on_conflict_do_nothing(index_elements=["phone_e164"])
            )
            identity_id = (
                await connection.execute(
                    select(iam_identities.c.id).where(iam_identities.c.phone_e164 == phone_e164)
                )
            ).scalar_one()
            await grant_operator_role(connection, identity_id)
            if inserted.rowcount == 1:
                await write_outbox(
                    connection,
                    _IAM_SCHEMA,
                    IAM_OUTBOX_TABLE,
                    events.operator_invited_envelope(
                        identity_id=identity_id,
                        phone_e164=phone_e164,
                        invited_by_identity_id=invited_by_identity_id,
                    ),
                )
            return int(identity_id)

        if connection is not None:
            identity_id = await _run(connection)
        else:
            async with self._engine.begin() as connection:
                identity_id = await _run(connection)

        return OperatorInvitedResult(identity_id=identity_id, phone_e164=phone_e164)

    async def save_patient_profile(
        self,
        identity_id: int,
        profile: PatientProfile,
        connection: AsyncConnection | None = None,
    ) -> PatientProfile:
        """Idempotently upsert the patient's profile-completion data (#482).

        One row per identity: ``INSERT ... ON CONFLICT (identity_id) DO UPDATE``
        replaces the whole profile on every save (never SELECT-then-INSERT), so
        a returning patient is asked only once and a repeat PUT with the same
        payload converges to the same row. ``connection`` lets a caller share an
        open transaction - the dual-seam discipline: the write commits
        atomically with whatever else that transaction carries; when omitted
        the method opens its own, preserving the standalone seam shape the
        route and tests exercise. Touches only the ``iam`` schema (ADR-0003).
        """
        now = self._clock()
        columns: dict[str, Any] = {
            "name": profile.name,
            "age": profile.age,
            "gender": profile.gender,
            "preferred_language": profile.preferred_language,
            "area": profile.area,
            "emergency_contact": profile.emergency_contact,
            "photo_ref": profile.photo_ref,
        }

        async def _run(connection: AsyncConnection) -> None:
            await connection.execute(
                postgresql_insert(iam_patient_profiles)
                .values(identity_id=identity_id, **columns)
                .on_conflict_do_update(
                    index_elements=["identity_id"],
                    set_={**columns, "updated_at": now},
                )
            )

        if connection is not None:
            await _run(connection)
        else:
            async with self._engine.begin() as connection:
                await _run(connection)

        return profile

    async def get_patient_profile(
        self,
        identity_id: int,
        connection: AsyncConnection | None = None,
    ) -> PatientProfile | None:
        """Read the patient's saved profile, or ``None`` when it is not set (#482).

        ``None`` is the typed "not set" the GET route wraps; a returned profile
        is the last committed save. Scoped to ``identity_id`` - callers (the
        route) pass the authenticated principal's subject id, so one identity
        never reads another's row. ``connection`` mirrors ``save_patient_profile``:
        an in-transaction caller reads the same snapshot it wrote instead of
        opening a competing transaction. Read-only.
        """

        async def _read(connection: AsyncConnection) -> PatientProfile | None:
            result = await connection.execute(
                select(iam_patient_profiles).where(
                    iam_patient_profiles.c.identity_id == identity_id
                )
            )
            row = result.mappings().first()
            if row is None:
                return None
            return PatientProfile(
                name=row["name"],
                age=row["age"],
                gender=row["gender"],
                preferred_language=row["preferred_language"],
                area=row["area"],
                emergency_contact=row["emergency_contact"],
                photo_ref=row["photo_ref"],
            )

        if connection is not None:
            return await _read(connection)
        async with self._engine.begin() as connection:
            return await _read(connection)

    async def save_patient_photo(
        self,
        *,
        identity_id: int,
        data: bytes,
        media_type: str | None,
    ) -> PatientProfile:
        """Upload or replace the caller's profile photo (US-20, ticket #533).

        Enforces the photo contract (JPEG/PNG/WebP only, within the configured
        ceiling, GIF refused), writes the bytes to the private ``profile-media``
        store under the ``patient/`` prefix, and persists only the returned
        opaque object key on the caller's ``iam_patient_profiles`` row
        (ADR-0020 D2: refs only in SQL, never the bytes and never a public URL).
        An existing photo is replaced: the old object is deleted so it is not
        orphaned. The photo is bound to ``identity_id`` - the route passes the
        authenticated subject id, so one identity can never overwrite another's
        photo.

        The store write rides an upload-retry ladder (NFR-PERF-002, mirroring
        the intake upload): transient :class:`OSError` is retried up to
        ``MAX_PROFILE_PHOTO_ATTEMPTS`` before giving up. The validation step
        runs before any store or database work, so a bad upload never files
        anything.

        Returns the updated profile (its ``photo_ref`` now names the new key).

        Raises :class:`ProfilePhotoValidationError` on a content-type/size
        violation, :class:`PatientProfileNotSetError` when there is no profile
        row to carry the key yet, and :class:`ProfilePhotoTransferError` when
        every store-write attempt fails.
        """
        if self._media_store is None:
            raise IamError("profile media store is not configured")
        validate_profile_photo(media_type, data, max_bytes=self._photo_max_bytes)
        profile = await self.get_patient_profile(identity_id)
        if profile is None:
            raise PatientProfileNotSetError(
                "set the patient profile before uploading a profile photo"
            )
        new_key = await self._store_photo(data, identity_id)
        try:
            await self._set_patient_photo_ref(identity_id, new_key)
        except Exception:
            # The reference never landed: drop the freshly filed object so the
            # store is not orphaned (the profile still points at the old photo).
            with contextlib.suppress(Exception):
                await self._media_store.delete(object_key=new_key)
            raise
        if profile.photo_ref is not None and profile.photo_ref != new_key:
            # Replace: the superseded object is deleted best-effort - the
            # profile already references the new key, so a leftover ciphertext
            # here is a logged-invisible orphan, never a broken reference.
            with contextlib.suppress(Exception):
                await self._media_store.delete(object_key=profile.photo_ref)
        profile.photo_ref = new_key
        return profile

    async def get_patient_photo(self, *, identity_id: int) -> PhotoContent | None:
        """Stream the caller's stored profile photo, or ``None`` when unset.

        Reads the profile row's ``photo_ref`` and decrypts the object through
        the store - never a public URL. ``None`` is the typed "no photo" answer
        (no profile row, no key, or a dangling key whose object is gone), which
        the GET route turns into a 404 for the session owner. Scoped to
        ``identity_id``: only the owning patient reaches the bytes here; a
        doctor's read of a patient photo is later consent-gated work (#540).
        """
        if self._media_store is None:
            raise IamError("profile media store is not configured")
        profile = await self.get_patient_profile(identity_id)
        if profile is None or profile.photo_ref is None:
            return None
        try:
            data = await self._media_store.read(object_key=profile.photo_ref)
        except FileNotFoundError:
            # A dangling key (object deleted out-of-band) means "no photo"
            # rather than a 500 - the owner simply has nothing to preview.
            return None
        return PhotoContent(data=data, media_type=_sniff_image_media_type(data))

    async def delete_patient_photo(self, *, identity_id: int) -> PatientProfile:
        """Remove the caller's profile photo: clear the key and delete the object.

        Clears ``photo_ref`` on the ``iam_patient_profiles`` row first - the
        contract is "removal clears the stored key" (US-20) - then deletes the
        ciphertext best-effort so a removed photo is not orphaned. Idempotent:
        a profile with no photo returns unchanged. Scoped to ``identity_id``.

        Raises :class:`PatientProfileNotSetError` when the caller has no
        profile row (nothing to carry the cleared key).
        """
        if self._media_store is None:
            raise IamError("profile media store is not configured")
        profile = await self.get_patient_profile(identity_id)
        if profile is None:
            raise PatientProfileNotSetError(
                "set the patient profile before removing a profile photo"
            )
        if profile.photo_ref is None:
            return profile
        old_key = profile.photo_ref
        await self._set_patient_photo_ref(identity_id, None)
        with contextlib.suppress(Exception):
            await self._media_store.delete(object_key=old_key)
        profile.photo_ref = None
        return profile

    async def _store_photo(self, data: bytes, identity_id: int) -> str:
        """Run one profile-photo write through the upload-resilience ladder.

        On a transient failure it backs off and retries up to
        ``MAX_PROFILE_PHOTO_ATTEMPTS`` (3) attempts, then raises
        :class:`ProfilePhotoTransferError` - a failed upload never silently
        leaves the profile photo absent (NFR-PERF-002).
        """
        media_store = self._media_store
        if media_store is None:
            raise IamError("profile media store is not configured")
        object_key: str | None = None
        last_error: OSError | None = None
        for attempt in range(1, MAX_PROFILE_PHOTO_ATTEMPTS + 1):
            if attempt > 1:
                await self._sleep(_profile_photo_backoff_delay(attempt))
            try:
                object_key = await media_store.save(
                    data=data,
                    subject_id=identity_id,
                    prefix=PATIENT_PREFIX,
                )
                break
            except OSError as exc:
                last_error = exc
        if object_key is None:
            raise ProfilePhotoTransferError(
                f"profile photo upload failed after {MAX_PROFILE_PHOTO_ATTEMPTS} "
                f"attempts for patient {identity_id}"
            ) from last_error
        return object_key

    async def _set_patient_photo_ref(self, identity_id: int, photo_ref: str | None) -> None:
        """Persist ``photo_ref`` on the caller's profile row (or refuse).

        A targeted single-column update (never a whole-row upsert, so the
        photo surface works without re-writing the profile's other fields).
        Raises :class:`PatientProfileNotSetError` when no row matches - the
        profile must exist before a photo key can live on it.
        """
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(iam_patient_profiles)
                .where(iam_patient_profiles.c.identity_id == identity_id)
                .values(photo_ref=photo_ref, updated_at=self._clock())
            )
        if result.rowcount == 0:
            raise PatientProfileNotSetError(
                "set the patient profile before changing the profile photo"
            )
