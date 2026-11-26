"""Tests for evaluation dataset validation (PHI patterns, oversized text, malformed examples)."""

from __future__ import annotations

from modules.observability.domain.dataset_validation import (
    ValidationError,
    validate_example,
    validate_examples,
)
from modules.observability.facade import EvaluationDatasetExample


def _valid_example(
    *,
    example_ref: str = "test-1",
    task_type: str = "transcription",
    input_data: dict | None = None,
    expected_output: dict | None = None,
    tags: list[str] | None = None,
) -> EvaluationDatasetExample:
    return EvaluationDatasetExample(
        example_ref=example_ref,
        task_type=task_type,
        input=input_data or {"text": "patient says hello"},
        expected_output=expected_output or {"result": "hello"},
        tags=tags or [],
    )


def _construct_example(**kwargs) -> EvaluationDatasetExample:
    """Construct an EvaluationDatasetExample bypassing Pydantic validation."""
    return EvaluationDatasetExample.model_construct(**kwargs)


class TestValidateExample:
    """Tests for single example validation."""

    def test_valid_example_passes(self) -> None:
        example = _valid_example()
        errors = validate_example(example)
        assert errors == []

    def test_missing_example_ref_fails(self) -> None:
        example = _construct_example(
            example_ref="",
            task_type="transcription",
            input={"text": "hello"},
            expected_output={"result": "hi"},
            tags=[],
        )
        errors = validate_example(example)
        assert any(e.field == "example_ref" and "required" in e.message for e in errors)

    def test_none_example_ref_fails(self) -> None:
        example = _construct_example(
            example_ref=None,  # type: ignore[arg-type]
            task_type="transcription",
            input={"text": "hello"},
            expected_output={"result": "hi"},
            tags=[],
        )
        errors = validate_example(example)
        assert any(e.field == "example_ref" and "required" in e.message for e in errors)

    def test_example_ref_too_long_fails(self) -> None:
        example = _valid_example(example_ref="x" * 65)
        errors = validate_example(example)
        assert any(
            e.field == "example_ref" and "exceeds maximum length" in e.message for e in errors
        )

    def test_missing_task_type_fails(self) -> None:
        example = _construct_example(
            example_ref="test-1",
            task_type="",
            input={"text": "hello"},
            expected_output={"result": "hi"},
            tags=[],
        )
        errors = validate_example(example)
        assert any(e.field == "task_type" and "required" in e.message for e in errors)

    def test_task_type_too_long_fails(self) -> None:
        example = _valid_example(task_type="x" * 31)
        errors = validate_example(example)
        assert any(e.field == "task_type" and "exceeds maximum length" in e.message for e in errors)

    def test_missing_input_fails(self) -> None:
        example = _construct_example(
            example_ref="test-1",
            task_type="transcription",
            input=None,  # type: ignore[arg-type]
            expected_output={"result": "hi"},
            tags=[],
        )
        errors = validate_example(example)
        assert any(e.field == "input" and "required" in e.message for e in errors)

    def test_input_not_dict_fails(self) -> None:
        example = _construct_example(
            example_ref="test-1",
            task_type="transcription",
            input="not a dict",  # type: ignore[arg-type]
            expected_output={"result": "hi"},
            tags=[],
        )
        errors = validate_example(example)
        assert any(e.field == "input" and "must be an object" in e.message for e in errors)

    def test_missing_expected_output_fails(self) -> None:
        example = _construct_example(
            example_ref="test-1",
            task_type="transcription",
            input={"text": "hello"},
            expected_output=None,  # type: ignore[arg-type]
            tags=[],
        )
        errors = validate_example(example)
        assert any(e.field == "expected_output" and "required" in e.message for e in errors)

    def test_expected_output_not_dict_fails(self) -> None:
        example = _construct_example(
            example_ref="test-1",
            task_type="transcription",
            input={"text": "hello"},
            expected_output="not a dict",  # type: ignore[arg-type]
            tags=[],
        )
        errors = validate_example(example)
        assert any(
            e.field == "expected_output" and "must be an object" in e.message for e in errors
        )

    def test_tags_not_list_fails(self) -> None:
        example = _construct_example(
            example_ref="test-1",
            task_type="transcription",
            input={"text": "hello"},
            expected_output={"result": "hi"},
            tags="not a list",  # type: ignore[arg-type]
        )
        errors = validate_example(example)
        assert any(e.field == "tags" and "must be a list" in e.message for e in errors)

    def test_tags_not_all_strings_fails(self) -> None:
        example = _construct_example(
            example_ref="test-1",
            task_type="transcription",
            input={"text": "hello"},
            expected_output={"result": "hi"},
            tags=["valid", 123],  # type: ignore[arg-type]
        )
        errors = validate_example(example)
        assert any(e.field == "tags" and "must be strings" in e.message for e in errors)

    def test_tags_total_length_exceeded_fails(self) -> None:
        example = _valid_example(tags=["x" * 500, "y" * 600])
        errors = validate_example(example)
        assert any(e.field == "tags" and "exceeds" in e.message for e in errors)


