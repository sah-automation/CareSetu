"""PHASE-8.2 T01: DoctorConsoleFacade Patients list derivation (ticket #539).

Drives the ADR-0019 Current/Past derivation through stubbed consent/care/
iam/health facades - no engine, the seam composes reads only:

- Current = live standing grant (any record scope) OR an open care case.
- Past = only closed cases and no live grant; a revoked grant falls back.
- Each row carries the live consent scopes (scope badges) and the most
  recent care stage across its cases.
- Row enrichment (name/age/photo presence) degrades safely when a profile
  is missing or the iam seam fails (review-queue convention), and search is a
  case-insensitive name substring that never matches a nameless row.
- Every served row is access-logged exactly once through the health facade and
  egress-disclosed against the authorizing live grant; a case-only row has no
  grant to disclose against and is skipped.
- Rows carry a ``has_photo`` presence flag, never the private storage key.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from modules.care.facade import CaseDetailView
from modules.consent.facade import CounterpartyGrantView
from modules.doctor.domain.exceptions import DoctorConsoleAccessDeniedError
from modules.doctor.facade import DoctorConsoleFacade
from modules.partner.facade import DoctorProfileNotAllowedError, PartnerNotFoundError

_DOCTOR_ID = 42
NOW = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Stub facades
# ---------------------------------------------------------------------------


class StubConsentFacade:
    """Canned counterparty grants, recording the reverse lookup and egress rows."""

    def __init__(self, grants: list[CounterpartyGrantView] | None = None) -> None:
        self.grants = grants or []
        self.calls: list[tuple[str, str]] = []
        self.egress: list[dict] = []

    async def list_counterparty_grants(
        self, *, counterparty_type: str, counterparty_id: str
    ) -> list[CounterpartyGrantView]:
        self.calls.append((counterparty_type, counterparty_id))
        return self.grants

    async def record_egress_disclosure(self, **kwargs: object) -> None:
        self.egress.append(dict(kwargs))


class StubCareFacade:
    """Canned all-cases feed, recording the list call."""

    def __init__(self, cases: list[CaseDetailView] | None = None) -> None:
        self.cases = cases or []
        self.calls: list[int] = []

    async def list_doctor_all_cases(self, *, doctor_id: int) -> list[CaseDetailView]:
        self.calls.append(doctor_id)
        return self.cases


class StubIamFacade:
    """Per-identity profile stand-in; can be pointed to fail wholesale."""

    def __init__(
        self,
        profiles: dict[int, object] | None = None,
        *,
        fail: bool = False,
    ) -> None:
        self.profiles = profiles or {}
        self.fail = fail
        self.reads: list[int] = []

    async def get_patient_profile(self, identity_id: int) -> object:
        self.reads.append(identity_id)
        if self.fail:
            raise RuntimeError("iam seam down")
        return self.profiles.get(identity_id)


class StubHealthFacade:
    """Records every access-log call; the doctor console has no ledger of its own."""

    def __init__(self) -> None:
        self.logged: list[tuple[int, int]] = []

    async def log_doctor_patient_view(self, *, patient_id: int, doctor_id: int) -> None:
        self.logged.append((patient_id, doctor_id))


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
# Row builders
# ---------------------------------------------------------------------------


def _grant(
    *,
    patient_id: int,
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
    patient_id: int,
    stage: str,
    updated_at: datetime,
    doctor_id: int = _DOCTOR_ID,
) -> CaseDetailView:
    return CaseDetailView(
        case_id=case_id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        pre_summary_id=case_id,
        stage=stage,
        closed_at=updated_at if stage == "closed" else None,
        close_reason=None,
        created_at=updated_at,
        updated_at=updated_at,
    )


def _profile(name: str, age: int = 30, photo_ref: str | None = None) -> object:
    return type("Profile", (), {"name": name, "age": age, "photo_ref": photo_ref})()


# ---------------------------------------------------------------------------
# ADR-0019 derivation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_current_patient_from_live_grant_only() -> None:
    consent = StubConsentFacade([_grant(patient_id=10, scope="health_background")])
    facade = _facade(consent=consent)

    result = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.patient_id == 10
    assert item.bucket == "current"
    assert item.granted_scopes == ["health_background"]
    assert item.latest_case_stage is None


@pytest.mark.asyncio
async def test_current_patient_from_open_care_case() -> None:
    care = StubCareFacade([_case(case_id=1, patient_id=20, stage="pre_summary", updated_at=NOW)])
    facade = _facade(care=care)

    result = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.bucket == "current"
    assert item.granted_scopes == []
    assert item.latest_case_stage == "pre_summary"


@pytest.mark.asyncio
async def test_past_patient_from_closed_case_with_no_live_grant() -> None:
    care = StubCareFacade([_case(case_id=1, patient_id=30, stage="closed", updated_at=NOW)])
    facade = _facade(care=care)

    result = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.bucket == "past"
    assert item.latest_case_stage == "closed"
    assert item.granted_scopes == []


@pytest.mark.asyncio
async def test_revoked_grant_falls_patient_to_past() -> None:
    # The grant list the consent seam currently answers excludes the revoked
    # lineage - only the closed case remains, so ADR-0019 buckets Past.
    care = StubCareFacade([_case(case_id=9, patient_id=40, stage="closed", updated_at=NOW)])
    facade = _facade(care=care)

    result = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    assert [item.patient_id for item in result.items] == [40]
    assert result.items[0].bucket == "past"


@pytest.mark.asyncio
async def test_live_grant_keeps_closed_case_current() -> None:
    consent = StubConsentFacade([_grant(patient_id=50, scope="full_record")])
    care = StubCareFacade([_case(case_id=1, patient_id=50, stage="closed", updated_at=NOW)])
    facade = _facade(consent=consent, care=care)

    result = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    assert [item.bucket for item in result.items] == ["current"]


@pytest.mark.asyncio
async def test_grant_and_open_case_dedupe_to_one_current_row() -> None:
    consent = StubConsentFacade([_grant(patient_id=60, scope="full_record")])
    care = StubCareFacade(
        [_case(case_id=1, patient_id=60, stage="prescription_pending", updated_at=NOW)]
    )
    facade = _facade(consent=consent, care=care)

    result = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    assert len(result.items) == 1
    assert result.items[0].bucket == "current"


# ---------------------------------------------------------------------------
# Scope badges and latest stage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_granted_scopes_collect_across_grants() -> None:
    consent = StubConsentFacade(
        [
            _grant(patient_id=70, scope="consultations", consent_id=1),
            _grant(patient_id=70, scope="lab_results", consent_id=2),
        ]
    )
    facade = _facade(consent=consent)

    result = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    assert sorted(result.items[0].granted_scopes) == ["consultations", "lab_results"]


@pytest.mark.asyncio
async def test_latest_case_stage_is_most_recently_updated_case() -> None:
    care = StubCareFacade(
        [
            _case(
                case_id=1,
                patient_id=80,
                stage="pre_summary",
                updated_at=datetime(2026, 9, 1, tzinfo=UTC),
            ),
            _case(
                case_id=2,
                patient_id=80,
                stage="closed",
                updated_at=datetime(2026, 9, 5, tzinfo=UTC),
            ),
            _case(
                case_id=3,
                patient_id=80,
                stage="prescription_pending",
                updated_at=datetime(2026, 9, 3, tzinfo=UTC),
            ),
        ]
    )
    facade = _facade(care=care)

    result = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    assert len(result.items) == 1
    assert result.items[0].latest_case_stage == "closed"
    # Any open case still keeps the patient current even when an older stage
    # is closed - the closed case did not end the relationship.
    assert result.items[0].bucket == "current"


# ---------------------------------------------------------------------------
# Profile enrichment and search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rows_enriched_from_identity_profile() -> None:
    consent = StubConsentFacade([_grant(patient_id=10), _grant(patient_id=20)])
    iam = StubIamFacade({10: _profile("Ravi Kumar", 32)})
    facade = _facade(consent=consent, iam=iam)

    result = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    by_id = {item.patient_id: item for item in result.items}
    assert by_id[10].name == "Ravi Kumar"
    assert by_id[10].age == 32
    assert by_id[20].name is None
    assert by_id[20].age is None
    assert sorted(iam.reads) == [10, 20]


@pytest.mark.asyncio
async def test_profile_resolution_failure_degrades_to_anonymous_rows() -> None:
    consent = StubConsentFacade([_grant(patient_id=10)])
    iam = StubIamFacade(fail=True)
    facade = _facade(consent=consent, iam=iam)

    result = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    assert len(result.items) == 1
    assert result.items[0].patient_id == 10
    assert result.items[0].name is None
    assert result.items[0].age is None
    assert result.items[0].has_photo is False


@pytest.mark.asyncio
async def test_rows_ship_photo_presence_never_the_storage_key() -> None:
    consent = StubConsentFacade([_grant(patient_id=10)])
    iam = StubIamFacade({10: _profile("Ravi Kumar", photo_ref="patient/7/photo-1.enc")})
    facade = _facade(consent=consent, iam=iam)

    result = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    assert result.items[0].has_photo is True
    assert "photo-1.enc" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_search_filters_rows_by_case_insensitive_name() -> None:
    consent = StubConsentFacade(
        [_grant(patient_id=10), _grant(patient_id=20), _grant(patient_id=30)]
    )
    iam = StubIamFacade({10: _profile("Ravi Kumar"), 20: _profile("Anita Sharma")})
    facade = _facade(consent=consent, iam=iam)

    result = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID, search="RAVI")

    assert [item.patient_id for item in result.items] == [10]


@pytest.mark.asyncio
async def test_search_never_matches_nameless_rows() -> None:
    consent = StubConsentFacade([_grant(patient_id=10), _grant(patient_id=30)])
    iam = StubIamFacade({10: _profile("Ravi Kumar")})
    facade = _facade(consent=consent, iam=iam)

    result = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID, search="kumar")

    assert [item.patient_id for item in result.items] == [10]


@pytest.mark.asyncio
async def test_blank_search_returns_all_rows() -> None:
    consent = StubConsentFacade([_grant(patient_id=10), _grant(patient_id=20)])
    iam = StubIamFacade({10: _profile("Ravi Kumar"), 20: _profile("Anita Sharma")})
    facade = _facade(consent=consent, iam=iam)

    result = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID, search="   ")

    assert sorted(item.patient_id for item in result.items) == [10, 20]


@pytest.mark.asyncio
async def test_rows_sorted_by_name_then_patient_id_nameless_first() -> None:
    consent = StubConsentFacade(
        [_grant(patient_id=10), _grant(patient_id=20), _grant(patient_id=30), _grant(patient_id=40)]
    )
    iam = StubIamFacade({20: _profile("Ravi Kumar"), 40: _profile("Anita Sharma")})
    facade = _facade(consent=consent, iam=iam)

    result = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    # Nameless (10, 30) sort first by (name or ""), then named alphabetically.
    assert [item.patient_id for item in result.items] == [10, 30, 40, 20]
    assert result.total == 4


@pytest.mark.asyncio
async def test_pagination_slices_rows_and_reports_total() -> None:
    consent = StubConsentFacade(
        [_grant(patient_id=10), _grant(patient_id=20), _grant(patient_id=30), _grant(patient_id=40)]
    )
    iam = StubIamFacade({10: _profile("Ravi Kumar"), 40: _profile("Anita Sharma")})
    facade = _facade(consent=consent, iam=iam)

    first = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID, page=1, per_page=2)

    # Sorted by (name or "", patient_id): nameless 20, 30 first, then Anita (40), Ravi (10).
    assert [item.patient_id for item in first.items] == [20, 30]
    assert first.total == 4

    second = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID, page=2, per_page=2)

    assert [item.patient_id for item in second.items] == [40, 10]
    assert second.total == 4


@pytest.mark.asyncio
async def test_pagination_access_logs_page_rows_only() -> None:
    consent = StubConsentFacade(
        [_grant(patient_id=10), _grant(patient_id=20), _grant(patient_id=30)]
    )
    health = StubHealthFacade()
    facade = _facade(consent=consent, health=health)

    await facade.list_doctor_patients(doctor_id=_DOCTOR_ID, page=1, per_page=2)

    assert sorted(health.logged) == [(10, _DOCTOR_ID), (20, _DOCTOR_ID)]


# ---------------------------------------------------------------------------
# Seam call shape and access logging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grants_queried_for_the_doctor_as_counterparty() -> None:
    consent = StubConsentFacade([])
    facade = _facade(consent=consent)

    await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    assert consent.calls == [("doctor", "42")]


@pytest.mark.asyncio
async def test_every_served_row_is_access_logged_once() -> None:
    consent = StubConsentFacade([_grant(patient_id=10), _grant(patient_id=20)])
    care = StubCareFacade([_case(case_id=1, patient_id=30, stage="closed", updated_at=NOW)])
    health = StubHealthFacade()
    facade = _facade(consent=consent, care=care, health=health)

    await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    assert sorted(health.logged) == [(10, _DOCTOR_ID), (20, _DOCTOR_ID), (30, _DOCTOR_ID)]


@pytest.mark.asyncio
async def test_access_log_covers_filtered_rows_only() -> None:
    consent = StubConsentFacade([_grant(patient_id=10), _grant(patient_id=20)])
    iam = StubIamFacade({10: _profile("Ravi Kumar"), 20: _profile("Anita Sharma")})
    health = StubHealthFacade()
    facade = _facade(consent=consent, iam=iam, health=health)

    await facade.list_doctor_patients(doctor_id=_DOCTOR_ID, search="ravi")

    assert health.logged == [(10, _DOCTOR_ID)]


@pytest.mark.asyncio
async def test_empty_result_when_no_grants_and_no_cases() -> None:
    health = StubHealthFacade()
    facade = _facade(health=health)

    result = await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    assert result.items == []
    assert result.total == 0
    assert health.logged == []


# ---------------------------------------------------------------------------
# Egress disclosure (US-18)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_served_granted_row_is_egress_disclosed() -> None:
    consent = StubConsentFacade(
        [_grant(patient_id=10, consent_id=1, version=2), _grant(patient_id=20, consent_id=7)]
    )
    facade = _facade(consent=consent)

    await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    assert consent.egress == [
        {
            "patient_id": 10,
            "consent_id": 1,
            "version": 2,
            "counterparty_type": "doctor",
            "counterparty_id": "42",
            "record_scope": "full_record",
            "disclosed_entry_ids": [],
        },
        {
            "patient_id": 20,
            "consent_id": 7,
            "version": 1,
            "counterparty_type": "doctor",
            "counterparty_id": "42",
            "record_scope": "full_record",
            "disclosed_entry_ids": [],
        },
    ]


@pytest.mark.asyncio
async def test_list_egress_prefers_the_full_record_grant_as_authorizing() -> None:
    consent = StubConsentFacade(
        [
            _grant(patient_id=10, scope="lab_results", consent_id=3, version=1),
            _grant(patient_id=10, scope="full_record", consent_id=9, version=4),
        ]
    )
    facade = _facade(consent=consent)

    await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    assert len(consent.egress) == 1
    assert consent.egress[0]["consent_id"] == 9
    assert consent.egress[0]["record_scope"] == "full_record"
    assert consent.egress[0]["version"] == 4


@pytest.mark.asyncio
async def test_list_egress_skips_case_only_rows_with_no_live_grant() -> None:
    consent = StubConsentFacade([_grant(patient_id=10)])
    care = StubCareFacade([_case(case_id=1, patient_id=30, stage="closed", updated_at=NOW)])
    facade = _facade(consent=consent, care=care)

    await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    # Past patient 30 is served from the care case alone: there is no standing
    # grant to cite, so no egress row is fabricated for it.
    assert [row["patient_id"] for row in consent.egress] == [10]


@pytest.mark.asyncio
async def test_list_egress_covers_the_served_page_only() -> None:
    consent = StubConsentFacade(
        [_grant(patient_id=10), _grant(patient_id=20), _grant(patient_id=30)]
    )
    facade = _facade(consent=consent)

    await facade.list_doctor_patients(doctor_id=_DOCTOR_ID, page=1, per_page=2)

    assert [row["patient_id"] for row in consent.egress] == [10, 20]


# ---------------------------------------------------------------------------
# Facade-side authorization re-check (api-standards §6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_rechecks_the_active_doctor_role_in_the_facade() -> None:
    # The edge guard is convenience; the facade is the boundary, so the id it
    # was handed is re-checked against MOD-002 before any read happens.
    partner = StubPartnerFacade()
    facade = _facade(partner=partner)

    await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    assert partner.checked == [_DOCTOR_ID]


@pytest.mark.parametrize("refusal", ["not_a_doctor", "not_active", "gone"])
@pytest.mark.asyncio
async def test_list_refuses_a_non_doctor_or_non_active_partner(refusal: str) -> None:
    # Even a caller holding a live grant and cases is refused: the role check
    # runs first and answers the module's own 403 refusal, so nothing is read,
    # logged, or disclosed on the way out.
    consent = StubConsentFacade([_grant(patient_id=10)])
    care = StubCareFacade([_case(case_id=1, patient_id=10, stage="pre_summary", updated_at=NOW)])
    health = StubHealthFacade()
    partner = StubPartnerFacade(refusal=refusal)
    facade = _facade(consent=consent, care=care, health=health, partner=partner)

    with pytest.raises(DoctorConsoleAccessDeniedError):
        await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    assert consent.calls == []
    assert care.calls == []
    assert health.logged == []
    assert consent.egress == []
