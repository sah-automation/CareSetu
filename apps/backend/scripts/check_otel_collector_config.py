"""PHASE-14 T32 (#749): collector cardinality-firewall lint.

Lints ``deploy/otel-collector/config.yaml`` - the committed OpenTelemetry
collector configuration that acts as the cardinality firewall for the
free-tier series ceiling (ADR-0024, spec #717 decisions 37/38). A running
collector is not available in the lint pass ("the config is committed as
data"), so "the firewall is sound" is a deterministic lint that asserts the
contract:

- the config file exists, is valid YAML, and is non-empty;
- pipeline order is ``memory_limiter`` first and ``batch`` last in every
  pipeline, with ``transform/cardinality_firewall`` in the metrics pipeline;
- the transform collapses response status to exactly the three #727 classes
  (``success`` / ``client-error`` / ``server-error``) and classifies both the
  instrumentor key ``http.status_code`` and the app key
  ``http.response.status_code``, deleting both raw keys;
- the transform normalises the bounded HTTP method vocabulary on both method
  keys;
- the raw path/URL/Host labels are deleted;
- the remote-write exporter exports native histograms (NHCB) and does not
  keep classic histograms, so a label set is one series;
- no literal credential is committed (secrets come from the environment);
- the FastAPI instrumentor version floor in ``apps/backend/pyproject.toml`` is
  at or above the release that fixed the unbounded-cardinality advisory
  (GHSA-5rv5-6h4r-h22v), so the firewall can never be shipped against an
  exposed instrumentor;
- the README documents every referenced environment variable and the open
  advisory, so neither can be dropped without failing the build.

Requires PyYAML (a declared backend dependency); unlike the stdlib-only
gates this one parses YAML as data, because the firewall's meaning is
structural.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DEPLOY_ROOT = REPO_ROOT / "deploy"

COLLECTOR_DIR_NAME = "otel-collector"
CONFIG_NAME = "config.yaml"
README_NAME = "README.md"

FIREWALL_PROCESSOR = "transform/cardinality_firewall"
MEMORY_LIMITER = "memory_limiter"
BATCH_PROCESSOR = "batch"
METRICS_EXPORTER = "prometheus_remote_write/grafana"

STATUS_CLASS_ATTR = "http.status_class"
STATUS_CLASSES = ("success", "client-error", "server-error")
STATUS_CLASS_1XX_MAX = 400
STATUS_CLASS_4XX_MAX = 500
STATUS_CODE_KEYS = ("http.status_code", "http.response.status_code")
METHOD_KEYS = ("http.method", "http.request.method")
METHOD_VERBS = ("GET", "HEAD", "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH")
METHOD_UNKNOWN = "UNKNOWN"
DROPPED_LABELS = (
    "http.host",
    "http.server_name",
    "http.url",
    "url.full",
    "url.path",
    "url.query",
    "net.host.name",
    "net.host.port",
)
NHCB_OPTION = "convert_explicit_histograms_to_nhcb"
KEEP_CLASSIC_OPTION = "keep_classic_histograms"
EXTENSION_NAME = "basicauth/grafana_cloud"

ADVISORY_MARKER = "GHSA-5rv5-6h4r-h22v"
ENV_VAR_PATTERN = re.compile(r"\$\{env:(?P<name>[A-Z0-9_]+)\}")

CARDINALITY_FIREWALL_REF = "#749"

PYPROJECT_RELATIVE = Path("apps/backend/pyproject.toml")
FASTAPI_INSTRUMENTOR_PACKAGE = "opentelemetry-instrumentation-fastapi"
#: The release that fixed the unbounded-cardinality DoS advisory
#: (GHSA-5rv5-6h4r-h22v / CVE-2023-43810). The pinned floor must stay at or
#: above this, or the firewall ships against an exposed instrumentor.
ADVISORY_FIXED_VERSION = (0, 41, 0)
INSTRUMENTOR_FLOOR_PATTERN = re.compile(
    r'"' + re.escape(FASTAPI_INSTRUMENTOR_PACKAGE) + r">=?(?P<version>[0-9]+\.[0-9]+(?:\.[0-9]+)?)"
)


def _parse_version(text: str) -> tuple[int, ...]:
    """``"0.48"`` -> ``(0, 48)``; a stable tuple for ``>=`` comparison."""
    return tuple(int(part) for part in text.split("."))


@dataclass(frozen=True)
class CollectorViolation:
    """One rule break in ``deploy/otel-collector/``."""

    path: Path
    message: str


def _load_config(path: Path) -> dict[str, Any] | None:
    """Parse ``config.yaml``; ``None`` when the file is missing or unreadable."""
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _collect_statements(config: dict[str, Any]) -> list[str]:
    """Every OTTL statement in the cardinality-firewall transform."""
    processors = config.get("processors")
    if not isinstance(processors, dict):
        return []
    firewall = processors.get(FIREWALL_PROCESSOR)
    if not isinstance(firewall, dict):
        return []
    groups = firewall.get("metric_statements")
    if not isinstance(groups, list):
        return []
    statements: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        entries = group.get("statements")
        if isinstance(entries, list):
            statements.extend(str(entry) for entry in entries)
    return statements


def _pipeline_violations(config: dict[str, Any], path: Path) -> list[CollectorViolation]:
    """Assert processor order and firewall wiring in every pipeline."""
    violations: list[CollectorViolation] = []
    service = config.get("service")
    pipelines = service.get("pipelines") if isinstance(service, dict) else None
    if not isinstance(pipelines, dict) or not pipelines:
        return [CollectorViolation(path, f"{CONFIG_NAME} must declare service.pipelines")]
    metrics = pipelines.get("metrics")
    if not isinstance(metrics, dict):
        return [CollectorViolation(path, f"{CONFIG_NAME} must declare a metrics pipeline")]
    for name, pipeline in pipelines.items():
        if not isinstance(pipeline, dict):
            continue
        processors = pipeline.get("processors")
        if not isinstance(processors, list) or not processors:
            violations.append(CollectorViolation(path, f"pipeline {name} must declare processors"))
            continue
        if processors[0] != MEMORY_LIMITER:
            violations.append(
                CollectorViolation(path, f"pipeline {name} must put {MEMORY_LIMITER} first")
            )
        if processors[-1] != BATCH_PROCESSOR:
            violations.append(
                CollectorViolation(path, f"pipeline {name} must put {BATCH_PROCESSOR} last")
            )
    metrics_processors = metrics.get("processors")
    if not isinstance(metrics_processors, list) or FIREWALL_PROCESSOR not in metrics_processors:
        violations.append(
            CollectorViolation(
                path, f"metrics pipeline must run {FIREWALL_PROCESSOR} before export"
            )
        )
    metrics_exporters = metrics.get("exporters")
    if not isinstance(metrics_exporters, list) or METRICS_EXPORTER not in metrics_exporters:
        violations.append(
            CollectorViolation(path, f"metrics pipeline must export to {METRICS_EXPORTER}")
        )
    return violations


def _status_class_violations(config: dict[str, Any], path: Path) -> list[CollectorViolation]:
    """Assert exactly three status classes over both raw status keys."""
    statements = _collect_statements(config)
    violations: list[CollectorViolation] = []
    for status_class in STATUS_CLASSES:
        if not any(
            f'"{status_class}"' in statement and STATUS_CLASS_ATTR in statement
            for statement in statements
        ):
            violations.append(
                CollectorViolation(
                    path, f"firewall must classify status into {STATUS_CLASS_ATTR}={status_class}"
                )
            )
    found_classes = {
        status_class
        for status_class in STATUS_CLASSES
        for statement in statements
        if f'"{status_class}"' in statement and STATUS_CLASS_ATTR in statement
    }
    for status_class in found_classes:
        if status_class not in STATUS_CLASSES:
            violations.append(
                CollectorViolation(path, f"firewall must not invent a status class {status_class}")
            )
    thresholds = {int(value) for value in re.findall(r"<\s*(\d+)", " ".join(statements))}
    if STATUS_CLASS_1XX_MAX not in thresholds:
        violations.append(
            CollectorViolation(path, "firewall must fold 3xx into success via a < 400 comparison")
        )
    if STATUS_CLASS_4XX_MAX not in thresholds:
        violations.append(
            CollectorViolation(path, "firewall must bound client-error via a < 500 comparison")
        )
    for key in STATUS_CODE_KEYS:
        if not any("delete_key" in statement and key in statement for statement in statements):
            violations.append(
                CollectorViolation(
                    path, f"firewall must delete the raw status key {key} once classified"
                )
            )
    return violations


def _method_violations(config: dict[str, Any], path: Path) -> list[CollectorViolation]:
    """Assert the bounded method vocabulary on both method keys."""
    statements = _collect_statements(config)
    violations: list[CollectorViolation] = []
    for key in METHOD_KEYS:
        guarded = [
            statement
            for statement in statements
            if key in statement and METHOD_UNKNOWN in statement and "IsMatch" in statement
        ]
        if not guarded:
            violations.append(
                CollectorViolation(
                    path, f"firewall must normalise {key} against the standard verb list"
                )
            )
            continue
        vocabulary = guarded[0]
        for verb in METHOD_VERBS:
            if verb not in vocabulary:
                violations.append(
                    CollectorViolation(
                        path, f"firewall method vocabulary for {key} is missing {verb}"
                    )
                )
    return violations


def _label_violations(config: dict[str, Any], path: Path) -> list[CollectorViolation]:
    """Assert every raw path/URL/Host label is deleted."""
    statements = _collect_statements(config)
    violations: list[CollectorViolation] = []
    for label in DROPPED_LABELS:
        if not any("delete_key" in statement and label in statement for statement in statements):
            violations.append(
                CollectorViolation(path, f"firewall must delete the raw label {label}")
            )
    return violations


def _exporter_violations(config: dict[str, Any], path: Path) -> list[CollectorViolation]:
    """Assert native-histogram export with classic series switched off."""
    exporters = config.get("exporters")
    if not isinstance(exporters, dict):
        return [CollectorViolation(path, f"{CONFIG_NAME} must declare exporters")]
    metrics = exporters.get(METRICS_EXPORTER)
    if not isinstance(metrics, dict):
        return [CollectorViolation(path, f"{CONFIG_NAME} must declare {METRICS_EXPORTER}")]
    violations: list[CollectorViolation] = []
    if metrics.get(NHCB_OPTION) is not True:
        violations.append(
            CollectorViolation(path, f"{METRICS_EXPORTER} must set {NHCB_OPTION}: true")
        )
    if metrics.get(KEEP_CLASSIC_OPTION) is True:
        violations.append(
            CollectorViolation(
                path,
                f"{METRICS_EXPORTER} must not set {KEEP_CLASSIC_OPTION}: true "
                "(classic series would defeat the firewall)",
            )
        )
    return violations


def _secret_violations(config: dict[str, Any], path: Path) -> list[CollectorViolation]:
    """Assert the basic-auth extension takes its values from the environment."""
    extensions = config.get("extensions")
    if not isinstance(extensions, dict) or EXTENSION_NAME not in extensions:
        return [CollectorViolation(path, f"{CONFIG_NAME} must declare {EXTENSION_NAME}")]
    extension = extensions[EXTENSION_NAME]
    if not isinstance(extension, dict):
        return [CollectorViolation(path, f"{EXTENSION_NAME} must be a mapping")]
    client = extension.get("client")
    if not isinstance(client, dict):
        return [CollectorViolation(path, f"{EXTENSION_NAME} must declare a client block")]
    violations: list[CollectorViolation] = []
    for field in ("username", "password"):
        value = client.get(field)
        if not isinstance(value, str) or not value.startswith("${env:"):
            violations.append(
                CollectorViolation(
                    path, f"{EXTENSION_NAME} must read client.{field} from the environment"
                )
            )
    return violations


def _env_var_names(source: str) -> set[str]:
    """Every environment variable name referenced as ``${env:NAME}``."""
    return {match.group("name") for match in ENV_VAR_PATTERN.finditer(source)}


def _readme_violations(config_path: Path, readme_path: Path) -> list[CollectorViolation]:
    """Assert the README documents every env var, the advisory and the cutover."""
    if not readme_path.is_file():
        return [CollectorViolation(readme_path, f"missing {README_NAME}")]
    readme = readme_path.read_text(encoding="utf-8")
    if not readme.strip():
        return [CollectorViolation(readme_path, f"empty {README_NAME}")]
    violations: list[CollectorViolation] = []
    config_source = config_path.read_text(encoding="utf-8")
    for name in sorted(_env_var_names(config_source)):
        if name not in readme:
            violations.append(
                CollectorViolation(readme_path, f"{README_NAME} must document {name}")
            )
    if ADVISORY_MARKER not in readme:
        violations.append(
            CollectorViolation(
                readme_path,
                f"{README_NAME} must record the advisory check ({ADVISORY_MARKER})",
            )
        )
    if CARDINALITY_FIREWALL_REF not in readme:
        violations.append(
            CollectorViolation(
                readme_path,
                f"{README_NAME} must reference the firewall ticket {CARDINALITY_FIREWALL_REF}",
            )
        )
    if "native histogram" not in readme.lower():
        violations.append(
            CollectorViolation(readme_path, f"{README_NAME} must document native histograms")
        )
    return violations


def _instrumentor_floor_violations(repo_root: Path) -> list[CollectorViolation]:
    """Assert the FastAPI instrumentor floor clears the advisory fix.

    The firewall is the mitigation for GHSA-5rv5-6h4r-h22v, so it must never
    ship against an instrumentor whose floor still admits the exposed release.
    """
    pyproject_path = repo_root / PYPROJECT_RELATIVE
    if not pyproject_path.is_file():
        return [CollectorViolation(pyproject_path, f"missing {PYPROJECT_RELATIVE}")]
    source = pyproject_path.read_text(encoding="utf-8")
    match = INSTRUMENTOR_FLOOR_PATTERN.search(source)
    if match is None:
        return [
            CollectorViolation(
                pyproject_path,
                f"must pin {FASTAPI_INSTRUMENTOR_PACKAGE} (advisory {ADVISORY_MARKER})",
            )
        ]
    floor = _parse_version(match.group("version"))
    if floor < ADVISORY_FIXED_VERSION:
        fixed = ".".join(str(part) for part in ADVISORY_FIXED_VERSION)
        return [
            CollectorViolation(
                pyproject_path,
                f"{FASTAPI_INSTRUMENTOR_PACKAGE} floor {match.group('version')} is below the "
                f"advisory {ADVISORY_MARKER} fix {fixed}",
            )
        ]
    return []


def check_otel_collector_config(
    deploy_root: Path = DEFAULT_DEPLOY_ROOT,
    repo_root: Path = REPO_ROOT,
) -> tuple[CollectorViolation, ...]:
    """Lint ``deploy/otel-collector/`` against the cardinality-firewall contract.

    Returns every violation, sorted by message, so the output is deterministic
    and the unit tests can assert on exact violations.
    """
    collector_dir = deploy_root / COLLECTOR_DIR_NAME
    config_path = collector_dir / CONFIG_NAME
    readme_path = collector_dir / README_NAME
    if not config_path.is_file():
        return (CollectorViolation(config_path, f"missing {CONFIG_NAME}"),)
    source = config_path.read_text(encoding="utf-8")
    if not source.strip():
        return (CollectorViolation(config_path, f"empty {CONFIG_NAME}"),)
    config = _load_config(config_path)
    if config is None:
        return (CollectorViolation(config_path, f"{CONFIG_NAME} is not valid YAML data"),)
    violations: list[CollectorViolation] = []
    violations.extend(_pipeline_violations(config, config_path))
    violations.extend(_status_class_violations(config, config_path))
    violations.extend(_method_violations(config, config_path))
    violations.extend(_label_violations(config, config_path))
    violations.extend(_exporter_violations(config, config_path))
    violations.extend(_secret_violations(config, config_path))
    violations.extend(_instrumentor_floor_violations(repo_root))
    violations.extend(_readme_violations(config_path, readme_path))
    return tuple(sorted(violations, key=lambda violation: violation.message))


def main(argv: list[str] | None = None) -> int:
    """Run the collector cardinality-firewall lint; exit 1 on violations."""
    parser = argparse.ArgumentParser(
        description="Lint deploy/otel-collector/ (PHASE-14 T32, #749).",
    )
    parser.add_argument(
        "--deploy-root",
        type=Path,
        default=DEFAULT_DEPLOY_ROOT,
        help=f"path to the deploy directory (default: {DEFAULT_DEPLOY_ROOT})",
    )
    args = parser.parse_args(argv)
    violations = check_otel_collector_config(args.deploy_root)
    for violation in violations:
        print(f"{violation.path}: {violation.message}", file=sys.stderr)
    if violations:
        print(
            f"otel collector config check FAILED: {len(violations)} violation(s)",
            file=sys.stderr,
        )
        return 1
    print(
        "otel collector config check OK: deploy/otel-collector/ enforces the "
        "cardinality firewall (#749)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
