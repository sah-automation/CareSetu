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

from scripts.scaffold_module import MODULE_SPECS, MODULES_PACKAGE, scaffold_module

ALL_MODULES = (
    "iam",
    "partner",
    "health",
    "consent",
    "intake",
    "care",
    "diagnostics",
    "fulfillment",
    "settlement",
    "notify",
    "audit",
)
EXPECTED_DIRS = ("domain", "adapters", "schema")
EXPECTED_FILES = (
    "facade.py",
    "outbox.py",
    "domain/__init__.py",
    "domain/exceptions.py",
    "schema/__init__.py",
    "schema/models.py",
)


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
    for name in ALL_MODULES:
        assert name in MODULE_SPECS, f"{name} missing from generator registry"
        _assert_hexagonal_layout(MODULES_PACKAGE / name)


def test_table_namespace_prefixes() -> None:
    for name in ALL_MODULES:
        models = importlib.import_module(f"modules.{name}.schema.models")
        metadata = models.MODULE_METADATA
        assert metadata.tables, f"{name}: schema defines no tables"
        for table in metadata.tables.values():
            assert table.name.startswith(f"{name}_"), f"{name}: table {table.name} lacks prefix"
            assert table.schema == name, f"{name}: table {table.name} in wrong schema"


def test_outbox_table_name_constant() -> None:
    for name in ALL_MODULES:
        outbox = importlib.import_module(f"modules.{name}.outbox")
        constant = getattr(outbox, f"{name.upper()}_OUTBOX_TABLE")
        assert constant == f"{name}_outbox"


def test_domain_error_class_exists() -> None:
    for name in ALL_MODULES:
        exceptions = importlib.import_module(f"modules.{name}.domain.exceptions")
        error_class = getattr(exceptions, f"{name.title()}Error")
        assert issubclass(error_class, Exception)
