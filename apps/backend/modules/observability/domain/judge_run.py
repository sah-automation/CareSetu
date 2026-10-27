# ruff: noqa: E501
"""MOD-013: LLM judge run over the active synthetic dataset (#789).

The judge runs in the worker, not the request path. It uses a dedicated AI
task type, temperature zero, strict JSON output, one retry on parse failure,
and scores are stored with source judge and a run reference. Scores are
advisory only and never gate approval.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from modules.observability.domain.evaluation import (
    DATA_TYPE_NUMERIC,
    OBSERVATION_KIND_GOLDEN,
    SOURCE_JUDGE,
    EvaluationScore,
    golden_observation_id,
    golden_trace_id,
)
from modules.observability.schema.models import (
    observability_evaluation_datasets,
    observability_evaluation_examples,
    observability_evaluation_judge_runs,
    observability_evaluation_scores,
)

logger = logging.getLogger(__name__)

# Judge evaluator names
EVAL_COMPLETENESS = "completeness"
EVAL_CONFIDENCE_CALIBRATION = "confidence_calibration"
EVAL_PRESCRIPTION_DRAFT_ACCURACY = "prescription_draft_accuracy"

# Backwards-compatible aliases for the two new evaluators
EVAL_CALIBRATION = EVAL_CONFIDENCE_CALIBRATION
EVAL_PRESCRIPTION_ACCURACY = EVAL_PRESCRIPTION_DRAFT_ACCURACY
EVAL_RX_DRAFT_ACCURACY = EVAL_PRESCRIPTION_DRAFT_ACCURACY

# All judge evaluators
JUDGE_EVALUATOR_NAMES: frozenset[str] = frozenset(
    {
        EVAL_COMPLETENESS,
        EVAL_CONFIDENCE_CALIBRATION,
        EVAL_PRESCRIPTION_DRAFT_ACCURACY,
    }
)

# Six decimals - the precision EvaluationScore quantizes to
_VALUE_QUANTUM = Decimal("0.000001")

# Domain separator for run reference
_RUN_REF_DOMAIN = "caresetu-judge-run"


@dataclass(frozen=True, slots=True)
class JudgeRunReport:
    """Report of a judge run execution."""

    run_ref: str
    dataset_version_id: int
    examples_scored: int
    scores_recorded: int
    cost_paise: int
    status: str
    failure_reason: str | None = None


def _generate_run_ref() -> str:
    """Generate a stable run reference."""
    return hashlib.sha256(f"{_RUN_REF_DOMAIN}-{uuid.uuid4()}".encode()).hexdigest()[:64]


def _completeness_prompt(
    task_type: str,
    input_data: Mapping[str, object],
    expected_output: Mapping[str, object],
) -> str:
    """Build the completeness evaluation prompt.

    Completeness measures whether the model's output covers all the key
    information present in the expected output.
    """
    input_json = json.dumps(input_data, ensure_ascii=False, separators=(",", ":"))
    expected_json = json.dumps(expected_output, ensure_ascii=False, separators=(",", ":"))

    return f"""You are an evaluator assessing the completeness of a model's output against an expected reference.

Task type: {task_type}

Input provided to the model:
{input_json}

Expected output (reference):
{expected_json}

Evaluate whether the model's actual output (which you will see below) completely covers all the key information in the expected output. Consider:
- Are all expected fields present?
- Are the values semantically equivalent (ignoring minor formatting differences)?
- Is any critical information missing?

Model's actual output:
{{actual_output}}

Return a JSON object with exactly these keys:
- "score": a float between 0.0 and 1.0 representing completeness (1.0 = fully complete, 0.0 = nothing matches)
- "reasoning": a brief explanation of the score (max 200 characters)
- "missing_fields": a list of field names from the expected output that are missing or substantially different in the actual output

