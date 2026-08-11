"""PHASE-1 T6b (#27): migration-check cross-schema FK rule (ADR-0003).

AST-scans every migration in ``alembic/versions`` and rejects foreign keys
whose source and referent tables resolve to different schemas - the
no-cross-schema-FK half of the module isolation rule (ADR-0003 section 1,
coding-standards section 2/5). The single-head invariant stays in the Node gate
(``scripts/migration-check.cjs``); this script adds the FK scan on top.

Schema resolution, in order of precedence, for each side of a foreign key:

1. An explicit schema literal: ``source_schema``/``referent_schema`` on
   ``op.create_foreign_key``, ``schema=`` on ``op.create_table``/``Table``.
2. A dotted table reference (``"consent.consent_consents"``) - PostgreSQL
   treats the leading part as the schema.
3. The table-declaration map: any ``op.create_table(..., schema=...)`` in the
   migration tree that declared the table's name.

A violation fires only when both sides resolve to a schema and the schemas
differ. Foreign keys whose schema cannot be resolved from migration source
(``op.execute`` raw DDL, non-literal names, unqualified names with no matching
``create_table``) are not flagged - the gate enforces the rule over alembic's
structured FK operations and is deliberately biased against false positives.

Stdlib-only by design, like the boundary checker: pre-commit and CI run this
gate on a bare interpreter before the backend's third-party dependencies are
installed.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VERSIONS_DIR = BACKEND_ROOT / "alembic" / "versions"


@dataclass(frozen=True)
class MigrationViolation:
    """One rule break: a foreign key whose ends live in different schemas."""

    path: Path
    message: str


def _call_name(func: ast.expr) -> str | None:
    """The dotted-tail name of a call target (``create_table``, ``sa.Table``)."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _iter_calls(tree: ast.AST, name: str) -> Iterable[ast.Call]:
    """Yield ``Call`` nodes whose target name is ``name``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node.func) == name:
            yield node


def _constant_string(node: ast.AST | None) -> str | None:
    """The value of ``node`` when it is a string literal, else ``None``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _keyword_string(call: ast.Call, name: str) -> str | None:
    """The string value of keyword ``name`` on ``call``, else ``None``."""
    for keyword in call.keywords:
        if keyword.arg == name:
            return _constant_string(keyword.value)
    return None


def _positional_node(call: ast.Call, index: int) -> ast.AST | None:
    """The ``index``-th positional argument node of ``call``, else ``None``."""
    if index < len(call.args):
        return call.args[index]
    return None


def _positional_string(call: ast.Call, index: int) -> str | None:
    """The string value of the ``index``-th positional argument, else ``None``."""
    return _constant_string(_positional_node(call, index))


def _string_list(node: ast.AST | None) -> list[str]:
    """Every string literal in ``node`` when it is a list/tuple literal."""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return []
    strings: list[str] = []
    for element in node.elts:
        value = _constant_string(element)
        if value is not None:
            strings.append(value)
    return strings


def _split_table(name: str) -> tuple[str | None, str]:
    """Split a table name into ``(schema, table)``; the leading dot-part is the schema."""
    parts = name.split(".")
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, parts[0]


def _table_call_schema(call: ast.Call) -> str | None:
    """The schema a ``create_table``/``Table`` call declares, else ``None``.

    From an explicit ``schema=`` keyword, falling back to the
    ``MetaData(schema=...)`` metadata object. Callers apply the leading
    dot-part of a qualified table name themselves.
    """
    schema = _keyword_string(call, "schema")
    if schema is None and len(call.args) > 1:
        metadata = call.args[1]
        if isinstance(metadata, ast.Call) and _call_name(metadata.func) == "MetaData":
            schema = _keyword_string(metadata, "schema")
            if schema is None and metadata.args:
                schema = _constant_string(metadata.args[0])
    return schema


def _declared_table_schemas(files: Sequence[Path]) -> dict[str, str]:
    """Map every table name declared with a schema to that schema.

    Drawn from ``op.create_table``/``Table`` calls across the whole migration
    tree, so an FK can be judged against where its referent table is actually
    created. Deterministic: later declarations (sorted file order, source order)
    win on the rare same-name collision.
    """
    schemas: dict[str, str] = {}
    for file in files:
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        except SyntaxError:
            continue
        for call in _iter_calls(tree, "create_table"):
            _register_declared_table(schemas, call)
        for call in _iter_calls(tree, "Table"):
            _register_declared_table(schemas, call)
    return schemas


def _register_declared_table(schemas: dict[str, str], call: ast.Call) -> None:
    name = _positional_string(call, 0)
    if name is None:
        return
    schema = _table_call_schema(call)
    qualified, table = _split_table(name)
    resolved = schema if schema is not None else qualified
    if resolved is not None:
        schemas[table] = resolved


def _resolve_schema(
    name: str,
    explicit: str | None,
    declared_schemas: dict[str, str],
) -> str | None:
    """The schema of table ``name`` under the resolution precedence, else ``None``."""
    if explicit is not None:
        return explicit
    qualified, table = _split_table(name)
    if qualified is not None:
        return qualified
    return declared_schemas.get(table)


def _is_cross_schema(local_schema: str | None, remote_schema: str | None) -> bool:
    """True when both ends resolve to a schema and the schemas differ."""
    return local_schema is not None and remote_schema is not None and local_schema != remote_schema


def _referent_schema(remote: str, declared_schemas: dict[str, str]) -> str | None:
    """The schema of a referent string (``table.col`` or ``schema.table.col``)."""
    parts = remote.split(".")
    if len(parts) >= 3:
        return parts[0]
    if len(parts) == 2:
        return declared_schemas.get(parts[0])
    return declared_schemas.get(remote)


