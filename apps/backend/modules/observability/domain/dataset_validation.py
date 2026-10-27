"""Dataset validation for evaluation datasets.

Validates synthetic examples on create and edit:
- Rejects malformed examples
- Rejects oversized text
- Rejects obvious PHI patterns (phone, email, government identifiers)
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True)
class ValidationError:
    """A single validation error."""

    field: str
    message: str
    example_ref: str | None = None


# PHI patterns - phone numbers (Indian format), emails, government IDs
# Matches: 9876543210, +91 98765 43210, +919876543210, 0 98765 43210, 09876543210
_PHONE_PATTERN = re.compile(
    r"(?:\+?91[\s-]?|0[\s-]?)"
    r"(?:[6-9]\d[\s-]?\d{3}[\s-]?\d{4}|[6-9]\d{9})"
    r"|(?:\+?91[\s-]?|0[\s-]?)?[6-9]\d{9}"
)
_EMAIL_PATTERN = re.compile(r"\S+@\S+\.\S+")
# Aadhaar: 12 digits, optionally spaced/grouped
_AADHAAR_PATTERN = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
# PAN: 5 letters, 4 digits, 1 letter
_PAN_PATTERN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
# Passport: 1 letter + 7 digits (Indian passport format)
_PASSPORT_PATTERN = re.compile(r"\b[A-Z]\d{7}\b")
# Driving license: various state formats, typically 2 letters + digits
_DL_PATTERN = re.compile(r"\b[A-Z]{2}[\s-]?\d{2}[\s-]?\d{11}\b")

_PHI_PATTERNS = (
    (_PHONE_PATTERN, "phone_number"),
    (_EMAIL_PATTERN, "email_address"),
    (_AADHAAR_PATTERN, "aadhaar_number"),
    (_PAN_PATTERN, "pan_number"),
    (_PASSPORT_PATTERN, "passport_number"),
    (_DL_PATTERN, "driving_license"),
)

# Maximum sizes (in characters)
_MAX_STRING_LENGTH = 10000  # 10KB per string field
_MAX_TOTAL_EXAMPLE_SIZE = 50000  # 50KB per example (input + expected_output)
_MAX_TAGS_LENGTH = 1000
_MAX_EXAMPLE_REF_LENGTH = 64
_MAX_TASK_TYPE_LENGTH = 30


def _extract_strings(obj: object, path: str = "") -> list[tuple[str, str]]:
    """Extract all string values from a nested structure with their paths."""
    strings: list[tuple[str, str]] = []
    if isinstance(obj, str):
        strings.append((path, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            strings.extend(_extract_strings(v, f"{path}.{k}" if path else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            strings.extend(_extract_strings(v, f"{path}[{i}]"))
    return strings


def _check_phi_patterns(text: str) -> list[str]:
    """Check text for PHI patterns. Returns list of matched pattern names."""
    matches = []
    for pattern, name in _PHI_PATTERNS:
        if pattern.search(text):
            matches.append(name)
    return matches


def validate_example(example: BaseModel) -> list[ValidationError]:
    """Validate a single evaluation dataset example.

    Returns a list of validation errors (empty if valid).
    """
    errors: list[ValidationError] = []
    example_ref = getattr(example, "example_ref", None)

    # Check example_ref
    if not example_ref:
        errors.append(
            ValidationError(
                field="example_ref", message="example_ref is required", example_ref=None
            )
        )
    elif not isinstance(example_ref, str):
        errors.append(
            ValidationError(
                field="example_ref",
                message="example_ref must be a string",
                example_ref=str(example_ref),
            )
        )
    elif len(example_ref) > _MAX_EXAMPLE_REF_LENGTH:
        errors.append(
            ValidationError(
                field="example_ref",
                message=f"example_ref exceeds maximum length of {_MAX_EXAMPLE_REF_LENGTH}",
                example_ref=example_ref,
            )
        )

    # Check task_type
    task_type = getattr(example, "task_type", None)
    if not task_type:
        errors.append(
            ValidationError(
                field="task_type",
                message="task_type is required",
                example_ref=example_ref,
            )
        )
    elif not isinstance(task_type, str):
        errors.append(
            ValidationError(
                field="task_type",
                message="task_type must be a string",
                example_ref=example_ref,
            )
        )
    elif len(task_type) > _MAX_TASK_TYPE_LENGTH:
        errors.append(
            ValidationError(
                field="task_type",
                message=f"task_type exceeds maximum length of {_MAX_TASK_TYPE_LENGTH}",
                example_ref=example_ref,
            )
        )

    # Check input
    input_data = getattr(example, "input", None)
    if input_data is None:
        errors.append(
            ValidationError(field="input", message="input is required", example_ref=example_ref)
        )
    elif not isinstance(input_data, dict):
        errors.append(
            ValidationError(
                field="input", message="input must be an object", example_ref=example_ref
            )
        )

    # Check expected_output
    expected_output = getattr(example, "expected_output", None)
    if expected_output is None:
        errors.append(
            ValidationError(
                field="expected_output",
                message="expected_output is required",
                example_ref=example_ref,
            )
        )
    elif not isinstance(expected_output, dict):
        errors.append(
            ValidationError(
                field="expected_output",
                message="expected_output must be an object",
                example_ref=example_ref,
            )
        )

    # Check tags
    tags = getattr(example, "tags", None)
    if tags is not None:
        if not isinstance(tags, list):
            errors.append(
                ValidationError(
                    field="tags",
                    message="tags must be a list",
                    example_ref=example_ref,
                )
            )
        elif not all(isinstance(t, str) for t in tags):
            errors.append(
                ValidationError(
                    field="tags",
                    message="all tags must be strings",
                    example_ref=example_ref,
                )
            )
        elif sum(len(t) for t in tags) > _MAX_TAGS_LENGTH:
            errors.append(
                ValidationError(
                    field="tags",
                    message=f"total tags length exceeds {_MAX_TAGS_LENGTH} characters",
                    example_ref=example_ref,
                )
            )

    # If basic structure is invalid, don't check content
    if errors:
        return errors

    # Check oversized text in input and expected_output
    total_size = 0
    for field_name, field_value in [("input", input_data), ("expected_output", expected_output)]:
        if isinstance(field_value, dict):
            strings = _extract_strings(field_value)
            for path, text in strings:
                if len(text) > _MAX_STRING_LENGTH:
                    errors.append(
                        ValidationError(
                            field=f"{field_name}.{path}",
                            message=(
                                f"string exceeds maximum length of {_MAX_STRING_LENGTH} characters"
                            ),
                            example_ref=example_ref,
                        )
                    )
                total_size += len(text)
                # Check for PHI patterns
                phi_matches = _check_phi_patterns(text)
                if phi_matches:
                    errors.append(
                        ValidationError(
                            field=f"{field_name}.{path}",
                            message=f"contains potential PHI: {', '.join(phi_matches)}",
                            example_ref=example_ref,
                        )
                    )

    # Check total example size
    if total_size > _MAX_TOTAL_EXAMPLE_SIZE:
        errors.append(
            ValidationError(
                field="example",
                message=f"total example size exceeds {_MAX_TOTAL_EXAMPLE_SIZE} characters",
                example_ref=example_ref,
            )
        )

    # Check tags for PHI
    if isinstance(tags, list):
        for tag in tags:
            phi_matches = _check_phi_patterns(tag)
            if phi_matches:
                errors.append(
                    ValidationError(
                        field="tags",
                        message=f"contains potential PHI: {', '.join(phi_matches)}",
                        example_ref=example_ref,
                    )
                )

    return errors


def validate_examples(examples: Sequence[BaseModel]) -> list[ValidationError]:
    """Validate a list of evaluation dataset examples.

    Returns a list of all validation errors across all examples.
    """
    all_errors: list[ValidationError] = []
    seen_refs: set[str] = set()

    for example in examples:
        example_ref = getattr(example, "example_ref", None)

        # Check for duplicate example_ref within the batch
        if example_ref and example_ref in seen_refs:
            all_errors.append(
                ValidationError(
                    field="example_ref",
                    message=f"duplicate example_ref: {example_ref}",
                    example_ref=example_ref,
                )
            )
        if example_ref:
            seen_refs.add(example_ref)

        all_errors.extend(validate_example(example))

    return all_errors