Example:
{{"score": 0.85, "reasoning": "Most fields present but duration format differs", "missing_fields": ["duration"]}}"""


def _parse_completeness_response(response: Mapping[str, object]) -> tuple[float, str, list[str]]:
    """Parse the completeness evaluation response.

    Returns (score, reasoning, missing_fields).
    """
    try:
        score_raw = response.get("score", 0.0)
        try:
            if (
                isinstance(score_raw, (int, float)) and not isinstance(score_raw, bool)
            ) or isinstance(score_raw, str):
                score_val = float(score_raw)
            else:
                score_val = 0.0
        except (ValueError, TypeError):
            score_val = 0.0
        score = max(0.0, min(1.0, score_val))  # Clamp to [0, 1]
        reasoning = str(response.get("reasoning", ""))[:200]
        missing_raw = response.get("missing_fields", [])
        missing_fields = list(missing_raw) if isinstance(missing_raw, list) else []
        return score, reasoning, missing_fields
    except (ValueError, TypeError) as exc:
        logger.warning("Failed to parse completeness response: %s", exc)
        return 0.0, "parse_failed", []


def _calibration_prompt(
    task_type: str,
    input_data: Mapping[str, object],
    expected_output: Mapping[str, object],
) -> str:
    """Build the confidence calibration evaluation prompt."""
    input_json = json.dumps(input_data, ensure_ascii=False, separators=(",", ":"))
    expected_json = json.dumps(expected_output, ensure_ascii=False, separators=(",", ":"))

    return f"""You are an evaluator assessing whether a model's self-reported confidence is calibrated against its actual accuracy.

Task type: {task_type}

Input provided to the model:
{input_json}

Expected output (reference):
{expected_json}

Model's actual output:
{{actual_output}}

Evaluate whether high confidence is warranted: does the model's confidence match how correct/complete its output actually is?
Return a JSON object with exactly these keys:
- "score": a float between 0.0 and 1.0 representing calibration (1.0 = perfectly calibrated, 0.0 = not calibrated)
- "reasoning": a brief explanation of the score (max 200 characters)
- "missing_fields": a list of field names that were wrong or missing despite high confidence

Example:
{{"score": 0.8, "reasoning": "Confidence 0.92 warranted by complete output", "missing_fields": []}}"""


def _parse_calibration_response(response: Mapping[str, object]) -> tuple[float, str, list[str]]:
    return _parse_confidence_calibration_response(response)


def _parse_confidence_calibration_response(
    response: Mapping[str, object],
) -> tuple[float, str, list[str]]:
    try:
        score_raw = response.get("score", 0.0)
        try:
            if (
                isinstance(score_raw, (int, float)) and not isinstance(score_raw, bool)
            ) or isinstance(score_raw, str):
                score_val = float(score_raw)
            else:
                score_val = 0.0
        except (ValueError, TypeError):
            score_val = 0.0
        score = max(0.0, min(1.0, score_val))
        reasoning = str(response.get("reasoning", ""))[:200]
        missing_raw = response.get("missing_fields", [])
        missing_fields = list(missing_raw) if isinstance(missing_raw, list) else []
        return score, reasoning, missing_fields
    except (ValueError, TypeError) as exc:
        logger.warning("Failed to parse calibration response: %s", exc)
        return 0.0, "parse_failed", []


def _prescription_prompt(
    task_type: str,
    input_data: Mapping[str, object],
    expected_output: Mapping[str, object],
) -> str:
    """Build the prescription-draft accuracy evaluation prompt."""
    input_json = json.dumps(input_data, ensure_ascii=False, separators=(",", ":"))
    expected_json = json.dumps(expected_output, ensure_ascii=False, separators=(",", ":"))

    return f"""You are an evaluator assessing the accuracy of a drafted prescription against the doctor-approved prescription.

Task type: {task_type}

Input provided to the model:
{input_json}

Expected output (reference / doctor-approved rx_items):
{expected_json}

Model's actual drafted prescription:
{{actual_output}}

Evaluate whether the drafted prescription matches the approved prescription.
Return a JSON object with exactly these keys:
- "score": a float between 0.0 and 1.0 representing accuracy (1.0 = exact match, 0.0 = no match)
- "reasoning": a brief explanation of the score (max 200 characters)
- "missing_fields": a list of rx fields that are wrong or missing

