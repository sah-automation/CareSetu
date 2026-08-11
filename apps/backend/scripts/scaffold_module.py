"""Emit Phase 1 module scaffolds for the CareSetu hexagonal layout.

Covered by ticket #24 (T5a: module scaffolding). The registry below is the
single source of truth for Phase 1 modules; later phases extend it in place
with new ``ModuleSpec`` entries rather than touching this script's structure.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

MODULES_PACKAGE = Path(__file__).resolve().parent.parent / "modules"


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    """Identity of one scaffolded module."""

    module: str
    title: str
    mod_id: str


_MODULE_SPEC_TUPLES: Sequence[tuple[str, str, str]] = (
    ("iam", "Identity and access management", "MOD-001"),
    ("partner", "Partner network management", "MOD-002"),
    ("health", "Health data", "MOD-003"),
    ("consent", "Consent management", "MOD-004"),
    ("intake", "Intake workflows", "MOD-005"),
    ("care", "Care planning", "MOD-006"),
    ("diagnostics", "Diagnostics and lab reports", "MOD-007"),
    ("fulfillment", "Pharmacy fulfillment", "MOD-008"),
    ("settlement", "Settlement and payments", "MOD-009"),
    ("notify", "Notifications", "MOD-010"),
    ("audit", "Audit", "MOD-011"),
)

MODULE_SPECS: dict[str, ModuleSpec] = {
    module: ModuleSpec(module=module, title=title, mod_id=mod_id)
    for module, title, mod_id in _MODULE_SPEC_TUPLES
}


def _ensure_package_init(pkg: Path) -> None:
    """Create ``pkg`` and its ``__init__.py`` when the file is missing."""
    init = pkg / "__init__.py"
    if init.exists():
        return
    pkg.mkdir(parents=True, exist_ok=True)
    init.write_text("", encoding="utf-8", newline="\n")


def _module_files(spec: ModuleSpec) -> list[tuple[str, str]]:
    """Return ``(relative_path, content)`` pairs for ``spec``'s scaffold."""
    spec_name = spec.module.replace(".", "_").title().replace("_", "")
    schema_name = spec.module.rsplit(".", 1)[-1]
    # fmt: off
    template = {
        "domain/exceptions.py": (
            f'"""{spec.mod_id}: domain errors for the ``{spec.module}`` module '
            f"(coding-standards §3).\n"
            "\n"
            "Phase 1 carries the module base error only; the hierarchy grows\n"
            "with the tickets that introduce real validation.\n"
            '"""\n'
            "\n"
            "from __future__ import annotations\n"
            "\n"
            "\n"
            f"class {spec_name}Error(Exception):\n"
            f'    """Base error for the {schema_name} module."""\n'
        ),
        "domain/__init__.py": "",
        "adapters/__init__.py": (
            f'"""{spec.mod_id}: event handlers for the ``{spec.module}`` module '
            "(coding-standards §2).\n"
            "\n"
            "``register_handlers`` is the composition-root seam (PHASE-1 T4, #30):\n"
            "the worker entrypoint calls it to register this module's handlers on\n"
            "the shared ``HandlerRegistry``. No business handlers exist in Phase 1.\n"
            '"""\n'
            "\n"
            "from bus.registry import HandlerRegistry\n"
            "\n"
            "\n"
            "def register_handlers(registry: HandlerRegistry) -> None:\n"
            "    \"\"\"Register this module's event handlers on ``registry`` "
            "(none yet in Phase 1).\"\"\"\n"
        ),
        "schema/__init__.py": "",
        "schema/models.py": (
            f'"""{spec.mod_id}: SQLAlchemy models for the ``{schema_name}`` '
            f"schema only (ADR-0003).\n"
            "\n"
            "Table namespace rule (coding-standards §2, T6a checker #26):\n"
            f"every table is prefixed with ``{spec.module}_`` and lives in\n"
            f"the ``{schema_name}`` schema. Models are added incrementally\n"
            "as Phase 2 tickets land.\n"
            '"""\n'
            "\n"
            "from __future__ import annotations\n"
            "\n"
            "from sqlalchemy import BigInteger, Column, MetaData, Table\n"
            "\n"
            f'MODULE_METADATA = MetaData(schema="{schema_name}")\n'
            "\n"
            "\n"
            f"{spec.module}_identities = Table(\n"
            f'    "{spec.module}_identities",\n'
            "    MODULE_METADATA,\n"
            '    Column("id", BigInteger, primary_key=True),\n'
            ")\n"
        ),
        "outbox.py": (
            f'"""{spec.mod_id}: outbox table contract for the ``{spec.module}`` '
            f"module (ADR-0003).\n"
            "\n"
            "The transactional outbox table name is a module contract; the\n"
            "T6a boundary checker (#26) verifies it matches the schema table.\n"
            '"""\n'
            "\n"
            "from __future__ import annotations\n"
            "\n"
            f'{spec.module.upper()}_OUTBOX_TABLE = "{spec.module}_outbox"\n'
        ),
        "facade.py": (
            f'"""{spec.mod_id} {spec.title}: typed public sync API.\n'
            "\n"
            f"The only legal cross-module import target for the ``{spec.module}``\n"
            "module (coding-standards §2, ADR-0003). Typed methods arrive with\n"
            "Phase 2; this scaffold carries no business logic.\n"
            '"""\n'
            "\n"
            "from __future__ import annotations\n"
            "\n"
            "\n"
            f"class {spec_name}Facade:\n"
            f'    """Typed public facade for {schema_name} (scaffold)."""\n'
        ),
    }
    # fmt: on
    return list(template.items())


def scaffold_module(spec: ModuleSpec, out_dir: Path) -> list[Path]:
    """Create the module tree for ``spec`` under ``out_dir``.

    Files are written with LF line endings; an existing file is never
    rewritten, so regenerating after a template change diverges loudly in the
    layout test rather than silently producing different bytes on disk.
    """
    _ensure_package_init(out_dir)
    package_dir = out_dir / spec.module
    _ensure_package_init(package_dir)
    written: list[Path] = []
    for rel_path, content in _module_files(spec):
        target = package_dir / rel_path
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        written.append(target)
    return written


def main() -> None:
    """Emit every module in ``MODULE_SPECS`` under ``modules/``."""
    for spec in MODULE_SPECS.values():
        scaffold_module(spec, MODULES_PACKAGE)
        print(f"scaffolded {spec.module}")


if __name__ == "__main__":
    main()
