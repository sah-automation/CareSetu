"""PHASE-1 T5a/T5b: module scaffold - hexagonal layout + namespace prefixes (#24, #25).

Asserts the generator can emit a module package into a throwaway directory and
that all eleven modules are scaffolded under ``apps/backend/modules/`` with the
hexagonal layout from coding-standards §2 (``domain/``, ``adapters/``,
``schema/``, ``facade.py``, ``outbox.py``). Also guards the table namespace
prefix rule (every table starts with ``<module>_``, e.g. ``consent_consents``)
that the T6a boundary checker (#26) will enforce over the real module tree.
"""

import importlib
from pathlib import Path

import pytest
from scripts.scaffold_module import (
    _MODULE_SPEC_TUPLES,
    MODULE_SPECS,
    MODULES_PACKAGE,
    _build_module_specs,
    scaffold_module,
)

from bus.bootstrap import MODULE_SCHEMAS

EXPECTED_DIRS = ("domain", "adapters", "schema")
EXPECTED_FILES = (
    "facade.py",
    "outbox.py",
    "domain/__init__.py",
    "domain/exceptions.py",
    "schema/__init__.py",
    "schema/models.py",
)


def test_spec_drift_from_bootstrap_raises() -> None:
    """A name in MODULE_SCHEMAS but not the spec tuples fails loudly (issue #47)."""
    drifted = (*MODULE_SCHEMAS, "future_module")

    with pytest.raises(RuntimeError, match="MODULE_SCHEMAS"):
        _build_module_specs(drifted, _MODULE_SPEC_TUPLES)


def _assert_hexagonal_layout(root: Path) -> None:
    """Assert ``root`` carries the full hexagonal layout from coding-standards §2."""
    for directory in EXPECTED_DIRS:
        assert (root / directory).is_dir(), f"{root.name}: missing {directory}/"
    for relative in EXPECTED_FILES:
        assert (root / relative).is_file(), f"{root.name}: missing {relative}"


def test_generator_emits_hexagonal_layout(tmp_path: Path) -> None:
    out_dir = tmp_path / "modules"
    spec = MODULE_SPECS["iam"]

    written = scaffold_module(spec, out_dir)

    assert written, "generator wrote nothing"
    assert (out_dir / "__init__.py").is_file(), "modules package missing __init__.py"
    _assert_hexagonal_layout(out_dir / "iam")

    again = scaffold_module(spec, out_dir)
    assert again == [], "re-running the generator must be a no-op"

    models_text = (out_dir / "iam" / "schema" / "models.py").read_text(encoding="utf-8")
    assert 'MODULE_METADATA = MetaData(schema="iam")' in models_text
    assert "iam_identities = Table(" in models_text

    adapters_text = (out_dir / "iam" / "adapters" / "__init__.py").read_text(encoding="utf-8")
    assert "def register_handlers(registry: HandlerRegistry) -> None:" in adapters_text


def test_all_modules_scaffolded() -> None:
    for name in MODULE_SCHEMAS:
        assert name in MODULE_SPECS, f"{name} missing from generator registry"
        _assert_hexagonal_layout(MODULES_PACKAGE / name)


def test_table_namespace_prefixes() -> None:
    for name in MODULE_SCHEMAS:
        models = importlib.import_module(f"modules.{name}.schema.models")
        metadata = models.MODULE_METADATA
        assert metadata.tables, f"{name}: schema defines no tables"
        for table in metadata.tables.values():
            assert table.name.startswith(f"{name}_"), f"{name}: table {table.name} lacks prefix"
            assert table.schema == name, f"{name}: table {table.name} in wrong schema"


def test_outbox_table_name_constant() -> None:
    for name in MODULE_SCHEMAS:
        outbox = importlib.import_module(f"modules.{name}.outbox")
        constant = getattr(outbox, f"{name.upper()}_OUTBOX_TABLE")
        assert constant == f"{name}_outbox"


def test_domain_error_class_exists() -> None:
    for name in MODULE_SCHEMAS:
        exceptions = importlib.import_module(f"modules.{name}.domain.exceptions")
        error_class = getattr(exceptions, f"{name.title()}Error")
        assert issubclass(error_class, Exception)
