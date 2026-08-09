"""Phase 0 corpus fixture loader.

Loads the committed Phase 0 Hindi voice corpus and its ground truth in a
single call via :func:`load_corpus`. This is throwaway research code for the
PHASE-0 feasibility spike (issue #2 / #3) and is intentionally not production
code; it mirrors the shape a future AI-gateway fixture loader might take.

Only the Python standard library is used so the corpus stays loadable in any
environment without extra dependencies.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PHASE0 = Path(__file__).resolve().parent
CORPUS_DIR = _PHASE0 / "corpus"
MANIFEST = CORPUS_DIR / "manifest.json"
FIELD_SET = _PHASE0 / "field_set" / "field_set.json"

COHORTS = frozenset({"urban_hindi", "peri_urban", "heavy_local"})

REQUIRED_PRESUMMARY_FIELDS = frozenset(
    {
        "clip_id",
        "cohort",
        "field_set_version",
        "chief_complaint",
        "onset",
        "duration",
        "location",
        "severity",
        "nature",
        "associated_symptoms",
        "aggravating_factors",
        "relieving_factors",
        "known_medications",
        "allergies",
        "past_history",
        "family_history",
        "vitals",
        "labs_ordered",
        "diagnosis_impression",
        "advice",
        "follow_up",
        "clinical_notes",
        "extraction_notes",
    }
)

_PHI_PATTERNS = (
    re.compile(r"(?:\+?91[\s-]?|0[\s-]?)?[6-9]\d{9}"),
    re.compile(r"\S+@\S+\.\S+"),
    re.compile(r"मेरा नाम", re.IGNORECASE),
    re.compile(r"नाम [\u0900-\u097F]+"),
    re.compile(r"(?:डॉक्टर|Dr\.)\s+[A-Za-z]", re.IGNORECASE),
)


class CorpusError(ValueError):
    """Raised when the corpus fixtures are missing or malformed."""


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise CorpusError(f"missing fixture file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CorpusError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CorpusError(f"expected a JSON object in {path}")
    return data


def _optional(value: Any, field_name: str, clip_id: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CorpusError(f"{clip_id}: field {field_name} must be a string or null")
    return value


def _tuple(value: Any, field_name: str, clip_id: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise CorpusError(f"{clip_id}: field {field_name} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise CorpusError(f"{clip_id}: field {field_name} must contain only strings")
    return tuple(value)


@dataclass(frozen=True)
class Medication:
    name: str | None
    strength: str | None
    frequency: str | None
    route: str | None
    duration: str | None
    note: str | None


@dataclass(frozen=True)
class Vitals:
    temperature: str | None
    blood_pressure: str | None
    pulse: str | None
    spo2: str | None
    height_cm: str | None
    weight_kg: str | None
    bmi: str | None
    other: tuple[str, ...]


@dataclass(frozen=True)
class PreSummary:
    clip_id: str
    cohort: str
    field_set_version: str
    chief_complaint: str | None
    onset: str | None
    duration: str | None
    location: str | None
    severity: str | None
    nature: str | None
    associated_symptoms: tuple[str, ...]
    aggravating_factors: tuple[str, ...]
    relieving_factors: tuple[str, ...]
    known_medications: tuple[Medication, ...]
    allergies: tuple[str, ...]
    past_history: tuple[str, ...]
    family_history: tuple[str, ...]
    vitals: Vitals
    labs_ordered: tuple[str, ...]
    diagnosis_impression: str | None
    advice: tuple[str, ...]
    follow_up: str | None
    clinical_notes: str
    extraction_notes: str


@dataclass(frozen=True)
class Clip:
    clip_id: str
    cohort: str
    audio_path: Path
    transcript_path: Path
    pre_summary_path: Path
    duration_s: float
    word_count: int


@dataclass(frozen=True)
class FieldSet:
    version: str
    name: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class Corpus:
    field_set: FieldSet
    clips: tuple[Clip, ...]
    pre_summaries: tuple[PreSummary, ...]

    def clip_by_id(self) -> dict[str, Clip]:
        """Index clips by id — the runner's hot lookup, built once per run."""
        return {clip.clip_id: clip for clip in self.clips}

    def pre_summary_by_id(self) -> dict[str, PreSummary]:
        """Index ground-truth pre-summaries by clip id, built once per run."""
        return {summary.clip_id: summary for summary in self.pre_summaries}


@dataclass(frozen=True)
class PhiFinding:
    clip_id: str
    pattern: str
    snippet: str


def _parse_medications(value: Any, clip_id: str) -> tuple[Medication, ...]:
    if not isinstance(value, list):
        raise CorpusError(f"{clip_id}: known_medications must be a list")
    meds: list[Medication] = []
    for item in value:
        if not isinstance(item, dict):
            raise CorpusError(f"{clip_id}: each medication must be an object")
        meds.append(
            Medication(
                name=_optional(item.get("name"), "medication.name", clip_id),
                strength=_optional(item.get("strength"), "medication.strength", clip_id),
                frequency=_optional(item.get("frequency"), "medication.frequency", clip_id),
                route=_optional(item.get("route"), "medication.route", clip_id),
                duration=_optional(item.get("duration"), "medication.duration", clip_id),
                note=_optional(item.get("note"), "medication.note", clip_id),
            )
        )
    return tuple(meds)


