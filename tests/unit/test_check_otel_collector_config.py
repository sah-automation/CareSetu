"""PHASE-14 T32 (#749): collector cardinality-firewall lint - fixture tests.

Feeds ``deploy/otel-collector/`` trees (a real one and mutated copies) to
``scripts.check_otel_collector_config`` and asserts the gate accepts the
committed firewall while rejecting drift: a missing fourth status class, a
missing raw-status delete, a dropped method guard, a resurrected raw label,
classic histograms kept alongside NHCB, a literal credential, and an
undocumented environment variable. Also asserts the real repo is clean and
that ``main`` reports exit codes.
"""

from pathlib import Path

import pytest
from scripts.check_otel_collector_config import (
    CollectorViolation,
    check_otel_collector_config,
    main,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_DEPLOY_ROOT = REPO_ROOT / "deploy"
REAL_CONFIG = REAL_DEPLOY_ROOT / "otel-collector" / "config.yaml"
REAL_README = REAL_DEPLOY_ROOT / "otel-collector" / "README.md"


def _deploy_tree(tmp_path: Path) -> Path:
    """A writable copy of the committed ``deploy/otel-collector/`` tree."""
    deploy_root = tmp_path / "deploy"
    collector_dir = deploy_root / "otel-collector"
    collector_dir.mkdir(parents=True)
    (collector_dir / "config.yaml").write_text(
        REAL_CONFIG.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (collector_dir / "README.md").write_text(
        REAL_README.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return deploy_root


def _config_path(deploy_root: Path) -> Path:
    return deploy_root / "otel-collector" / "config.yaml"


def _readme_path(deploy_root: Path) -> Path:
    return deploy_root / "otel-collector" / "README.md"


def _messages(violations: tuple[CollectorViolation, ...]) -> str:
    return "\n".join(violation.message for violation in violations)


def test_real_config_is_clean() -> None:
    assert check_otel_collector_config(REAL_DEPLOY_ROOT) == ()


def test_missing_config_is_rejected(tmp_path: Path) -> None:
    deploy_root = tmp_path / "deploy"
    (deploy_root / "otel-collector").mkdir(parents=True)

    violations = check_otel_collector_config(deploy_root)
    assert len(violations) == 1
    assert "missing config.yaml" in violations[0].message


def test_status_class_invented_is_rejected(tmp_path: Path) -> None:
    deploy_root = _deploy_tree(tmp_path)
    path = _config_path(deploy_root)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'set(attributes["http.status_class"], "server-error")',
            'set(attributes["http.status_class"], "redirect")',
        ),
        encoding="utf-8",
    )

    violations = check_otel_collector_config(deploy_root)
    assert "server-error" in _messages(tuple(v for v in violations if "classify" in v.message))


def test_missing_raw_status_delete_is_rejected(tmp_path: Path) -> None:
    deploy_root = _deploy_tree(tmp_path)
    path = _config_path(deploy_root)
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        "          - 'delete_key(attributes, \"http.response.status_code\")'", ""
    )
    path.write_text(source, encoding="utf-8")

    violations = check_otel_collector_config(deploy_root)
    assert "http.response.status_code" in _messages(violations)


def test_missing_method_guard_is_rejected(tmp_path: Path) -> None:
    deploy_root = _deploy_tree(tmp_path)
    path = _config_path(deploy_root)
    source = path.read_text(encoding="utf-8")
    verbs = "GET|HEAD|POST|PUT|DELETE|CONNECT|OPTIONS|TRACE|PATCH"
    guarded = (
        'set(attributes["http.request.method"], "UNKNOWN") where not '
        f'IsNil(attributes["http.request.method"]) and not '
        f'IsMatch(attributes["http.request.method"], "^({verbs})$")'
    )
    source = source.replace(guarded, 'set(attributes["http.request.method"], "UNKNOWN")')
    path.write_text(source, encoding="utf-8")

    violations = check_otel_collector_config(deploy_root)
    assert "http.request.method" in _messages(violations)


def test_reintroduced_raw_label_is_rejected(tmp_path: Path) -> None:
    deploy_root = _deploy_tree(tmp_path)
    path = _config_path(deploy_root)
    source = path.read_text(encoding="utf-8")
    source = source.replace("          - 'delete_key(attributes, \"http.url\")'", "")
    path.write_text(source, encoding="utf-8")

    violations = check_otel_collector_config(deploy_root)
    assert "http.url" in _messages(violations)