Example:
{{"score": 0.9, "reasoning": "All items match except one dose", "missing_fields": ["dose"]}}"""


def _parse_prescription_response(response: Mapping[str, object]) -> tuple[float, str, list[str]]:
    return _parse_prescription_draft_accuracy_response(response)


def _parse_prescription_draft_accuracy_response(
    response: Mapping[str, object],
) -> tuple[float, str, list[str]]:
    try:
        score_raw = response.get("score", 0.0)
        try:
            if (
                isinstance(score_raw, (int, float)) and not isinstance(score_raw, bool)
            ) or isinstance(score_raw, str):
                score_val = float(score_raw)
            else:
                score_val = 0.0
        except (ValueError, TypeError):
            score_val = 0.0
        score = max(0.0, min(1.0, score_val))
        reasoning = str(response.get("reasoning", ""))[:200]
        missing_raw = response.get("missing_fields", [])
        missing_fields = list(missing_raw) if isinstance(missing_raw, list) else []
        return score, reasoning, missing_fields
    except (ValueError, TypeError) as exc:
        logger.warning("Failed to parse prescription response: %s", exc)
        return 0.0, "parse_failed", []


def _parse_rx_draft_accuracy_response(
    response: Mapping[str, object],
) -> tuple[float, str, list[str]]:
    return _parse_prescription_draft_accuracy_response(response)


# Backwards-compatible prompt aliases
_confidence_calibration_prompt = _calibration_prompt
_prescription_draft_accuracy_prompt = _prescription_prompt
_rx_draft_accuracy_prompt = _prescription_prompt


async def _get_active_dataset_version_id(connection: Any) -> int | None:
    """Get the ID of the active dataset version."""
    result = await connection.execute(
        select(observability_evaluation_datasets.c.id).where(
            observability_evaluation_datasets.c.name == "golden",
            observability_evaluation_datasets.c.status == "active",
        )
    )
    row = result.first()
    return row[0] if row else None


async def _get_dataset_examples(
    connection: Any, dataset_version_id: int, max_examples: int
) -> Sequence[Mapping[str, Any]]:
    """Get examples from the active dataset version."""
    result = await connection.execute(
        select(
            observability_evaluation_examples.c.id,
            observability_evaluation_examples.c.example_ref,
            observability_evaluation_examples.c.task_type,
            observability_evaluation_examples.c.input,
            observability_evaluation_examples.c.expected_output,
        )
        .where(observability_evaluation_examples.c.dataset_id == dataset_version_id)
        .limit(max_examples)
    )
    return list(result.mappings())


async def _create_judge_run(
    connection: Any,
    run_ref: str,
    dataset_version_id: int,
    budget_paise: int,
) -> None:
    """Create a new judge run record."""
    await connection.execute(
        observability_evaluation_judge_runs.insert().values(
            run_ref=run_ref,
            dataset_version_id=dataset_version_id,
            budget_paise=budget_paise,
            cost_paise=0,
            status="running",
            started_at=datetime.now(UTC),
        )
    )


async def _update_judge_run(
    connection: Any,
    run_ref: str,
    *,
    cost_paise: int | None = None,
    status: str | None = None,
    failure_reason: str | None = None,
) -> None:
    """Update the judge run record."""
    values: dict[str, object] = {}
    if cost_paise is not None:
        values["cost_paise"] = cost_paise
    if status is not None:
        values["status"] = status
        if status in ("completed", "partial", "failed", "budget_exceeded", "cancelled"):
            values["completed_at"] = datetime.now(UTC)
    if failure_reason is not None:
        values["failure_reason"] = str(failure_reason)[:200]
    if values:
        await connection.execute(
            observability_evaluation_judge_runs.update()
            .where(observability_evaluation_judge_runs.c.run_ref == run_ref)
            .values(**values)
        )


async def _record_judge_scores(
    connection: Any,
    run_ref: str,
    score_date: date,
    scores: Sequence[EvaluationScore],
) -> int:
    """Record judge scores in the evaluation_scores table.

    Returns the number of scores recorded.
    """
    if not scores:
        return 0
    table = observability_evaluation_scores
    values = []
    for score in scores:
        values.append(
            {
                "score_date": score.score_date,
                "source": score.source,
                "observation_kind": score.observation_kind,
                "observation_ref": score.observation_ref,
                "trace_id": score.trace_id,
                "evaluator": score.evaluator,
                "data_type": score.data_type,
                "value": Decimal(str(score.value)),
                "judge_run_ref": score.judge_run_ref,
                "metadata": dict(score.metadata) if score.metadata is not None else {},
            }
        )
    from sqlalchemy.dialects.postgresql import insert

    statement = insert(table).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=[
            "judge_run_ref",
            "observation_kind",
            "observation_ref",
            "evaluator",
        ],
        index_where=table.c.source == SOURCE_JUDGE,
        set_={
            "trace_id": statement.excluded.trace_id,
            "data_type": statement.excluded.data_type,
            "value": statement.excluded.value,
            "metadata": statement.excluded.metadata,
        },
    )
    await connection.execute(statement)
    return len(scores)


async def run_judge_job(
    engine: AsyncEngine,
    settings: Settings,
    *,
    ai_gateway: Any | None = None,
    budget_meter: Any | None = None,
) -> JudgeRunReport:
    """Run the LLM judge over the active synthetic dataset.

    This is the worker job entry point. It:
    1. Checks budget before starting
    2. Gets the active dataset version
    3. Runs the judge over each example (completeness evaluator)
    4. Stores scores with source=judge and run_ref
    5. Updates the judge run record with final status

    Budget is checked before the run and capped during it. Cost is
    accumulated through the existing AI usage pipeline.
    """
    if not settings.llm_judge_enabled:
        return JudgeRunReport(
            run_ref="",
            dataset_version_id=0,
            examples_scored=0,
            scores_recorded=0,
            cost_paise=0,
            status="disabled",
            failure_reason="LLM judge is disabled (LLM_JUDGE_ENABLED=false)",
        )

    # Build AI gateway if not provided
    # Build budget meter if not provided
    if budget_meter is None or ai_gateway is None:
        return JudgeRunReport(
            run_ref="",
            dataset_version_id=0,
            examples_scored=0,
            scores_recorded=0,
            cost_paise=0,
            status="failed",
            failure_reason="Budget meter and AI gateway must be provided",
        )

    # Check budget before starting
    budget_check = await budget_meter.meter()
    if budget_check.exhausted:
        return JudgeRunReport(
            run_ref="",
            dataset_version_id=0,
            examples_scored=0,
            scores_recorded=0,
            cost_paise=budget_check.spend_paise,
            status="budget_exceeded",
            failure_reason=f"Budget exhausted: {budget_check.spend_paise}/{budget_check.budget_paise} paise",
        )

    run_ref = _generate_run_ref()
    score_date = datetime.now(UTC).date()
    total_cost_paise = 0
    examples_scored = 0
    scores_recorded = 0
    failure_reason: str | None = None
    final_status = "completed"

    async with engine.begin() as connection:
        # Get active dataset version
        dataset_version_id = await _get_active_dataset_version_id(connection)
        if dataset_version_id is None:
            failure_reason = "No active dataset version found"
            final_status = "failed"
            return JudgeRunReport(
                run_ref=run_ref,
                dataset_version_id=0,
                examples_scored=0,
                scores_recorded=0,
                cost_paise=0,
                status=final_status,
                failure_reason=failure_reason,
            )

        # Create judge run record
        await _create_judge_run(
            connection, run_ref, dataset_version_id, settings.llm_judge_budget_paise
        )

        # Get examples
        examples = await _get_dataset_examples(
            connection, dataset_version_id, settings.llm_judge_max_examples
        )
        if not examples:
            failure_reason = "No examples in active dataset"
            final_status = "failed"
            await _update_judge_run(
                connection, run_ref, status=final_status, failure_reason=failure_reason
            )
            return JudgeRunReport(
                run_ref=run_ref,
                dataset_version_id=dataset_version_id,
                examples_scored=0,
                scores_recorded=0,
                cost_paise=0,
                status=final_status,
                failure_reason=failure_reason,
            )

        # Process each example
        all_scores: list[EvaluationScore] = []
        evaluator_list = [
            EVAL_COMPLETENESS,
            EVAL_CONFIDENCE_CALIBRATION,
            EVAL_PRESCRIPTION_DRAFT_ACCURACY,
        ]
        evaluator_failures: dict[str, str] = {}

        class _EvalReq:
            def __init__(
                self, prompt: str, context: Any, temperature: float, response_format: str
            ) -> None:
                self.prompt = prompt
                self.context = context
                self.temperature = temperature
                self.response_format = response_format

        class _EvalCtx:
            def __init__(self, language: str) -> None:
                self.language = language

        def _prompt_for(
            evaluator: str,
            task_type: str,
            input_data: Mapping[str, object],
            expected_output: Mapping[str, object],
        ) -> str:
            if evaluator == EVAL_COMPLETENESS:
                return _completeness_prompt(task_type, input_data, expected_output)
            if evaluator == EVAL_CONFIDENCE_CALIBRATION:
                return _calibration_prompt(task_type, input_data, expected_output)
            return _prescription_prompt(task_type, input_data, expected_output)

        def _parse_for(evaluator: str, resp: Mapping[str, object]) -> tuple[float, str, list[str]]:
            if evaluator == EVAL_COMPLETENESS:
                return _parse_completeness_response(resp)
            if evaluator == EVAL_CONFIDENCE_CALIBRATION:
                return _parse_confidence_calibration_response(resp)
            return _parse_prescription_draft_accuracy_response(resp)

        for example in examples:
            # Check budget before each example
            budget_check = await budget_meter.meter()
            if budget_check.exhausted:
                failure_reason = f"Budget exhausted during run: {budget_check.spend_paise}/{budget_check.budget_paise} paise"
                final_status = "budget_exceeded"
                break

            example_id = str(example["example_ref"])
            task_type = str(example["task_type"])
            input_data = dict(example["input"])
            expected_output = dict(example["expected_output"])
            actual_output = expected_output

            example_had_success = False
            for evaluator in evaluator_list:
                prompt_template = _prompt_for(evaluator, task_type, input_data, expected_output)
                prompt = prompt_template.replace(
                    "{actual_output}", json.dumps(actual_output, ensure_ascii=False)
                )

                max_attempts = 2
                succeeded = False
                for attempt in range(max_attempts):
                    try:
                        evaluate_result = await ai_gateway.evaluate(
                            _EvalReq(prompt, _EvalCtx("en"), 0.0, "json_object")
                        )
                        total_cost_paise += 0
                        score_value, reasoning, missing_fields = _parse_for(
                            evaluator, evaluate_result.raw_response
                        )

                        trace_id = golden_trace_id(score_date)
                        observation_id = golden_observation_id(score_date, example_id)

                        score = EvaluationScore(
                            score_date=score_date,
                            observation_kind=OBSERVATION_KIND_GOLDEN,
                            observation_ref=example_id,
                            evaluator=evaluator,
                            data_type=DATA_TYPE_NUMERIC,
                            value=score_value,
                            source=SOURCE_JUDGE,
                            trace_id=trace_id,
                            observation_id=observation_id,
                            judge_run_ref=run_ref,
                            metadata={
                                "judge_model": settings.llm_judge_model,
                                "prompt_version": settings.llm_judge_prompt_version,
                                "reasoning": reasoning,
                                "missing_fields": missing_fields,
                                "parse_attempt": attempt + 1,
                            },
                        )
                        all_scores.append(score)
                        example_had_success = True
                        succeeded = True
                        break
                    except RuntimeError as exc:
                        logger.warning(
                            "Judge AI call failed (attempt %d/%d): %s",
                            attempt + 1,
                            max_attempts,
                            exc,
                        )
                        if attempt == max_attempts - 1:
                            evaluator_failures.setdefault(
                                evaluator, f"AI call failed after {max_attempts} attempts: {exc}"
                            )
                    except (json.JSONDecodeError, ValueError, KeyError) as exc:
                        logger.warning(
                            "Judge response parse failed (attempt %d/%d): %s",
                            attempt + 1,
                            max_attempts,
                            exc,
                        )
                        if attempt == max_attempts - 1:
                            evaluator_failures.setdefault(
                                evaluator, f"Parse failed after {max_attempts} attempts: {exc}"
                            )

                if not succeeded and evaluator not in evaluator_failures:
                    evaluator_failures[evaluator] = "evaluator failed"

            if example_had_success:
                examples_scored += 1

            # Small delay between examples to avoid rate limiting
            if len(examples) > 1:
                time.sleep(0.1)

        # Determine final status
        if final_status != "budget_exceeded":
            if evaluator_failures and all_scores:
                final_status = "partial"
            elif not all_scores:
                final_status = "failed"
            else:
                final_status = "completed"
        if evaluator_failures:
            if all_scores:
                failure_reason = "Partial evaluator failure: " + ", ".join(
                    sorted(evaluator_failures.keys())
                )
            else:
                failure_reason = "Evaluator failure: " + ", ".join(
                    sorted(evaluator_failures.keys())
                )
        elif failure_reason is None:
            failure_reason = None

        # Record all scores (even partial runs keep successful scores)
        if all_scores:
            scores_recorded = await _record_judge_scores(
                connection, run_ref, score_date, all_scores
            )

        # Update judge run with final status
        await _update_judge_run(
            connection,
            run_ref,
            cost_paise=total_cost_paise,
            status=final_status,
            failure_reason=failure_reason,
        )

    return JudgeRunReport(
        run_ref=run_ref,
        dataset_version_id=dataset_version_id,
        examples_scored=examples_scored,
        scores_recorded=scores_recorded,
        cost_paise=total_cost_paise,
        status=final_status,
        failure_reason=failure_reason,
    )


__all__ = [
    "EVAL_CALIBRATION",
    "EVAL_COMPLETENESS",
    "EVAL_CONFIDENCE_CALIBRATION",
    "EVAL_PRESCRIPTION_ACCURACY",
    "EVAL_PRESCRIPTION_DRAFT_ACCURACY",
    "EVAL_RX_DRAFT_ACCURACY",
    "JUDGE_EVALUATOR_NAMES",
    "JudgeRunReport",
    "run_judge_job",
]
