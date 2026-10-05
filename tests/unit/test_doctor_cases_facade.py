"""#646: DoctorConsoleFacade open-cases projection for the doctor console.

Drives the cases-list read through stubbed consent/care/iam/health/partner
facades - no engine, the seam composes reads only. The read is the console
counterpart of the ADR-0019 Patients list:

- Open care cases become rows carrying the case facts the console already
  reads plus the patient's name/age/photo presence, enriched through the
  existing degrade-safe profile resolver.
- Open cases come from the care module's own open-cases seam (so this list
  and ``GET /v1/care/cases`` cannot disagree on the case set), rows are
  ordered creation-ascending by this read, and the read is unpaginated.
- A failing profile read degrades the whole batch to anonymous rows, warns
  with no patient identifier and no PHI, and still returns the list.
- A non-active or non-doctor partner is refused before any case, grant, or
  profile read happens.
- Every served row is access-logged once under the cases-list surface marker
  and egress-disclosed against the patient's live standing grant; a row with
  no live grant is not disclosed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from modules.care.facade import CaseDetailView
from modules.consent.facade import CounterpartyGrantView
from modules.doctor.domain.exceptions import DoctorConsoleAccessDeniedError
from modules.doctor.facade import DoctorConsoleFacade
from modules.partner.facade import DoctorProfileNotAllowedError, PartnerNotFoundError

_DOCTOR_ID = 42
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


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
    """Canned open-cases feed, recording the list call.

    Mirrors ``CaseConsoleFacade.list_doctor_cases``: the care module already
    answers "this doctor's open cases, oldest first", and the console consumes
    that seam rather than re-filtering the all-cases feed. ``all_cases_calls``
    stays empty whenever the console took the open-cases seam, so a regression
    that went back to re-filtering would be visible.
    """

    def __init__(self, cases: list[CaseDetailView] | None = None) -> None:
        self.cases = cases or []
        self.calls: list[int] = []
        self.all_cases_calls: list[int] = []

    async def list_doctor_cases(self, *, doctor_id: int) -> list[CaseDetailView]:
        self.calls.append(doctor_id)
        return self.cases

    async def list_doctor_all_cases(self, *, doctor_id: int) -> list[CaseDetailView]:
        self.all_cases_calls.append(doctor_id)
        return self.cases


class StubIamFacade:
    """Per-identity profile stand-in; can fail wholesale or for one patient."""

    def __init__(
        self,
        profiles: dict[int, object] | None = None,
        *,
        fail: bool = False,
        fail_for: int | None = None,
    ) -> None:
        self.profiles = profiles or {}
        self.fail = fail
        self.fail_for = fail_for
        self.reads: list[int] = []

    async def get_patient_profile(self, identity_id: int) -> object:
        self.reads.append(identity_id)
        if self.fail or identity_id == self.fail_for:
            raise RuntimeError("iam seam down")
        return self.profiles.get(identity_id)


class StubHealthFacade:
    """Records every access-log call with its surface marker.

    ``scope`` defaults to the marker the real health facade owns for its own
    Patients list, so a caller that relies on that default is recorded the way
    the ledger would actually record it (MOD-012 passes a marker only for the
    surfaces it owns).
    """

    def __init__(self) -> None:
        self.logged: list[tuple[int, int, str]] = []

    async def log_doctor_patient_view(
        self, *, patient_id: int, doctor_id: int, scope: str = "doctor_patients_list"
    ) -> None:
        self.logged.append((patient_id, doctor_id, scope))


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
    stage: str = "pre_summary",
    forced_review: bool = False,
    created_at: datetime = NOW,
    updated_at: datetime | None = None,
    doctor_id: int = _DOCTOR_ID,
) -> CaseDetailView:
    return CaseDetailView(
        case_id=case_id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        pre_summary_id=case_id,
        stage=stage,
        forced_review=forced_review,
        closed_at=created_at if stage == "closed" else None,
        close_reason=None,
        created_at=created_at,
        updated_at=updated_at or created_at,
    )


def _profile(name: str, age: int = 30, photo_ref: str | None = None) -> object:
    return type("Profile", (), {"name": name, "age": age, "photo_ref": photo_ref})()


# ---------------------------------------------------------------------------
# Row shape and identity enrichment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_case_row_carries_case_facts_and_patient_identity() -> None:
    care = StubCareFacade([_case(case_id=7, patient_id=10)])
    iam = StubIamFacade({10: _profile("Ravi Kumar", 32)})
    facade = _facade(care=care, iam=iam)

    result = await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

    assert len(result.items) == 1
    row = result.items[0]
    assert row.case_id == 7
    assert row.stage == "pre_summary"
    assert row.forced_review is False
    assert row.created_at == NOW
    assert row.updated_at == NOW
    assert row.patient_id == 10
    assert row.patient_name == "Ravi Kumar"
    assert row.patient_age == 32
    assert row.has_photo is False


@pytest.mark.asyncio
async def test_row_carries_the_forced_review_flag_and_the_prescription_stage() -> None:
    care = StubCareFacade(
        [
            _case(
                case_id=1,
                patient_id=10,
                stage="prescription_pending",
                forced_review=True,
                created_at=NOW,
                updated_at=NOW + timedelta(hours=3),
            )
        ]
    )
    facade = _facade(care=care)

    result = await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

    row = result.items[0]
    assert row.stage == "prescription_pending"
    assert row.forced_review is True
    assert row.updated_at == NOW + timedelta(hours=3)


@pytest.mark.asyncio
async def test_row_ships_photo_presence_never_the_storage_key() -> None:
    care = StubCareFacade([_case(case_id=1, patient_id=10)])
    iam = StubIamFacade({10: _profile("Ravi Kumar", photo_ref="patient/7/photo-1.enc")})
    facade = _facade(care=care, iam=iam)

    result = await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

    assert result.items[0].has_photo is True
    assert "photo-1.enc" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_each_patient_profile_is_resolved_once_for_the_whole_batch() -> None:
    # One resolver pass over the distinct patient set - the shared
    # degrade-safe resolver, not a per-row second lookup.
    care = StubCareFacade([_case(case_id=1, patient_id=10), _case(case_id=2, patient_id=10)])
    iam = StubIamFacade({10: _profile("Ravi Kumar", 32)})
    facade = _facade(care=care, iam=iam)

    result = await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

    assert [row.case_id for row in result.items] == [1, 2]
    assert iam.reads == [10]


@pytest.mark.asyncio
async def test_missing_profile_yields_anonymous_row_fields() -> None:
    care = StubCareFacade([_case(case_id=1, patient_id=10)])
    iam = StubIamFacade()
    facade = _facade(care=care, iam=iam)

    result = await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

    row = result.items[0]
    assert row.patient_id == 10
    assert row.patient_name is None
    assert row.patient_age is None
    assert row.has_photo is False


# ---------------------------------------------------------------------------
# Degrade-safe enrichment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_failure_degrades_the_whole_batch_to_anonymous_rows(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The shared resolver degrades wholesale: one failed profile read costs
    # every row its name, never the list itself.
    care = StubCareFacade([_case(case_id=1, patient_id=10), _case(case_id=2, patient_id=20)])
    iam = StubIamFacade({10: _profile("Ravi Kumar", 32)}, fail=True)
    facade = _facade(care=care, iam=iam)

    with caplog.at_level(logging.WARNING, logger="modules.doctor.facade"):
        result = await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

    assert [row.case_id for row in result.items] == [1, 2]
    assert [row.patient_name for row in result.items] == [None, None]
    assert [row.patient_age for row in result.items] == [None, None]
    warnings = [
        record.getMessage() for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    # No patient identifier and no PHI in the log line.
    assert "10" not in warnings[0]
    assert "20" not in warnings[0]
    assert "Ravi" not in warnings[0]


@pytest.mark.asyncio
async def test_a_mid_batch_profile_failure_still_degrades_the_whole_batch() -> None:
    # Not a per-row fallback: patient 10's profile resolves before the read for
    # 20 fails, and its name is dropped too - a half-enriched batch would
    # imply a partial read of the identity module that never happened.
    care = StubCareFacade([_case(case_id=1, patient_id=10), _case(case_id=2, patient_id=20)])
    iam = StubIamFacade({10: _profile("Ravi Kumar", 32)}, fail_for=20)
    facade = _facade(care=care, iam=iam)

    result = await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

    assert iam.reads == [10, 20]
    assert [row.patient_name for row in result.items] == [None, None]
    assert [row.patient_age for row in result.items] == [None, None]


# ---------------------------------------------------------------------------
# Case-set ownership and ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_console_consumes_the_care_modules_open_cases_seam() -> None:
    # Not the all-cases feed re-filtered here: a second copy of MOD-006's
    # non-closed filter is exactly how the console work list and
    # GET /v1/care/cases would come to answer different case sets.
    care = StubCareFacade([_case(case_id=1, patient_id=10)])
    facade = _facade(care=care)

    await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

    assert care.calls == [_DOCTOR_ID]
    assert care.all_cases_calls == []


@pytest.mark.asyncio
async def test_rows_are_ordered_creation_ascending_regardless_of_the_feed_order() -> None:
    care = StubCareFacade(
        [
            _case(case_id=10, patient_id=10, created_at=NOW),
            _case(case_id=20, patient_id=20, created_at=NOW - timedelta(days=2)),
            _case(case_id=30, patient_id=10, created_at=NOW - timedelta(days=1)),
        ]
    )
    facade = _facade(care=care)

    result = await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

    assert [row.case_id for row in result.items] == [20, 30, 10]


@pytest.mark.asyncio
async def test_empty_result_when_the_doctor_has_no_cases() -> None:
    health = StubHealthFacade()
    facade = _facade(health=health)

    result = await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

    assert result.items == []
    assert health.logged == []


# ---------------------------------------------------------------------------
# Seam call shape, access logging, and egress disclosure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cases_and_grants_are_read_for_the_edge_supplied_doctor() -> None:
    consent = StubConsentFacade()
    care = StubCareFacade()
    facade = _facade(consent=consent, care=care)

    await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

    assert consent.calls == [("doctor", "42")]
    assert care.calls == [_DOCTOR_ID]


@pytest.mark.asyncio
async def test_every_served_row_is_access_logged_once_with_the_cases_marker() -> None:
    care = StubCareFacade([_case(case_id=1, patient_id=10), _case(case_id=2, patient_id=20)])
    health = StubHealthFacade()
    facade = _facade(care=care, health=health)

    await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

    assert sorted(health.logged) == [
        (10, _DOCTOR_ID, "doctor_cases_list"),
        (20, _DOCTOR_ID, "doctor_cases_list"),
    ]


@pytest.mark.asyncio
async def test_access_log_marker_is_distinct_from_the_patients_list_marker() -> None:
    care = StubCareFacade([_case(case_id=1, patient_id=10)])
    health = StubHealthFacade()
    facade = _facade(care=care, health=health)

    await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)
    await facade.list_doctor_patients(doctor_id=_DOCTOR_ID)

    scopes = {scope for _, _, scope in health.logged}
    assert scopes == {"doctor_cases_list", "doctor_patients_list"}


@pytest.mark.asyncio
async def test_every_served_row_with_a_live_grant_is_egress_disclosed() -> None:
    consent = StubConsentFacade(
        [_grant(patient_id=10, consent_id=1, version=2), _grant(patient_id=20, consent_id=7)]
    )
    care = StubCareFacade([_case(case_id=1, patient_id=10), _case(case_id=2, patient_id=20)])
    facade = _facade(consent=consent, care=care)

    await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

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
async def test_egress_prefers_the_full_record_grant_as_authorizing() -> None:
    consent = StubConsentFacade(
        [
            _grant(patient_id=10, scope="lab_results", consent_id=3, version=1),
            _grant(patient_id=10, scope="full_record", consent_id=9, version=4),
        ]
    )
    care = StubCareFacade([_case(case_id=1, patient_id=10)])
    facade = _facade(consent=consent, care=care)

    await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

    assert len(consent.egress) == 1
    assert consent.egress[0]["consent_id"] == 9
    assert consent.egress[0]["record_scope"] == "full_record"
    assert consent.egress[0]["version"] == 4


@pytest.mark.asyncio
async def test_every_row_of_one_patient_discloses_against_that_patients_grant() -> None:
    consent = StubConsentFacade([_grant(patient_id=10, consent_id=4)])
    care = StubCareFacade([_case(case_id=1, patient_id=10), _case(case_id=2, patient_id=10)])
    facade = _facade(consent=consent, care=care)

    await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

    assert [row["patient_id"] for row in consent.egress] == [10, 10]
    assert {row["consent_id"] for row in consent.egress} == {4}


@pytest.mark.asyncio
async def test_egress_skips_a_row_with_no_live_grant() -> None:
    consent = StubConsentFacade([_grant(patient_id=10)])
    care = StubCareFacade([_case(case_id=1, patient_id=10), _case(case_id=2, patient_id=99)])
    health = StubHealthFacade()
    facade = _facade(consent=consent, care=care, health=health)

    await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

    # Row 99 is served from the care case alone: no standing grant to cite, so
    # no egress row is fabricated - but the access-history row still records it.
    assert [row["patient_id"] for row in consent.egress] == [10]
    assert sorted(entry[0] for entry in health.logged) == [10, 99]


# ---------------------------------------------------------------------------
# Facade-side authorization re-check (api-standards §6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cases_read_rechecks_the_active_doctor_role_in_the_facade() -> None:
    partner = StubPartnerFacade()
    facade = _facade(partner=partner)

    await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

    assert partner.checked == [_DOCTOR_ID]


@pytest.mark.parametrize("refusal", ["not_a_doctor", "not_active", "gone"])
@pytest.mark.asyncio
async def test_cases_read_refuses_a_non_doctor_or_non_active_partner(refusal: str) -> None:
    consent = StubConsentFacade([_grant(patient_id=10)])
    care = StubCareFacade([_case(case_id=1, patient_id=10)])
    iam = StubIamFacade({10: _profile("Ravi Kumar", 32)})
    health = StubHealthFacade()
    partner = StubPartnerFacade(refusal=refusal)
    facade = _facade(consent=consent, care=care, iam=iam, health=health, partner=partner)

    with pytest.raises(DoctorConsoleAccessDeniedError):
        await facade.list_doctor_cases(doctor_id=_DOCTOR_ID)

    assert consent.calls == []
    assert care.calls == []
    assert iam.reads == []
    assert health.logged == []
    assert consent.egress == []