def test_keep_classic_histograms_is_rejected(tmp_path: Path) -> None:
    deploy_root = _deploy_tree(tmp_path)
    path = _config_path(deploy_root)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "keep_classic_histograms: false", "keep_classic_histograms: true"
        ),
        encoding="utf-8",
    )

    violations = check_otel_collector_config(deploy_root)
    assert "keep_classic_histograms" in _messages(violations)


def test_nhcb_disabled_is_rejected(tmp_path: Path) -> None:
    deploy_root = _deploy_tree(tmp_path)
    path = _config_path(deploy_root)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "convert_explicit_histograms_to_nhcb: true",
            "convert_explicit_histograms_to_nhcb: false",
        ),
        encoding="utf-8",
    )

    violations = check_otel_collector_config(deploy_root)
    assert "convert_explicit_histograms_to_nhcb" in _messages(violations)


def test_literal_credential_is_rejected(tmp_path: Path) -> None:
    deploy_root = _deploy_tree(tmp_path)
    path = _config_path(deploy_root)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "password: ${env:GRAFANA_CLOUD_API_KEY}", "password: glc_supersecret"
        ),
        encoding="utf-8",
    )

    violations = check_otel_collector_config(deploy_root)
    assert "client.password" in _messages(violations)


def test_undocumented_env_var_is_rejected(tmp_path: Path) -> None:
    deploy_root = _deploy_tree(tmp_path)
    config = _config_path(deploy_root)
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "endpoint: ${env:GRAFANA_OTLP_URL}",
            "endpoint: ${env:GRAFANA_MYSTERY_URL}",
        ),
        encoding="utf-8",
    )

    violations = check_otel_collector_config(deploy_root)
    assert "GRAFANA_MYSTERY_URL" in _messages(violations)


def test_missing_advisory_note_is_rejected(tmp_path: Path) -> None:
    deploy_root = _deploy_tree(tmp_path)
    path = _readme_path(deploy_root)
    path.write_text(
        path.read_text(encoding="utf-8").replace("GHSA-5rv5-6h4r-h22v", "the advisory"),
        encoding="utf-8",
    )

    violations = check_otel_collector_config(deploy_root)
    assert "GHSA-5rv5-6h4r-h22v" in _messages(violations)


def test_pipeline_order_is_enforced(tmp_path: Path) -> None:
    deploy_root = _deploy_tree(tmp_path)
    path = _config_path(deploy_root)
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        "    metrics:\n"
        "      receivers:\n"
        "        - otlp\n"
        "      processors:\n"
        "        - memory_limiter\n"
        "        - transform/cardinality_firewall\n"
        "        - batch\n",
        "    metrics:\n"
        "      receivers:\n"
        "        - otlp\n"
        "      processors:\n"
        "        - transform/cardinality_firewall\n"
        "        - memory_limiter\n"
        "        - batch\n",
    )
    path.write_text(source, encoding="utf-8")

    violations = check_otel_collector_config(deploy_root)
    assert "memory_limiter first" in _messages(violations)


def test_instrumentor_floor_below_advisory_fix_is_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    pyproject = repo / "apps" / "backend" / "pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text(
        '[project]\ndependencies = [\n    "opentelemetry-instrumentation-fastapi>=0.40b0",\n]\n',
        encoding="utf-8",
    )

    violations = check_otel_collector_config(_deploy_tree(tmp_path), repo)
    assert "GHSA-5rv5-6h4r-h22v" in _messages(violations)


def test_instrumentor_floor_is_checked_in_real_repo() -> None:
    real = check_otel_collector_config(REAL_DEPLOY_ROOT, REPO_ROOT)
    pyproject_violations = [
        violation
        for violation in real
        if "opentelemetry-instrumentation-fastapi" in violation.message
    ]
    assert pyproject_violations == []


def test_main_reports_failure_and_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy_root = _deploy_tree(tmp_path)
    assert main(["--deploy-root", str(deploy_root)]) == 0

    path = _config_path(deploy_root)
    path.write_text("", encoding="utf-8")
    assert main(["--deploy-root", str(deploy_root)]) == 1
    assert "FAILED" in capsys.readouterr().err