def _foreign_key_violations(
    file: Path,
    source: str,
    tree: ast.Module,
    declared_schemas: dict[str, str],
) -> list[MigrationViolation]:
    """Check every ``op.create_foreign_key`` call in the file."""
    violations: list[MigrationViolation] = []
    for call in _iter_calls(tree, "create_foreign_key"):
        source_table = _positional_string(call, 1)
        referent_table = _positional_string(call, 2)
        if source_table is None or referent_table is None:
            continue
        source_schema = _keyword_string(call, "source_schema")
        referent_schema = _keyword_string(call, "referent_schema")
        local_schema = _resolve_schema(source_table, source_schema, declared_schemas)
        remote_schema = _resolve_schema(referent_table, referent_schema, declared_schemas)
        if _is_cross_schema(local_schema, remote_schema):
            segment = ast.get_source_segment(source, call) or "op.create_foreign_key(...)"
            violations.append(
                MigrationViolation(
                    file,
                    f"{segment}: cross-schema foreign key: {source_table} (schema "
                    f"{local_schema}) references {referent_table} (schema {remote_schema})",
                )
            )
    return violations


def _local_table_schema(
    call: ast.Call,
    declared_schemas: dict[str, str],
) -> tuple[str, str | None]:
    """The name and resolved schema of the table a ``create_table``/``Table`` call declares."""
    name = _positional_string(call, 0)
    if name is None:
        return "", None
    schema = _table_call_schema(call)
    qualified, table = _split_table(name)
    resolved = schema if schema is not None else qualified
    if resolved is None:
        resolved = declared_schemas.get(table)
    return table, resolved


def _table_foreign_key_violations(
    file: Path,
    source: str,
    table_call: ast.Call,
    local_table: str,
    local_schema: str | None,
    declared_schemas: dict[str, str],
) -> list[MigrationViolation]:
    """Check the ``ForeignKey``/``ForeignKeyConstraint`` inside one table call."""
    violations: list[MigrationViolation] = []
    for node in ast.walk(table_call):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if name == "ForeignKey":
            remote = _positional_string(node, 0)
            if remote is None:
                continue
            remote_schema = _referent_schema(remote, declared_schemas)
            if _is_cross_schema(local_schema, remote_schema):
                segment = ast.get_source_segment(source, node) or f'ForeignKey("{remote}")'
                violations.append(
                    MigrationViolation(
                        file,
                        f"{segment}: cross-schema foreign key: {local_table} (schema "
                        f"{local_schema}) references {remote} (schema {remote_schema})",
                    )
                )
        elif name == "ForeignKeyConstraint":
            for remote in _string_list(_positional_node(node, 1)):
                remote_schema = _referent_schema(remote, declared_schemas)
                if _is_cross_schema(local_schema, remote_schema):
                    segment = ast.get_source_segment(source, node) or "ForeignKeyConstraint(...)"
                    violations.append(
                        MigrationViolation(
                            file,
                            f"{segment}: cross-schema foreign key: {local_table} (schema "
                            f"{local_schema}) references {remote} (schema {remote_schema})",
                        )
                    )
    return violations


def _migration_files(versions_dir: Path) -> list[Path]:
    """Every migration ``.py`` in ``versions_dir``, sorted for determinism."""
    if not versions_dir.is_dir():
        return []
    return sorted(file for file in versions_dir.glob("*.py") if not file.name.startswith("__"))


def _check_migration_file(
    file: Path,
    declared_schemas: dict[str, str],
) -> list[MigrationViolation]:
    """Check one migration file against the cross-schema FK rule."""
    source = file.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(file))
    except SyntaxError:
        return [MigrationViolation(file, "unparseable migration file")]
    violations: list[MigrationViolation] = []
    violations.extend(_foreign_key_violations(file, source, tree, declared_schemas))
    table_calls = list(_iter_calls(tree, "create_table")) + list(_iter_calls(tree, "Table"))
    for table_call in table_calls:
        local_table, local_schema = _local_table_schema(table_call, declared_schemas)
        if local_table:
            violations.extend(
                _table_foreign_key_violations(
                    file, source, table_call, local_table, local_schema, declared_schemas
                )
            )
    return violations


def check_migrations_fk(
    versions_dir: Path = DEFAULT_VERSIONS_DIR,
) -> tuple[MigrationViolation, ...]:
    """Check every migration under ``versions_dir`` for cross-schema foreign keys.

    Returns every violation, sorted by path then message, so the output is
    deterministic and the unit tests can assert on exact violations.
    """
    files = _migration_files(versions_dir)
    declared_schemas = _declared_table_schemas(files)
    violations: list[MigrationViolation] = []
    for file in files:
        violations.extend(_check_migration_file(file, declared_schemas))
    return tuple(sorted(violations, key=lambda v: (str(v.path), v.message)))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the cross-schema FK scan over the real migration tree; exit 1 on violations."""
    parser = argparse.ArgumentParser(
        description="Reject cross-schema foreign keys in alembic migrations (ADR-0003).",
    )
    parser.add_argument(
        "--versions-dir",
        type=Path,
        default=DEFAULT_VERSIONS_DIR,
        help=f"alembic versions directory (default: {DEFAULT_VERSIONS_DIR})",
    )
    args = parser.parse_args(argv)
    if not args.versions_dir.is_dir():
        print(f"migration FK check FAILED: {args.versions_dir} is not a directory", file=sys.stderr)
        return 1
    violations = check_migrations_fk(args.versions_dir)
    for violation in violations:
        print(f"{violation.path}: {violation.message}", file=sys.stderr)
    if violations:
        print(f"migration FK check FAILED: {len(violations)} violation(s)", file=sys.stderr)
        return 1
    print("migration FK check OK: no cross-schema foreign keys (ADR-0003)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
