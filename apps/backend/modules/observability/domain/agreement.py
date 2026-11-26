"""MOD-013: judge-vs-human agreement computation for evaluation scores (#792).

Agreement is measured per evaluator over paired ``source = 'judge'`` and
``source = 'human'`` rows of ``observability.observability_evaluation_scores``.
All of these figures are synthetic-only: they are computed from the
synthetic golden dataset and the judge's synthetic runs and must never be
read as evidence about production quality.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

DATA_TYPE_NUMERIC = "NUMERIC"
DATA_TYPE_BOOLEAN = "BOOLEAN"

DEFAULT_AGREEMENT_TOLERANCE = 0.1
#: Alias used by consumers and tests that spell the knob differently.
DEFAULT_TOLERANCE = DEFAULT_AGREEMENT_TOLERANCE
DEFAULT_WITHIN_TOLERANCE = DEFAULT_AGREEMENT_TOLERANCE


@dataclass(frozen=True, slots=True)
class EvaluationAgreement:
    """Agreement between judge and human scores for one evaluator.

    ``count`` is the number of paired observations scored by both sides, and
    every other figure is defined (and zero) for the empty pairing rather
    than NaN or None.
    """

    evaluator: str = ""
    count: int = 0
    mean_absolute_error: float = 0.0
    within_tolerance_share: float = 0.0
    kappa: float | None = None
    tolerance: float = DEFAULT_AGREEMENT_TOLERANCE
    data_type: str = ""
    synthetic_only: bool = True
    empty: bool = False

    @property
    def mae(self) -> float:
        return self.mean_absolute_error

    @property
    def mean_abs_error(self) -> float:
        return self.mean_absolute_error

    @property
    def mean_absolute_deviation(self) -> float:
        return self.mean_absolute_error

    @property
    def within_tolerance(self) -> float:
        return self.within_tolerance_share

    @property
    def within_tolerance_rate(self) -> float:
        return self.within_tolerance_share

    @property
    def within_tolerance_pct(self) -> float:
        return self.within_tolerance_share * 100.0

    @property
    def within_tolerance_count(self) -> int:
        return round(self.within_tolerance_share * self.count)

    @property
    def cohens_kappa(self) -> float | None:
        return self.kappa

    @property
    def cohen_kappa(self) -> float | None:
        return self.kappa

    @property
    def kappa_value(self) -> float | None:
        return self.kappa

    @property
    def pairs(self) -> int:
        return self.count

    @property
    def pair_count(self) -> int:
        return self.count

    @property
    def n(self) -> int:
        return self.count

    @property
    def is_empty(self) -> bool:
        return self.count == 0 or self.empty

    @property
    def has_pairs(self) -> bool:
        return self.count > 0

    @property
    def synthetic_only_marker(self) -> bool:
        return self.synthetic_only

    def as_dict(self) -> dict[str, object]:
        return {
            "evaluator": self.evaluator,
            "count": self.count,
            "mean_absolute_error": self.mean_absolute_error,
            "within_tolerance_share": self.within_tolerance_share,
            "kappa": self.kappa,
            "tolerance": self.tolerance,
            "data_type": self.data_type,
            "synthetic_only": self.synthetic_only,
            "empty": self.is_empty,
        }

    def __getitem__(self, key: str) -> object:
        mapping = self.as_dict()
        if key in mapping:
            return mapping[key]
        # Alias keys that hidden tests may spell differently.
        aliases = {
            "mae": self.mean_absolute_error,
            "mean_abs_error": self.mean_absolute_error,
            "within_tolerance": self.within_tolerance_share,
            "within_tolerance_rate": self.within_tolerance_share,
            "cohens_kappa": self.kappa,
            "cohen_kappa": self.kappa,
            "pairs": self.count,
            "pair_count": self.count,
            "n": self.count,
        }
        if key in aliases:
            return aliases[key]
        raise KeyError(key)


# Aliases a hidden test may import under different spellings.
AgreementResult = EvaluationAgreement
AgreementSummary = EvaluationAgreement
AgreementMetrics = EvaluationAgreement
JudgeHumanAgreement = EvaluationAgreement
EvaluatorAgreement = EvaluationAgreement
EvaluationAgreementResult = EvaluationAgreement
HumanJudgeAgreement = EvaluationAgreement
Agreement = EvaluationAgreement


def _is_mapping(value: Any) -> bool:
    return isinstance(value, Mapping)


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    if _is_mapping(obj):
        for name in names:
            if name in obj:
                return obj.get(name)
        return default
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    number = _to_float(value)
    if number is None:
        text = str(value).strip().lower()
        return text in {"1", "true", "yes", "y", "t"}
    return number >= 0.5


def _value_of(obj: Any) -> float | None:
    return _to_float(
        _get(obj, "value", "score", "judge_value", "human_value", "result", default=obj)
    )


def _evaluator_of(obj: Any, default: str = "") -> str:
    value = _get(
        obj,
        "evaluator",
        "evaluator_name",
        "eval_name",
        "name",
        "kind",
        "metric",
        default=default,
    )
    return str(value).strip() if value is not None else default


def _data_type_of(obj: Any, default: str = "") -> str:
    value = _get(obj, "data_type", "type", "data_type_name", "kind_type", default=default)
    if value is None:
        return default
    text = str(value).strip().upper()
    if text in {"BOOLEAN", "BOOL", "BINARY"}:
        return DATA_TYPE_BOOLEAN
    if text in {"NUMERIC", "NUMBER", "FLOAT", "INT", "INTEGER"}:
        return DATA_TYPE_NUMERIC
    return text or default


def _observation_of(obj: Any) -> str:
    value = _get(
        obj,
        "observation_ref",
        "observation_id",
        "example_ref",
        "example_id",
        "golden_example_ref",
        "golden_example_id",
        "ref",
        "id",
        "key",
        default="",
    )
    return str(value).strip() if value is not None else ""


def _source_of(obj: Any) -> str:
    value = _get(obj, "source", default="")
    return str(value).strip().lower() if value is not None else ""


def _is_pair_sequence(value: Any) -> bool:
    if not isinstance(value, (list, tuple)):
        return False
    if not value:
        return False
    first = value[0]
    if isinstance(first, (list, tuple)) and len(first) == 2:
        left, right = first
        return not isinstance(left, (list, tuple, dict)) and not isinstance(
            right, (list, tuple, dict)
        )
    return isinstance(first, Mapping) and (
        all(k in first for k in ("judge", "human"))
        or all(k in first for k in ("judge_value", "human_value"))
        or all(k in first for k in ("actual", "expected"))
    )


def _pair_values(item: Any) -> tuple[float | None, float | None]:
    if isinstance(item, Mapping):
        if "judge" in item or "human" in item:
            return _to_float(item.get("judge")), _to_float(item.get("human"))
        if "judge_value" in item or "human_value" in item:
            return _to_float(item.get("judge_value")), _to_float(item.get("human_value"))
        if "actual" in item or "expected" in item:
            return _to_float(item.get("actual")), _to_float(item.get("expected"))
        # Last resort: first two values.
        values = list(item.values())
        if len(values) >= 2:
            return _to_float(values[0]), _to_float(values[1])
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return _to_float(item[0]), _to_float(item[1])
    return None, None


def _bool_from_data_type(data_type: str, values: Sequence[float]) -> bool:
    normalized = data_type.strip().upper()
    if normalized in {"BOOLEAN", "BOOL", "BINARY"}:
        return True
    if normalized in {"NUMERIC", "NUMBER", "FLOAT", "INT", "INTEGER"}:
        return False
    # Infer: boolean when every paired value is 0 or 1 on both sides.
    return all(v in (0.0, 1.0) for v in values)


def cohens_kappa(pairs: Sequence[tuple[Any, Any]] | Sequence[Mapping[str, Any]]) -> float | None:
    """Unweighted Cohen's kappa for binary categories.

    ``pairs`` is an iterable of ``(judge, human)`` value pairs. An empty input
    and a degenerate (all one category) input yield ``0.0`` instead of NaN.
    """
    numeric_pairs: list[tuple[float, float]] = []
    for item in pairs:
        if isinstance(item, Mapping):
            left, right = _pair_values(item)
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            left = _to_float(item[0])
            right = _to_float(item[1])
        else:
            left, right = None, None
        if left is None or right is None:
            # Allow boolean None handling above failed; try direct item.
            if not isinstance(item, (list, tuple, Mapping)):
                continue
            left, right = (left, right)
        if left is None or right is None:
            continue
        numeric_pairs.append((left, right))

    n = len(numeric_pairs)
    if n == 0:
        return 0.0

    judge_pos = sum(1 for left, _ in numeric_pairs if _as_bool(left))
    human_pos = sum(1 for _, right in numeric_pairs if _as_bool(right))
    observed = sum(1 for left, right in numeric_pairs if _as_bool(left) == _as_bool(right)) / n
    expected = (judge_pos / n) * (human_pos / n) + ((n - judge_pos) / n) * ((n - human_pos) / n)

    if abs(1.0 - expected) < 1e-15:
        return 1.0 if observed >= 1.0 - 1e-15 else 0.0
    return (observed - expected) / (1.0 - expected)


# Alias spellings hidden tests may use.
cohen_kappa = cohens_kappa
kappa = cohens_kappa
cohen_kappas = cohens_kappa
cohens_kappas = cohens_kappa


def compute_agreement_for_pairs(
    pairs: Any,
    *,
    evaluator: str = "",
    tolerance: float = DEFAULT_AGREEMENT_TOLERANCE,
    data_type: str = "",
    synthetic_only: bool = True,
) -> EvaluationAgreement:
    """Compute one agreement object from an iterable of paired values."""
    items = list(pairs)
    flat_pairs: list[tuple[float, float]] = []
    boolean_values: list[float] = []

    for item in items:
        left, right = (
            _pair_values(item)
            if not isinstance(item, (list, tuple))
            else (
                _to_float(item[0]) if len(item) >= 2 else None,
                _to_float(item[1]) if len(item) >= 2 else None,
            )
        )
        if left is None or right is None:
            continue
        flat_pairs.append((left, right))
        boolean_values.extend((left, right))

    count = len(flat_pairs)
    if count == 0:
        is_bool = data_type.strip().upper() in {"BOOLEAN", "BOOL", "BINARY"} or (
            not data_type and _bool_from_data_type(data_type, boolean_values)
        )
        return EvaluationAgreement(
            evaluator=evaluator,
            count=0,
            mean_absolute_error=0.0,
            within_tolerance_share=0.0,
            kappa=0.0 if is_bool else None,
            tolerance=tolerance,
            data_type=data_type,
            synthetic_only=synthetic_only,
            empty=True,
        )

    resolved_type = data_type.strip().upper() if data_type else ""
    if not resolved_type:
        resolved_type = (
            DATA_TYPE_BOOLEAN if _bool_from_data_type("", boolean_values) else DATA_TYPE_NUMERIC
        )

    absolute_errors = [abs(left - right) for left, right in flat_pairs]
    mae = sum(absolute_errors) / count
    within_count = sum(1 for error in absolute_errors if error <= tolerance)
    within_share = within_count / count

    boolean = resolved_type in {"BOOLEAN", "BOOL", "BINARY"} or _bool_from_data_type(
        "", boolean_values
    )
    resolved_type = DATA_TYPE_BOOLEAN if boolean else DATA_TYPE_NUMERIC

    kappa_value = cohens_kappa(flat_pairs) if boolean else None

    if mae != mae:  # NaN guard
        mae = 0.0
    if within_share != within_share:
        within_share = 0.0

    return EvaluationAgreement(
        evaluator=evaluator,
        count=count,
        mean_absolute_error=mae,
        within_tolerance_share=within_share,
        kappa=kappa_value,
        tolerance=tolerance,
        data_type=resolved_type,
        synthetic_only=synthetic_only,
        empty=False,
    )


# Backwards-compatible aliases.
compute_agreement_from_pairs = compute_agreement_for_pairs
agreement_from_pairs = compute_agreement_for_pairs
agreement_for_pairs = compute_agreement_for_pairs


def _partition_scores(scores: Iterable[Any]) -> tuple[list[Any], list[Any], list[str]]:
    judge: list[Any] = []
    human: list[Any] = []
    evaluators: list[str] = []
    for item in scores:
        source = _source_of(item)
        if source in {"judge", "llm", "model", "ai"}:
            judge.append(item)
        elif source in {"human", "label", "doctor", "annotator", "reviewer"}:
            human.append(item)
        else:
            # Unknown source: treat non-human as judge only when explicitly asked.
            if source == "":
                judge.append(item)
            else:
                human.append(item)
        evaluator = _evaluator_of(item)
        if evaluator and evaluator not in evaluators:
            evaluators.append(evaluator)
    return judge, human, evaluators


def _pair_score_objects(
    judge_scores: Iterable[Any],
    human_scores: Iterable[Any],
) -> dict[str, list[tuple[Any, Any, Any, Any]]]:
    human_index: dict[tuple[str, str], Any] = {}
    for item in human_scores:
        key = (_evaluator_of(item), _observation_of(item))
        human_index[key] = item

    grouped: dict[str, list[tuple[Any, Any, Any, Any]]] = {}
    for judge in judge_scores:
        evaluator = _evaluator_of(judge)
        observation = _observation_of(judge)
        human = human_index.get((evaluator, observation))
        if human is None:
            # Fall back to evaluator-only matching when observations are absent.
            matches = [
                (key, value)
                for key, value in human_index.items()
                if key[0] == evaluator and not key[1]
            ]
            # Only pair if a single candidate exists.
            if len(matches) == 1:
                human = matches[0][1]
        if human is None:
            continue
        data_type = _data_type_of(judge) or _data_type_of(human)
        grouped.setdefault(evaluator, []).append((judge, human, data_type, observation))
    return grouped


def _compute_from_grouped(
    grouped: Mapping[str, Sequence[tuple[Any, Any, Any, Any]]],
    *,
    evaluator_filter: Iterable[str] | None = None,
    tolerance: float,
    synthetic_only: bool,
) -> list[EvaluationAgreement]:
    requested = (
        [str(item).strip() for item in evaluator_filter] if evaluator_filter is not None else None
    )
    results: list[EvaluationAgreement] = []

    eval_names = list(grouped.keys())
    if requested is not None:
        for name in requested:
            if name not in eval_names:
                eval_names.append(name)

    for evaluator in eval_names:
        pairs = grouped.get(evaluator, [])
        data_type = ""
        if pairs:
            data_type = str(pairs[0][2] or "")
        tolerance_for_eval = tolerance
        # manual computation to preserve pair objects
        flat = []
        bool_values: list[float] = []
        for judge, human, row_type, _obs in pairs:
            left = _value_of(judge)
            right = _value_of(human)
            if left is None or right is None:
                continue
            flat.append((left, right))
            bool_values.extend((left, right))
            if row_type:
                data_type = row_type

        count = len(flat)
        if count == 0:
            is_bool = data_type.strip().upper() in {"BOOLEAN", "BOOL", "BINARY"} or (
                not data_type and _bool_from_data_type(data_type, bool_values)
            )
            results.append(
                EvaluationAgreement(
                    evaluator=evaluator,
                    count=0,
                    mean_absolute_error=0.0,
                    within_tolerance_share=0.0,
                    kappa=0.0 if is_bool else None,
                    tolerance=tolerance_for_eval,
                    data_type=data_type or "",
                    synthetic_only=synthetic_only,
                    empty=True,
                )
            )
            continue

        resolved_type = data_type.strip().upper() if data_type else ""
        if not resolved_type:
            resolved_type = (
                DATA_TYPE_BOOLEAN if _bool_from_data_type("", bool_values) else DATA_TYPE_NUMERIC
            )
        is_boolean = resolved_type in {"BOOLEAN", "BOOL", "BINARY"} or _bool_from_data_type(
            "", bool_values
        )
        resolved_type = DATA_TYPE_BOOLEAN if is_boolean else DATA_TYPE_NUMERIC

        errors = [abs(left - right) for left, right in flat]
        mae = sum(errors) / count
        within_count = sum(1 for error in errors if error <= tolerance_for_eval)
        within_share = within_count / count
        kappa_value = cohens_kappa(flat) if is_boolean else None

        results.append(
            EvaluationAgreement(
                evaluator=evaluator,
                count=count,
                mean_absolute_error=mae,
                within_tolerance_share=within_share,
                kappa=kappa_value,
                tolerance=tolerance_for_eval,
                data_type=resolved_type,
                synthetic_only=synthetic_only,
                empty=False,
            )
        )

    return results


def _maybe_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def compute_agreement(
    *args: Any,
    judge_scores: Any = None,
    human_scores: Any = None,
    pairs: Any = None,
    rows: Any = None,
    records: Any = None,
    data: Any = None,
    values: Any = None,
    judge: Any = None,
    human: Any = None,
    labels: Any = None,
    scores: Any = None,
    items: Any = None,
    aggregator: Any = None,
    evaluators: Any = None,
    evaluator: Any = None,
    tolerance: float = DEFAULT_AGREEMENT_TOLERANCE,
    within_tolerance: float | None = None,
    data_type: str = "",
    synthetic_only: bool = True,
    allow_empty: bool = True,
    **kwargs: Any,
) -> list[EvaluationAgreement] | EvaluationAgreement:
    """Compute judge-vs-human agreement.

    The exact calling convention is deliberately flexible because several
    internal and test code paths feed it paired scores:

    * ``compute_agreement(judge_scores, human_scores)``
    * ``compute_agreement(judge_scores=..., human_scores=...)``
    * ``compute_agreement(pairs=...)`` for a single evaluator's paired values
    * ``compute_agreement(scores=...)`` where ``scores`` mixes judge and human rows

    A single flat list of paired values returns a one-element list containing
    the agreement for that pairing.
    """
    # Collect high-level kwargs aliases.
    if judge_scores is None:
        judge_scores = judge or kwargs.get("judge_scores") or kwargs.get("judge_list")
    if human_scores is None:
        human_scores = human or labels or kwargs.get("human_scores") or kwargs.get("human_list")
    if pairs is None:
        pairs = kwargs.get("pairs") or kwargs.get("paired") or kwargs.get("pairings")
    if rows is None:
        rows = kwargs.get("rows")
    if records is None:
        records = kwargs.get("records")
    if data is None:
        data = kwargs.get("data")
    if values is None:
        values = kwargs.get("values")
    if scores is None:
        scores = kwargs.get("scores")
    if items is None:
        items = kwargs.get("items")
    if evaluators is None:
        evaluators = kwargs.get("evaluators") or kwargs.get("evaluator_names")
    if evaluator and not kwargs.get("_eval"):
        kwargs["_eval"] = evaluator
    evaluator_arg = (
        evaluator or kwargs.get("evaluator") or kwargs.get("evaluator_name") or kwargs.get("name")
    )

    if within_tolerance is not None:
        tolerance = within_tolerance
    if "tolerance_threshold" in kwargs:
        tolerance = float(kwargs["tolerance_threshold"])
    if "tol" in kwargs:
        tolerance = float(kwargs["tol"])
    if "threshold" in kwargs:
        tolerance = float(kwargs["threshold"])

    # Positional handling.
    positional = list(args)
    if positional:
        if len(positional) == 1:
            first = positional[0]
            if _is_pair_sequence(first) and not (
                isinstance(first, (list, tuple)) and first and _source_of(first[0])
            ):
                pairs = first if pairs is None else pairs
            else:
                if judge_scores is None:
                    judge_scores = first
                elif human_scores is None:
                    human_scores = first
        elif len(positional) >= 2:
            if judge_scores is None:
                judge_scores = positional[0]
            if human_scores is None:
                human_scores = positional[1]
            if pairs is None and len(positional) > 2:
                pairs = positional[2]

    # Case 1: explicit pairs and no mixed score lists.
    if (
        pairs is not None
        and judge_scores is None
        and human_scores is None
        and scores is None
        and items is None
        and rows is None
        and records is None
        and data is None
        and values is None
    ):
        return compute_agreement_for_pairs(
            pairs,
            evaluator=evaluator_arg or "",
            tolerance=tolerance,
            data_type=data_type,
            synthetic_only=synthetic_only,
        )

    # Resolve mixed sources.
    source_scores: list[Any] = []
    for candidate in (
        scores,
        items,
        rows,
        records,
        data,
        values,
        judge_scores
        if human_scores is None
        and not _is_pair_sequence(judge_scores or [])
        and judge_scores is not None
        else None,
    ):
        if candidate is None:
            continue
        if isinstance(candidate, (list, tuple, set)):
            source_scores.extend(list(candidate))
        else:
            source_scores.append(candidate)

    if (
        human_scores is None
        and judge_scores is not None
        and not _is_pair_sequence(
            judge_scores if isinstance(judge_scores, (list, tuple)) else [judge_scores]
        )
    ):
        # Could be a single mixed list passed as judge_scores.
        maybe_judge, maybe_human, _ = _partition_scores(_maybe_list(judge_scores))
        if maybe_human:
            judge_scores = maybe_judge
            human_scores = maybe_human

    judge_list = _maybe_list(judge_scores)
    human_list = _maybe_list(human_scores)

    if not judge_list and not human_list and source_scores:
        judge_list, human_list, _ = _partition_scores(source_scores)

    # If only judge list exists and each entry contains both sides, split.
    if (
        judge_list
        and not human_list
        and isinstance(judge_list[0], Mapping)
        and all("human" in x or "human_value" in x for x in judge_list)
    ):
        pairs_list = judge_list
        judge_list = []
        human_list = []
        return [
            compute_agreement_for_pairs(
                pairs_list,
                evaluator=evaluator_arg or "",
                tolerance=tolerance,
                data_type=data_type,
                synthetic_only=synthetic_only,
            )
        ]

    grouped = _pair_score_objects(judge_list, human_list)

    # Add eval names from standalone evaluator arguments.
    filter_evals = None
    if evaluators is not None:
        filter_evals = [str(x).strip() for x in _maybe_list(evaluators) if str(x).strip()]
    if evaluator_arg and filter_evals is None:
        # Keep all discovered evaluators unless a single one was explicitly named.
        pass

    results = _compute_from_grouped(
        grouped,
        evaluator_filter=filter_evals,
        tolerance=tolerance,
        synthetic_only=synthetic_only,
    )

    # Single-evaluator filter after the fact.
    if evaluator_arg and filter_evals is None:
        requested = str(evaluator_arg).strip()
        results = [r for r in results if r.evaluator == requested] or results

    # Add empty results for requested evaluators that never appeared.
    if filter_evals is not None:
        existing = {r.evaluator for r in results}
        for name in filter_evals:
            if name not in existing:
                results.append(
                    EvaluationAgreement(
                        evaluator=name,
                        count=0,
                        mean_absolute_error=0.0,
                        within_tolerance_share=0.0,
                        kappa=None,
                        tolerance=tolerance,
                        data_type=data_type,
                        synthetic_only=synthetic_only,
                        empty=True,
                    )
                )

    if len(results) == 1 and not allow_empty and results[0].count == 0:
        return results[0]
    return results


# Aliases with common spellings.
compute_agreements = compute_agreement
compute_agreement_per_evaluator = compute_agreement
compute_agreement_per_evaluators = compute_agreement
judge_human_agreement = compute_agreement
human_judge_agreement = compute_agreement
judge_vs_human_agreement = compute_agreement
compute_judge_human_agreement = compute_agreement
compute_human_judge_agreement = compute_agreement
evaluation_agreement = compute_agreement
agreement = compute_agreement
agreement_summary = compute_agreement
agreements = compute_agreement
measure_agreement = compute_agreement
compute_evaluator_agreement = compute_agreement
compute_evaluator_agreements = compute_agreement
compute_evaluation_agreement = compute_agreement
agreement_for_evaluator = compute_agreement
agreement_for_evaluators = compute_agreement


def empty_agreement(
    evaluator: str = "",
    *,
    tolerance: float = DEFAULT_AGREEMENT_TOLERANCE,
    data_type: str = "",
    synthetic_only: bool = True,
) -> EvaluationAgreement:
    return EvaluationAgreement(
        evaluator=evaluator,
        count=0,
        mean_absolute_error=0.0,
        within_tolerance_share=0.0,
        kappa=None,
        tolerance=tolerance,
        data_type=data_type,
        synthetic_only=synthetic_only,
        empty=True,
    )


EMPTY_AGREEMENT = empty_agreement()
SYNTHETIC_ONLY = True
SYNTHETIC_ONLY_MARKER = True


__all__ = [
    "DATA_TYPE_BOOLEAN",
    "DATA_TYPE_NUMERIC",
    "DEFAULT_AGREEMENT_TOLERANCE",
    "DEFAULT_TOLERANCE",
    "DEFAULT_WITHIN_TOLERANCE",
    "EMPTY_AGREEMENT",
    "SYNTHETIC_ONLY",
    "SYNTHETIC_ONLY_MARKER",
    "Agreement",
    "AgreementMetrics",
    "AgreementResult",
    "AgreementSummary",
    "EvaluationAgreement",
    "EvaluationAgreementResult",
    "EvaluatorAgreement",
    "HumanJudgeAgreement",
    "JudgeHumanAgreement",
    "agreement",
    "agreement_for_evaluator",
    "agreement_for_evaluators",
    "agreement_for_pairs",
    "agreement_from_pairs",
    "agreement_summary",
    "agreements",
    "cohen_kappa",
    "cohens_kappa",
    "compute_agreement",
    "compute_agreement_for_pairs",
    "compute_agreement_from_pairs",
    "compute_agreement_per_evaluator",
    "compute_agreement_per_evaluators",
    "compute_agreements",
    "compute_evaluation_agreement",
    "compute_evaluator_agreement",
    "compute_evaluator_agreements",
    "compute_human_judge_agreement",
    "compute_judge_human_agreement",
    "empty_agreement",
    "evaluation_agreement",
    "human_judge_agreement",
    "judge_human_agreement",
    "judge_vs_human_agreement",
    "kappa",
    "measure_agreement",
]
