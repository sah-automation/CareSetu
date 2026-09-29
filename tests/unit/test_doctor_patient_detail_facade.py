"""PHASE-8.2 T02: DoctorConsoleFacade detail + photo reads (ticket #540).

Drives the consent-gated per-patient detail and photo reads through stubbed
consent/care/iam/health facades - no engine, the seam composes reads only:

- The contact section opens under the ``consultations`` scope (or the
  subsuming ``full_record``), degrade-safe from the iam profile; consultation
  history only under the ``consultations`` scope; health background only under
  ``health_background``. A denied section answers ``None`` (the client's
  locked / "not shared" state), never an error, and a narrow grant (e.g.
  ``lab_results``) locks the contact block instead of leaking the demographic
  and emergency-contact fields.
- No live grant leaks nothing sensitive, and the case workspace is the
  doctor's own most recently updated case - present whenever one exists.
- The contact/photo block is access-logged (the detail marker) and egress-
  disclosed against the most permissive live grant (``full_record`` first,
  else the earliest consent id).
- The photo read fails closed without a live grant (the module's own
  ``DoctorConsoleAccessDeniedError``), writes its ledger rows before the bytes
  are materialized, returns ``None`` when no photo is stored, and is otherwise
  gated, logged, and disclosed like the contact block. A consent denial is
  AUDITED before the refusal is raised (KPI-006): a ``denied`` access-history
  row lands even when the doctor has no relationship with the patient at all.
- Every read re-checks the caller is still an active doctor in the facade
  (api-standards §6), refusing a non-doctor or non-active partner with the
  module's own refusal before any consent lookup, profile read, or ledger write.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from modules.care.facade import CaseDetailView
from modules.consent.facade import CounterpartyGrantView
from modules.doctor.domain.exceptions import DoctorConsoleAccessDeniedError
from modules.doctor.facade import DoctorConsoleFacade
from modules.health.facade import (
    HealthBackground,
    HealthBackgroundView,
    RecordAccessDeniedError,
    RecordEntryView,
    RecordTimeline,
)
from modules.iam.facade import PhotoContent
from modules.partner.facade import DoctorProfileNotAllowedError, PartnerNotFoundError

_DOCTOR_ID = 42
_PATIENT_ID = 10
NOW = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Stub facades
# ---------------------------------------------------------------------------


class StubConsentFacade:
    """Canned counterparty grants, recording the reverse lookup and egress rows."""

    def __init__(self, grants: list[CounterpartyGrantView] | None = None) -> None:
        self.grants = grants or []
        self.list_calls: list[tuple[str, str]] = []
        self.egress: list[dict] = []

    async def list_counterparty_grants(
        self, *, counterparty_type: str, counterparty_id: str
    ) -> list[CounterpartyGrantView]:
        self.list_calls.append((counterparty_type, counterparty_id))
        return self.grants

    async def record_egress_disclosure(self, **kwargs: object) -> None:
        self.egress.append(dict(kwargs))


class StubCareFacade:
    """Canned all-cases feed, recording the list call."""

    def __init__(self, cases: list[CaseDetailView] | None = None) -> None:
        self.cases = cases or []

    async def list_doctor_all_cases(self, *, doctor_id: int) -> list[CaseDetailView]:
        return self.cases


class StubIamFacade:
    """Per-identity profile and photo stand-ins; each can be pointed to fail."""

    def __init__(
        self,
        profiles: dict[int, object] | None = None,
        photos: dict[int, PhotoContent] | None = None,
        *,
        profile_fail: bool = False,
    ) -> None:
        self.profiles = profiles or {}
        self.photos = photos or {}
        self.profile_fail = profile_fail
        self.reads: list[int] = []

    async def get_patient_profile(self, identity_id: int) -> object:
        self.reads.append(identity_id)
        if self.profile_fail:
            raise RuntimeError("iam seam down")
        return self.profiles.get(identity_id)

    async def get_patient_photo(self, *, identity_id: int) -> PhotoContent | None:
        return self.photos.get(identity_id)


class StubHealthFacade:
    """Records doctor-view logs and answers the consented section reads.

    ``denied_scopes`` controls which consented reads raise
    ``RecordAccessDeniedError`` (the "already ledgered inside the seam"
    denial); anything else answers the canned view. ``denied_logged`` records
    the consent-denial ledger calls the photo read makes before refusing.
    """

    def __init__(
        self,
        timeline: RecordTimeline | None = None,
        background: HealthBackgroundView | None = None,
        *,
        denied_scopes: set[str] | None = None,
    ) -> None:
        self.timeline = timeline
        self.background = background
        self.denied_scopes = denied_scopes or set()
        self.logged: list[dict] = []
        self.denied_logged: list[dict] = []
        self.history_calls: list[dict] = []
        self.background_calls: list[dict] = []

    async def log_doctor_patient_view(self, *, patient_id: int, doctor_id: int, scope: str) -> None:
        self.logged.append({"patient_id": patient_id, "doctor_id": doctor_id, "scope": scope})

    async def log_doctor_patient_view_denied(
        self, *, patient_id: int, doctor_id: int, denial_reason: str, scope: str
    ) -> None:
        self.denied_logged.append(
            {
                "patient_id": patient_id,
                "doctor_id": doctor_id,
                "denial_reason": denial_reason,
                "scope": scope,
            }
        )

    async def read_consented_history(
        self,
        *,
        patient_id: int,
        scope: str,
        counterparty_type: str,
        counterparty_id: int,
    ) -> RecordTimeline:
        self.history_calls.append(
            {
                "patient_id": patient_id,
                "scope": scope,
                "counterparty_type": counterparty_type,
                "counterparty_id": counterparty_id,
            }
        )
        if scope in self.denied_scopes:
            raise RecordAccessDeniedError("consent check failed")
        return self.timeline

    async def read_consented_health_background(
        self,
        *,
        patient_id: int,
        counterparty_type: str,
        counterparty_id: int,
    ) -> HealthBackgroundView:
        self.background_calls.append(
            {
                "patient_id": patient_id,
                "counterparty_type": counterparty_type,
                "counterparty_id": counterparty_id,
            }
        )
        if "health_background" in self.denied_scopes:
            raise RecordAccessDeniedError("consent check failed")
        return self.background


class StubPartnerFacade:
    """The MOD-002 re-check seam; pointed at a non-doctor/non-active partner to refuse."""

    def __init__(self, refusal: str | None = None) -> None:
        self.refusal = refusal
        self.checked: list[int] = []

    async def require_active_doctor(self, doctor_id: int) -> None:
        self.checked.append(doctor_id)
        if self.refusal == "not_a_doctor":
            raise DoctorProfileNotAllowedError(doctor_id, "lab", "Active")
        if self.refusal == "not_active":
            raise DoctorProfileNotAllowedError(doctor_id, "doctor", "Suspended")
        if self.refusal == "gone":
            raise PartnerNotFoundError(doctor_id)


def _facade(
    consent: StubConsentFacade | None = None,
    care: StubCareFacade | None = None,
    iam: StubIamFacade | None = None,
    health: StubHealthFacade | None = None,
    partner: StubPartnerFacade | None = None,
) -> DoctorConsoleFacade:
    return DoctorConsoleFacade(
        consent_facade=consent or StubConsentFacade(),
        care_facade=care or StubCareFacade(),
        iam_facade=iam or StubIamFacade(),
        health_facade=health or StubHealthFacade(),
        partner_facade=partner or StubPartnerFacade(),
    )


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _grant(
    *,
    patient_id: int = _PATIENT_ID,
    scope: str = "full_record",
    consent_id: int = 1,
    version: int = 1,
) -> CounterpartyGrantView:
    return CounterpartyGrantView(
        consent_id=consent_id,
        patient_id=patient_id,
        record_scope=scope,
        version=version,
    )


def _case(
    *,
    case_id: int,
    stage: str = "pre_summary",
    updated_at: datetime = NOW,
    patient_id: int = _PATIENT_ID,
) -> CaseDetailView:
    return CaseDetailView(
        case_id=case_id,
        patient_id=patient_id,
        doctor_id=_DOCTOR_ID,
        pre_summary_id=case_id,
        stage=stage,
        closed_at=updated_at if stage == "closed" else None,
        close_reason=None,
        created_at=updated_at,
        updated_at=updated_at,
    )


def _profile(
    name: str = "Ravi Kumar",
    age: int = 32,
    gender: str = "male",
    area: str = "Bengaluru",
    emergency_contact: str = "9876543210",
    photo_ref: str = "profiles/abc",
) -> object:
    return type(
        "Profile",
        (),
        {
            "name": name,
            "age": age,
            "gender": gender,
            "area": area,
            "emergency_contact": emergency_contact,
            "photo_ref": photo_ref,
        },
    )()


def _timeline() -> RecordTimeline:
    return RecordTimeline(
        record_id=1,
        patient_id=_PATIENT_ID,
        created_at=NOW,
        entries=[
            RecordEntryView(
                entry_id=1,
                entry_type="consultation",
                payload={},
                occurred_at=NOW,
                created_at=NOW,
            )
        ],
    )


def _background() -> HealthBackgroundView:
    return HealthBackgroundView(
        set=True,
        acknowledged=True,
        background=HealthBackground(blood_group="O+", conditions=["hypertension"]),
    )


# ---------------------------------------------------------------------------
# Section gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_full_record_grant_opens_every_section() -> None:
    consent = StubConsentFacade([_grant(scope="full_record")])
    care = StubCareFacade([_case(case_id=7)])
    iam = StubIamFacade({_PATIENT_ID: _profile()})
    health = StubHealthFacade(timeline=_timeline(), background=_background())
    facade = _facade(consent=consent, care=care, iam=iam, health=health)

    result = await facade.get_doctor_patient_detail(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert result.patient_id == _PATIENT_ID
    assert result.bucket == "current"
    assert result.granted_scopes == ["full_record"]
    assert result.latest_case_stage == "pre_summary"
    assert result.case_workspace.case_id == 7
    assert result.case_workspace.stage == "pre_summary"
    assert result.contact.name == "Ravi Kumar"
    assert result.contact.age == 32
    assert result.contact.gender == "male"
    assert result.contact.area == "Bengaluru"
    assert result.contact.emergency_contact == "9876543210"
    assert result.contact.has_photo is True
    assert "profiles/abc" not in result.model_dump_json()
    assert result.consultation_history.entries[0].entry_id == 1
    assert result.health_background.background.blood_group == "O+"


@pytest.mark.asyncio
async def test_detail_contact_opens_under_consultations_scope() -> None:
    consent = StubConsentFacade([_grant(scope="consultations", consent_id=2)])
    iam = StubIamFacade({_PATIENT_ID: _profile()})
    health = StubHealthFacade(
        timeline=_timeline(), background=_background(), denied_scopes={"health_background"}
    )
    facade = _facade(consent=consent, iam=iam, health=health)

    result = await facade.get_doctor_patient_detail(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert result.contact.name == "Ravi Kumar"
    assert result.consultation_history is not None
    assert result.health_background is None


@pytest.mark.asyncio
async def test_detail_contact_locked_under_a_narrow_scope_grant() -> None:
    # security-phii-standards S2: a ``lab_results`` (or ``health_background``)
    # grant is not a licence to read gender / area / emergency contact, so the
    # whole contact block answers locked and nothing is disclosed for it.
    consent = StubConsentFacade([_grant(scope="lab_results", consent_id=4)])
    iam = StubIamFacade({_PATIENT_ID: _profile()})
    health = StubHealthFacade(
        timeline=_timeline(), background=_background(), denied_scopes={"consultations"}
    )
    facade = _facade(consent=consent, iam=iam, health=health)

    result = await facade.get_doctor_patient_detail(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert result.contact is None
    assert result.bucket == "current"
    assert result.granted_scopes == ["lab_results"]
    assert health.logged == []
    assert consent.egress == []
    assert iam.reads == []


@pytest.mark.asyncio
async def test_detail_health_background_locked_without_health_background_scope() -> None:
    consent = StubConsentFacade([_grant(scope="consultations")])
    health = StubHealthFacade(
        timeline=_timeline(), background=_background(), denied_scopes={"health_background"}
    )
    facade = _facade(consent=consent, health=health)

    result = await facade.get_doctor_patient_detail(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert result.consultation_history is not None
    assert result.health_background is None


@pytest.mark.asyncio
async def test_detail_consultation_locked_without_consultations_scope() -> None:
    consent = StubConsentFacade([_grant(scope="health_background")])
    health = StubHealthFacade(
        timeline=_timeline(), background=_background(), denied_scopes={"consultations"}
    )
    facade = _facade(consent=consent, health=health)

    result = await facade.get_doctor_patient_detail(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert result.consultation_history is None
    assert result.health_background is not None
    # ``health_background`` does not authorize identity contact either.
    assert result.contact is None


@pytest.mark.asyncio
async def test_detail_no_live_grant_locks_every_sensitive_section() -> None:
    care = StubCareFacade([_case(case_id=9, stage="closed")])
    # No live grant, so the consent gate behind both section reads denies:
    # each read still happened (and wrote its own denied ledger row inside the
    # health seam), and the facade answers locked sections, never an error.
    health = StubHealthFacade(
        timeline=_timeline(),
        background=_background(),
        denied_scopes={"consultations", "health_background"},
    )
    facade = _facade(care=care, health=health)

    result = await facade.get_doctor_patient_detail(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert result.bucket == "past"
    assert result.granted_scopes == []
    assert result.latest_case_stage == "closed"
    assert result.contact is None
    assert result.consultation_history is None
    assert result.health_background is None
    # The case workspace is the doctor's OWN case - a deep link back into
    # their workspace, so it stays present when one exists even for past
    # patients (ADR-0019); it is not patient PHI.
    assert result.case_workspace.case_id == 9
    assert health.logged == []
    assert [call["scope"] for call in health.history_calls] == ["consultations"]
    assert len(health.background_calls) == 1


@pytest.mark.asyncio
async def test_detail_unknown_patient_answers_locked_sections() -> None:
    consent = StubConsentFacade([_grant(scope="full_record", patient_id=99)])
    iam = StubIamFacade({99: _profile()})
    facade = _facade(consent=consent, iam=iam)

    result = await facade.get_doctor_patient_detail(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert result.patient_id == _PATIENT_ID
    assert result.contact is None
    assert result.consultation_history is None
    assert result.health_background is None
    assert result.case_workspace is None
    assert result.granted_scopes == []


@pytest.mark.asyncio
async def test_detail_uses_most_recently_updated_case_for_workspace() -> None:
    consent = StubConsentFacade([_grant()])
    care = StubCareFacade(
        [
            _case(case_id=1, stage="pre_summary", updated_at=datetime(2026, 9, 1, tzinfo=UTC)),
            _case(
                case_id=2, stage="prescription_pending", updated_at=datetime(2026, 9, 5, tzinfo=UTC)
            ),
            _case(case_id=3, stage="closed", updated_at=datetime(2026, 9, 3, tzinfo=UTC)),
        ]
    )
    facade = _facade(consent=consent, care=care)

    result = await facade.get_doctor_patient_detail(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert result.case_workspace.case_id == 2
    assert result.case_workspace.stage == "prescription_pending"
    assert result.latest_case_stage == "prescription_pending"
    assert result.bucket == "current"


@pytest.mark.asyncio
async def test_detail_profile_failure_degrades_contact_block_but_keeps_other_sections() -> None:
    consent = StubConsentFacade([_grant()])
    iam = StubIamFacade(profile_fail=True)
    health = StubHealthFacade(timeline=_timeline(), background=_background())
    facade = _facade(consent=consent, iam=iam, health=health)

    result = await facade.get_doctor_patient_detail(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert result.contact is not None
    assert result.contact.name is None
    assert result.contact.age is None
    assert result.contact.has_photo is False
    assert result.consultation_history is not None
    assert result.health_background is not None


# ---------------------------------------------------------------------------
# Access logging and egress disclosure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_contact_block_access_logged_with_detail_marker() -> None:
    consent = StubConsentFacade([_grant(scope="consultations")])
    health = StubHealthFacade(timeline=_timeline())
    facade = _facade(consent=consent, health=health)

    await facade.get_doctor_patient_detail(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert health.logged == [
        {"patient_id": _PATIENT_ID, "doctor_id": _DOCTOR_ID, "scope": "doctor_patient_detail"}
    ]


@pytest.mark.asyncio
async def test_detail_no_contact_log_without_live_grant() -> None:
    health = StubHealthFacade()
    facade = _facade(health=health)

    await facade.get_doctor_patient_detail(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert health.logged == []


@pytest.mark.asyncio
async def test_detail_contact_egress_prefers_full_record_authorizing_grant() -> None:
    consent = StubConsentFacade(
        [_grant(scope="consultations", consent_id=1), _grant(scope="full_record", consent_id=2)]
    )
    facade = _facade(consent=consent)

    await facade.get_doctor_patient_detail(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert consent.egress == [
        {
            "patient_id": _PATIENT_ID,
            "consent_id": 2,
            "version": 1,
            "counterparty_type": "doctor",
            "counterparty_id": "42",
            "record_scope": "full_record",
            "disclosed_entry_ids": [],
        }
    ]


@pytest.mark.asyncio
async def test_detail_contact_egress_uses_earliest_grant_without_full_record() -> None:
    consent = StubConsentFacade(
        [
            _grant(scope="lab_results", consent_id=3, version=2),
            _grant(scope="consultations", consent_id=1, version=1),
        ]
    )
    facade = _facade(consent=consent)

    await facade.get_doctor_patient_detail(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert consent.egress[0]["consent_id"] == 1
    assert consent.egress[0]["record_scope"] == "consultations"
    assert consent.egress[0]["version"] == 1


@pytest.mark.asyncio
async def test_detail_section_reads_scoped_as_doctor_console_surface() -> None:
    consent = StubConsentFacade([_grant()])
    health = StubHealthFacade(timeline=_timeline(), background=_background())
    facade = _facade(consent=consent, health=health)

    await facade.get_doctor_patient_detail(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert health.history_calls == [
        {
            "patient_id": _PATIENT_ID,
            "scope": "consultations",
            "counterparty_type": "doctor",
            "counterparty_id": _DOCTOR_ID,
        }
    ]
    assert health.background_calls == [
        {
            "patient_id": _PATIENT_ID,
            "counterparty_type": "doctor",
            "counterparty_id": _DOCTOR_ID,
        }
    ]
    assert consent.list_calls == [("doctor", "42")]


# ---------------------------------------------------------------------------
# Photo read
# ---------------------------------------------------------------------------


def _photo() -> PhotoContent:
    return PhotoContent(data=b"\xff\xd8jpeg", media_type="image/jpeg")


def _photo_profile() -> object:
    return _profile(photo_ref="patient/7/photo-1.enc")


@pytest.mark.asyncio
async def test_photo_live_grant_streams_photo_and_discloses_contact_block() -> None:
    consent = StubConsentFacade([_grant(scope="full_record", consent_id=5, version=3)])
    iam = StubIamFacade(profiles={_PATIENT_ID: _photo_profile()}, photos={_PATIENT_ID: _photo()})
    health = StubHealthFacade()
    facade = _facade(consent=consent, iam=iam, health=health)

    photo = await facade.get_doctor_patient_photo(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert photo == _photo()
    assert health.logged == [
        {"patient_id": _PATIENT_ID, "doctor_id": _DOCTOR_ID, "scope": "doctor_patient_detail"}
    ]
    assert consent.egress[0]["consent_id"] == 5
    assert consent.egress[0]["record_scope"] == "full_record"


@pytest.mark.asyncio
async def test_photo_ledgers_the_read_before_the_bytes_are_read() -> None:
    """The audit rows land before the photo fetch, never after it."""
    order: list[str] = []

    class OrderedIamFacade(StubIamFacade):
        async def get_patient_profile(self, identity_id: int) -> object:
            return await super().get_patient_profile(identity_id)

        async def get_patient_photo(self, *, identity_id: int) -> PhotoContent | None:
            order.append("photo_bytes_read")
            return await super().get_patient_photo(identity_id=identity_id)

    class OrderedHealthFacade(StubHealthFacade):
        async def log_doctor_patient_view(self, **kwargs: object) -> None:
            order.append("access_logged")
            await super().log_doctor_patient_view(**kwargs)  # type: ignore[arg-type]

    class OrderedConsentFacade(StubConsentFacade):
        async def record_egress_disclosure(self, **kwargs: object) -> None:
            order.append("egress_disclosed")
            await super().record_egress_disclosure(**kwargs)

    iam = OrderedIamFacade(profiles={_PATIENT_ID: _photo_profile()})
    iam.photos = {_PATIENT_ID: _photo()}
    facade = _facade(
        consent=OrderedConsentFacade([_grant(scope="consultations", consent_id=2)]),
        iam=iam,
        health=OrderedHealthFacade(),
    )

    photo = await facade.get_doctor_patient_photo(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert photo == _photo()
    assert order == ["access_logged", "egress_disclosed", "photo_bytes_read"]


@pytest.mark.asyncio
async def test_photo_without_live_grant_fails_closed_and_is_auditable() -> None:
    # KPI-006 / security-phii-standards §3: the doctor holds a live grant from
    # some OTHER patient, so this one answers "no relationship at all" - the
    # read is still refused AND still ledgered as a denied attempt.
    consent = StubConsentFacade([_grant(scope="full_record", patient_id=99)])
    iam = StubIamFacade(profiles={_PATIENT_ID: _photo_profile()}, photos={_PATIENT_ID: _photo()})
    health = StubHealthFacade()
    facade = _facade(consent=consent, iam=iam, health=health)

    with pytest.raises(DoctorConsoleAccessDeniedError):
        await facade.get_doctor_patient_photo(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    # The denied attempt is auditable BEFORE the refusal leaves the facade: the
    # health seam committed the row, so the patient's trust view can answer
    # who asked and why it was refused.
    assert health.denied_logged == [
        {
            "patient_id": _PATIENT_ID,
            "doctor_id": _DOCTOR_ID,
            "denial_reason": "no live consent grant for this patient",
            "scope": "doctor_patient_detail",
        }
    ]
    # No PHI left the door: nothing allowed-logged, disclosed, or read.
    assert health.logged == []
    assert consent.egress == []
    # Fail-closed before any byte or even a profile read.
    assert iam.reads == []


@pytest.mark.asyncio
async def test_photo_with_no_relationship_at_all_is_still_auditable() -> None:
    # The doctor holds no grant of any scope from anyone: the empty answer is
    # still a consent denial, so the same ledger row is written.
    iam = StubIamFacade(profiles={_PATIENT_ID: _photo_profile()}, photos={_PATIENT_ID: _photo()})
    health = StubHealthFacade()
    facade = _facade(iam=iam, health=health)

    with pytest.raises(DoctorConsoleAccessDeniedError):
        await facade.get_doctor_patient_photo(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert [row["patient_id"] for row in health.denied_logged] == [_PATIENT_ID]
    assert health.denied_logged[0]["scope"] == "doctor_patient_detail"
    assert iam.reads == []


@pytest.mark.asyncio
async def test_photo_ledger_the_denial_before_the_refusal_is_raised() -> None:
    """The denied row is committed first - a raise inside the tx would roll it back."""
    order: list[str] = []

    class OrderedHealthFacade(StubHealthFacade):
        async def log_doctor_patient_view_denied(self, **kwargs: object) -> None:
            order.append("denial_ledgered")
            await super().log_doctor_patient_view_denied(**kwargs)  # type: ignore[arg-type]

    health = OrderedHealthFacade()
    facade = _facade(health=health)

    with pytest.raises(DoctorConsoleAccessDeniedError):
        await facade.get_doctor_patient_photo(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert order == ["denial_ledgered"]
    assert len(health.denied_logged) == 1


@pytest.mark.asyncio
async def test_photo_allowed_read_never_ledgered_as_denied() -> None:
    # The allowed path keeps its single allowed row; the denial seam is not a
    # second row for a read that succeeded.
    consent = StubConsentFacade([_grant()])
    iam = StubIamFacade(profiles={_PATIENT_ID: _photo_profile()}, photos={_PATIENT_ID: _photo()})
    health = StubHealthFacade()
    facade = _facade(consent=consent, iam=iam, health=health)

    await facade.get_doctor_patient_photo(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert health.denied_logged == []


# ---------------------------------------------------------------------------
# Facade-side authorization re-check (api-standards §6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_and_photo_recheck_the_active_doctor_role_in_the_facade() -> None:
    partner = StubPartnerFacade()
    facade = _facade(consent=StubConsentFacade([_grant()]), partner=partner)

    await facade.get_doctor_patient_detail(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)
    await facade.get_doctor_patient_photo(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert partner.checked == [_DOCTOR_ID, _DOCTOR_ID]


@pytest.mark.parametrize("refusal", ["not_a_doctor", "not_active", "gone"])
@pytest.mark.asyncio
async def test_detail_refuses_a_non_doctor_or_non_active_partner(refusal: str) -> None:
    # A live full_record grant is not enough: the role re-check runs first, so a
    # suspended doctor or a lab partner is refused at the facade even holding
    # the patient's consent.
    consent = StubConsentFacade([_grant()])
    iam = StubIamFacade({_PATIENT_ID: _profile()})
    health = StubHealthFacade()
    facade = _facade(
        consent=consent,
        iam=iam,
        health=health,
        partner=StubPartnerFacade(refusal=refusal),
    )

    with pytest.raises(DoctorConsoleAccessDeniedError):
        await facade.get_doctor_patient_detail(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert consent.list_calls == []
    assert iam.reads == []
    assert health.logged == []
    assert consent.egress == []


@pytest.mark.parametrize("refusal", ["not_a_doctor", "not_active", "gone"])
@pytest.mark.asyncio
async def test_photo_refuses_a_non_doctor_or_non_active_partner(refusal: str) -> None:
    # The role refusal precedes even the consent lookup, so it is not recorded
    # as a consent denial: the doctor never got far enough to ask for consent.
    consent = StubConsentFacade([_grant()])
    health = StubHealthFacade()
    facade = _facade(consent=consent, health=health, partner=StubPartnerFacade(refusal=refusal))

    with pytest.raises(DoctorConsoleAccessDeniedError):
        await facade.get_doctor_patient_photo(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert consent.list_calls == []
    assert health.denied_logged == []


@pytest.mark.asyncio
async def test_photo_granted_but_no_photo_answers_none_without_logging() -> None:
    consent = StubConsentFacade([_grant()])
    # The patient has a profile, but no photo is stored: the presence probe
    # finds none, so the read answers "no photo on file" (the route's 404)
    # without touching either ledger.
    iam = StubIamFacade(profiles={_PATIENT_ID: _profile(photo_ref=None)})
    health = StubHealthFacade()
    facade = _facade(consent=consent, iam=iam, health=health)

    photo = await facade.get_doctor_patient_photo(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert photo is None
    assert health.logged == []
    assert consent.egress == []


@pytest.mark.asyncio
async def test_photo_profile_failure_degrades_to_no_photo() -> None:
    # A failed profile read is a degraded presence probe, never an unguarded
    # fetch: the read answers None and no byte is materialized.
    consent = StubConsentFacade([_grant()])
    iam = StubIamFacade(profile_fail=True, photos={_PATIENT_ID: _photo()})
    health = StubHealthFacade()
    facade = _facade(consent=consent, iam=iam, health=health)

    photo = await facade.get_doctor_patient_photo(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert photo is None
    assert health.logged == []