def _parse_vitals(value: Any, clip_id: str) -> Vitals:
    if not isinstance(value, dict):
        raise CorpusError(f"{clip_id}: vitals must be an object")
    return Vitals(
        temperature=_optional(value.get("temperature"), "vitals.temperature", clip_id),
        blood_pressure=_optional(value.get("blood_pressure"), "vitals.blood_pressure", clip_id),
        pulse=_optional(value.get("pulse"), "vitals.pulse", clip_id),
        spo2=_optional(value.get("spo2"), "vitals.spo2", clip_id),
        height_cm=_optional(value.get("height_cm"), "vitals.height_cm", clip_id),
        weight_kg=_optional(value.get("weight_kg"), "vitals.weight_kg", clip_id),
        bmi=_optional(value.get("bmi"), "vitals.bmi", clip_id),
        other=_tuple(value.get("other", []), "vitals.other", clip_id),
    )


def parse_pre_summary(data: dict[str, Any]) -> PreSummary:
    clip_id = str(data.get("clip_id", "?"))
    missing = REQUIRED_PRESUMMARY_FIELDS.difference(data)
    if missing:
        raise CorpusError(f"{clip_id}: missing required fields: {sorted(missing)}")
    cohort = data["cohort"]
    if cohort not in COHORTS:
        raise CorpusError(f"{clip_id}: unknown cohort {cohort!r}")
    return PreSummary(
        clip_id=clip_id,
        cohort=cohort,
        field_set_version=str(data["field_set_version"]),
        chief_complaint=_optional(data["chief_complaint"], "chief_complaint", clip_id),
        onset=_optional(data["onset"], "onset", clip_id),
        duration=_optional(data["duration"], "duration", clip_id),
        location=_optional(data["location"], "location", clip_id),
        severity=_optional(data["severity"], "severity", clip_id),
        nature=_optional(data["nature"], "nature", clip_id),
        associated_symptoms=_tuple(data["associated_symptoms"], "associated_symptoms", clip_id),
        aggravating_factors=_tuple(data["aggravating_factors"], "aggravating_factors", clip_id),
        relieving_factors=_tuple(data["relieving_factors"], "relieving_factors", clip_id),
        known_medications=_parse_medications(data["known_medications"], clip_id),
        allergies=_tuple(data["allergies"], "allergies", clip_id),
        past_history=_tuple(data["past_history"], "past_history", clip_id),
        family_history=_tuple(data["family_history"], "family_history", clip_id),
        vitals=_parse_vitals(data["vitals"], clip_id),
        labs_ordered=_tuple(data["labs_ordered"], "labs_ordered", clip_id),
        diagnosis_impression=_optional(
            data["diagnosis_impression"], "diagnosis_impression", clip_id
        ),
        advice=_tuple(data["advice"], "advice", clip_id),
        follow_up=_optional(data["follow_up"], "follow_up", clip_id),
        clinical_notes=str(data["clinical_notes"]),
        extraction_notes=str(data["extraction_notes"]),
    )


def _resolve_fixture(rel: str) -> Path:
    """Resolve a manifest-relative fixture path.

    Manifest paths are stored as ``corpus/audio/sample_0002.wav`` (relative to
    phase0/). Tolerate a bare-relative variant (``audio/sample_0002.wav``) for
    robustness.
    """
    candidate = _PHASE0 / rel
    if candidate.is_file():
        return candidate
    fallback = CORPUS_DIR / rel
    if fallback.is_file():
        return fallback
    return candidate


def load_corpus() -> Corpus:
    """Load the full corpus (manifest, field set, pre-summaries) in one call."""
    manifest_data = _load_json(MANIFEST)
    rows = manifest_data.get("clips")
    if not isinstance(rows, list):
        raise CorpusError("manifest.json must contain a 'clips' array")

    clips: list[Clip] = []
    for row in rows:
        if not isinstance(row, dict):
            raise CorpusError("each manifest row must be an object")
        clip_id = str(row["clip_id"])
        cohort = str(row["cohort"])
        if cohort not in COHORTS:
            raise CorpusError(f"{clip_id}: unknown cohort {cohort!r}")
        clips.append(
            Clip(
                clip_id=clip_id,
                cohort=cohort,
                audio_path=_resolve_fixture(str(row["audio_path"])),
                transcript_path=_resolve_fixture(str(row["transcript_path"])),
                pre_summary_path=_resolve_fixture(str(row["pre_summary_path"])),
                duration_s=float(row["duration_s"]),
                word_count=int(row["word_count"]),
            )
        )

    field_set_data = _load_json(FIELD_SET)
    field_set = FieldSet(
        version=str(field_set_data["field_set_version"]),
        name=str(field_set_data["name"]),
        fields=tuple(str(f["name"]) for f in field_set_data["fields"]),
    )

    pre_summaries: list[PreSummary] = []
    for clip in clips:
        pre_summaries.append(parse_pre_summary(_load_json(clip.pre_summary_path)))

    return Corpus(field_set=field_set, clips=tuple(clips), pre_summaries=tuple(pre_summaries))


def scan_phi(corpus: Corpus) -> tuple[PhiFinding, ...]:
    """Heuristic PHI scan over transcripts.

    Detects phone numbers, email addresses, and common Hindi proper-name cues.
    This is a best-effort first-pass guard, not a substitute for human review;
    see phase0/PHI_SCAN.md.
    """
    findings: list[PhiFinding] = []
    for clip in corpus.clips:
        text = clip.transcript_path.read_text(encoding="utf-8")
        for pattern in _PHI_PATTERNS:
            match = pattern.search(text)
            if match is not None:
                start = max(0, match.start() - 20)
                snippet = text[start : match.end() + 20].replace("\n", " ")
                findings.append(
                    PhiFinding(clip_id=clip.clip_id, pattern=pattern.pattern, snippet=snippet)
                )
    return tuple(findings)
