"""PHASE-8.2 T02: DoctorConsoleFacade detail + photo reads (ticket #540).

Drives the consent-gated per-patient detail and photo reads through stubbed
consent/care/iam/health facades - no engine, the seam composes reads only:

- The contact section opens under ANY live grant, degrade-safe from the iam
  profile; consultation history only under the ``consultations`` scope; health
  background only under ``health_background``. A denied section answers
  ``None`` (the client's locked / "not shared" state), never an error.
- No live grant leaks nothing sensitive, and the case workspace is the
  doctor's own most recently updated case - present whenever one exists.
- The contact/photo block is access-logged (the detail marker) and egress-
  disclosed against the most permissive live grant (``full_record`` first,
  else the earliest consent id).
- The photo read fails closed without a live grant (RecordAccessDeniedError),
  returns ``None`` when no photo is stored, and is otherwise gated, logged,
  and disclosed like the contact block.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from modules.care.facade import CaseDetailView
from modules.consent.facade import CounterpartyGrantView
from modules.doctor.facade import DoctorConsoleFacade
from modules.health.facade import (
    HealthBackground,
    HealthBackgroundView,
    RecordAccessDeniedError,
    RecordEntryView,
    RecordTimeline,
)
from modules.iam.facade import PhotoContent

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

    async def get_patient_profile(self, identity_id: int) -> object:
        if self.profile_fail:
            raise RuntimeError("iam seam down")
        return self.profiles.get(identity_id)

    async def get_patient_photo(self, *, identity_id: int) -> PhotoContent | None:
        return self.photos.get(identity_id)


class StubHealthFacade:
    """Records doctor-view logs and answers the consented section reads.

    ``denied_scopes`` controls which consented reads raise
    ``RecordAccessDeniedError`` (the "already ledgered inside the seam"
    denial); anything else answers the canned view.
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
        self.history_calls: list[dict] = []
        self.background_calls: list[dict] = []

    async def log_doctor_patient_view(self, *, patient_id: int, doctor_id: int, scope: str) -> None:
        self.logged.append({"patient_id": patient_id, "doctor_id": doctor_id, "scope": scope})

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


def _facade(
    consent: StubConsentFacade | None = None,
    care: StubCareFacade | None = None,
    iam: StubIamFacade | None = None,
    health: StubHealthFacade | None = None,
) -> DoctorConsoleFacade:
    return DoctorConsoleFacade(
        consent_facade=consent or StubConsentFacade(),
        care_facade=care or StubCareFacade(),
        iam_facade=iam or StubIamFacade(),
        health_facade=health or StubHealthFacade(),
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
    assert result.contact.photo_ref == "profiles/abc"
    assert result.consultation_history.entries[0].entry_id == 1
    assert result.health_background.background.blood_group == "O+"


@pytest.mark.asyncio
async def test_detail_contact_opens_under_any_live_grant() -> None:
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
    assert result.contact.name is None


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
    assert result.contact.photo_ref is None
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


@pytest.mark.asyncio
async def test_photo_live_grant_streams_photo_and_discloses_contact_block() -> None:
    consent = StubConsentFacade([_grant(scope="full_record", consent_id=5, version=3)])
    iam = StubIamFacade(photos={_PATIENT_ID: _photo()})
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
async def test_photo_without_live_grant_fails_closed() -> None:
    consent = StubConsentFacade([_grant(scope="full_record", patient_id=99)])
    iam = StubIamFacade(photos={_PATIENT_ID: _photo()})
    health = StubHealthFacade()
    facade = _facade(consent=consent, iam=iam, health=health)

    with pytest.raises(RecordAccessDeniedError):
        await facade.get_doctor_patient_photo(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert health.logged == []
    assert consent.egress == []


@pytest.mark.asyncio
async def test_photo_granted_but_no_photo_answers_none_without_logging() -> None:
    consent = StubConsentFacade([_grant()])
    iam = StubIamFacade()
    health = StubHealthFacade()
    facade = _facade(consent=consent, iam=iam, health=health)

    photo = await facade.get_doctor_patient_photo(doctor_id=_DOCTOR_ID, patient_id=_PATIENT_ID)

    assert photo is None
    assert health.logged == []
    assert consent.egress == []