class TestOversizedTextRejection:
    """Tests for oversized text rejection."""

    def test_input_string_too_long_fails(self) -> None:
        example = _valid_example(input_data={"text": "x" * 10001})
        errors = validate_example(example)
        assert any(
            e.field == "input.text" and "exceeds maximum length" in e.message for e in errors
        )

    def test_expected_output_string_too_long_fails(self) -> None:
        example = _valid_example(expected_output={"result": "x" * 10001})
        errors = validate_example(example)
        assert any(
            e.field == "expected_output.result" and "exceeds maximum length" in e.message
            for e in errors
        )

    def test_nested_string_too_long_fails(self) -> None:
        example = _valid_example(input_data={"nested": {"deep": {"text": "x" * 10001}}})
        errors = validate_example(example)
        assert any(
            e.field == "input.nested.deep.text" and "exceeds maximum length" in e.message
            for e in errors
        )

    def test_total_example_size_exceeded_fails(self) -> None:
        # Create example with many large strings that sum > 50000
        large_text = "x" * 15000
        example = _valid_example(
            input_data={"a": large_text, "b": large_text, "c": large_text},
            expected_output={"x": large_text},
        )
        errors = validate_example(example)
        assert any(
            e.field == "example" and "total example size exceeds" in e.message for e in errors
        )


class TestPHIPatternRejection:
    """Tests for PHI pattern rejection."""

    def test_phone_number_in_input_rejected(self) -> None:
        example = _valid_example(input_data={"phone": "Call me at 9876543210"})
        errors = validate_example(example)
        assert any(e.field == "input.phone" and "phone_number" in e.message for e in errors)

    def test_phone_number_with_country_code_rejected(self) -> None:
        example = _valid_example(input_data={"phone": "Call me at +91 98765 43210"})
        errors = validate_example(example)
        assert any(e.field == "input.phone" and "phone_number" in e.message for e in errors)

    def test_phone_number_with_zero_prefix_rejected(self) -> None:
        example = _valid_example(input_data={"phone": "Call me at 0 98765 43210"})
        errors = validate_example(example)
        assert any(e.field == "input.phone" and "phone_number" in e.message for e in errors)

    def test_email_in_input_rejected(self) -> None:
        example = _valid_example(input_data={"contact": "Email me at user@example.com"})
        errors = validate_example(example)
        assert any(e.field == "input.contact" and "email_address" in e.message for e in errors)

    def test_aadhaar_number_rejected(self) -> None:
        example = _valid_example(input_data={"id": "Aadhaar: 1234 5678 9012"})
        errors = validate_example(example)
        assert any(e.field == "input.id" and "aadhaar_number" in e.message for e in errors)

    def test_aadhaar_number_no_spaces_rejected(self) -> None:
        example = _valid_example(input_data={"id": "123456789012"})
        errors = validate_example(example)
        assert any(e.field == "input.id" and "aadhaar_number" in e.message for e in errors)

    def test_pan_number_rejected(self) -> None:
        example = _valid_example(input_data={"id": "PAN: ABCDE1234F"})
        errors = validate_example(example)
        assert any(e.field == "input.id" and "pan_number" in e.message for e in errors)

    def test_passport_number_rejected(self) -> None:
        example = _valid_example(input_data={"id": "Passport: Z1234567"})
        errors = validate_example(example)
        assert any(e.field == "input.id" and "passport_number" in e.message for e in errors)

    def test_driving_license_rejected(self) -> None:
        example = _valid_example(input_data={"id": "DL: MH 12 34567890123"})
        errors = validate_example(example)
        assert any(e.field == "input.id" and "driving_license" in e.message for e in errors)

    def test_phi_in_expected_output_rejected(self) -> None:
        example = _valid_example(expected_output={"phone": "9876543210"})
        errors = validate_example(example)
        assert any(
            e.field == "expected_output.phone" and "phone_number" in e.message for e in errors
        )

    def test_phi_in_tags_rejected(self) -> None:
        example = _valid_example(tags=["patient-9876543210", "normal-tag"])
        errors = validate_example(example)
        assert any(e.field == "tags" and "phone_number" in e.message for e in errors)

    def test_multiple_phi_patterns_reported(self) -> None:
        example = _valid_example(input_data={"text": "Call 9876543210 or email user@example.com"})
        errors = validate_example(example)
        phi_errors = [e for e in errors if "PHI" in e.message]
        assert len(phi_errors) >= 1
        # Should detect both phone and email
        messages = " ".join(e.message for e in phi_errors)
        assert "phone_number" in messages
        assert "email_address" in messages


class TestValidateExamples:
    """Tests for batch validation."""

    def test_duplicate_example_ref_fails(self) -> None:
        ex1 = _valid_example(example_ref="dup")
        ex2 = _valid_example(example_ref="dup")
        errors = validate_examples([ex1, ex2])
        assert any(e.field == "example_ref" and "duplicate" in e.message for e in errors)

    def test_valid_batch_passes(self) -> None:
        ex1 = _valid_example(example_ref="test-1")
        ex2 = _valid_example(example_ref="test-2")
        errors = validate_examples([ex1, ex2])
        assert errors == []

    def test_mixed_valid_and_invalid(self) -> None:
        ex1 = _valid_example(example_ref="valid")
        ex2 = _valid_example(example_ref="invalid", input_data={"phone": "9876543210"})
        errors = validate_examples([ex1, ex2])
        # Should have errors only for the invalid one
        assert any(e.example_ref == "invalid" for e in errors)
        assert not any(e.example_ref == "valid" for e in errors)


class TestValidationErrorStructure:
    """Tests for ValidationError dataclass."""

    def test_error_has_field_message_and_example_ref(self) -> None:
        example = _valid_example(example_ref="test-1", input_data={"phone": "9876543210"})
        errors = validate_example(example)
        assert len(errors) == 1
        error = errors[0]
        assert isinstance(error, ValidationError)
        assert error.field == "input.phone"
        assert "phone_number" in error.message
        assert error.example_ref == "test-1"
