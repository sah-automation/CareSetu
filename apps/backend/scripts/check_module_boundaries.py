"""PHASE-1 T6a (#26): machine-enforced module isolation (ADR-0003).

Walks the module import graph and rejects module-to-module imports of
``domain``/``schema``/``adapters`` (and of any other non-``facade`` cross-module
target); allows cross-module imports only via ``facade.py``; whitelists the
transport carve-out (the dispatcher in ``bus/`` and the migration harness in
``alembic/``) for outbox/schema plumbing only (ADR-0003 §3); and asserts the
table namespace prefixes (``consent_consents``, ``care_prescriptions``, ...)
plus the per-module outbox table name (coding-standards §2).

The gate is deliberately strict about *how* facade access is spelled: only the
fully-qualified ``modules.<module>.facade`` form is legal. A package-root
import such as ``import modules.consent`` or ``from modules.consent import
facade`` loads the module package itself and is rejected, so a stray symbol
smuggled through ``__init__`` cannot slip past the facade-only rule.

Stdlib-only by design: this gate is what keeps the module tree importable in
the first place, so it must run on a bare interpreter in pre-commit and CI
without the backend's third-party dependencies installed.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
MODULES_PACKAGE_NAME = "modules"
DEFAULT_MODULES_PACKAGE = BACKEND_ROOT / MODULES_PACKAGE_NAME
DEFAULT_CARVE_OUT_RELATIVE_ROOTS = ("bus", "alembic")
DEFAULT_CARVE_OUT_ROOTS = tuple(BACKEND_ROOT / root for root in DEFAULT_CARVE_OUT_RELATIVE_ROOTS)
SCHEMA_PLUMBING_PACKAGES = ("schema", "outbox")


@dataclass(frozen=True)
class BoundaryViolation:
    """One rule break: an illegal import or a namespace-prefix violation."""

    path: Path
    message: str


def _module_names(modules_package: Path) -> tuple[str, ...]:
    """Sorted names of the module packages directly under ``modules_package``."""
    return tuple(
        sorted(
            entry.name
            for entry in modules_package.iterdir()
            if entry.is_dir() and entry.name != "__pycache__" and not entry.name.startswith(".")
        )
    )


def _iter_checked_files(
    modules_package: Path,
    carve_out_roots: Sequence[Path],
) -> Iterable[tuple[Path, str | None, bool]]:
    """Yield ``(file, current_module, is_carve_out)`` for every ``.py`` file to check.

    ``current_module`` is ``None`` for transport files that belong to no module.
    """
    for module_name in _module_names(modules_package):
        for file in (modules_package / module_name).rglob("*.py"):
            if "__pycache__" in file.parts:
                continue
            yield file, module_name, False
    for root in carve_out_roots:
        for file in root.rglob("*.py"):
            if "__pycache__" in file.parts:
                continue
            yield file, None, True


def _import_specs(tree: ast.Module) -> Iterable[tuple[ast.Import | ast.ImportFrom, int, list[str]]]:
    """Yield ``(node, level, dotted_parts)`` for every import statement.

    ``level`` is the relative-import level (0 = absolute). For ``from X import
    a`` both ``X`` and ``X.a`` are yielded so a bare attribute import cannot
    smuggle a module reference past the gate.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node, 0, alias.name.split(".")
        elif isinstance(node, ast.ImportFrom):
            parts = node.module.split(".") if node.module else []
            for alias in node.names:
                yield node, node.level, [*parts, alias.name]
            yield node, node.level, parts


def _resolve_candidates(
    level: int, parts: list[str], package_parts: list[str]
) -> Iterable[list[str]]:
    """Turn one import spec into absolute dotted paths (relative imports resolved)."""
    if level == 0:
        yield list(parts)
        return
    backup = max(0, len(package_parts) - (level - 1))
    yield package_parts[:backup] + parts


def _deepest_existing_module(
    parts: Sequence[str],
    modules_package: Path,
    package_name: str,
) -> list[str] | None:
    """The longest prefix of ``parts`` naming an existing package or module file.

    ``None`` when ``parts`` does not resolve into the module tree at all (a
    non-module import, or the ``modules`` package root itself).
    """
    if len(parts) < 2 or parts[0] != package_name:
        return None
    for end in range(len(parts), 1, -1):
        relative = list(parts[1:end])
        module_file = modules_package.joinpath(*relative).with_suffix(".py")
        if module_file.is_file():
            return list(parts[:end])
        package_dir = modules_package.joinpath(*relative)
        if package_dir.is_dir() and (package_dir / "__init__.py").is_file():
            return list(parts[:end])
    return None


def _violation_message(
    parts: Sequence[str],
    current_module: str | None,
    is_carve_out: bool,
    package_name: str,
) -> str | None:
    """The rule violation for one resolved import target, or ``None`` when legal."""
    rest = list(parts[1:])
    if not rest:
        return None
    target_module = rest[0]
    if target_module == current_module:
        return None
    sub = rest[1:]
    if not sub:
        return f"module package import is not facade-only: {'.'.join(parts)}"
    if sub[0] == "facade":
        return None
    if is_carve_out and sub[0] in SCHEMA_PLUMBING_PACKAGES:
        return None
    return f"forbidden cross-module import of {package_name}.{target_module}.{sub[0]}"


def _check_file_imports(
    file: Path,
    tree: ast.Module,
    source: str,
    package_parts: list[str],
    current_module: str | None,
    is_carve_out: bool,
    modules_package: Path,
    package_name: str,
) -> list[BoundaryViolation]:
    """Check every import in one file against the isolation rule."""
    violations: list[BoundaryViolation] = []
    seen: set[tuple[str, str]] = set()
    for node, level, parts in _import_specs(tree):
        for candidate in _resolve_candidates(level, parts, package_parts):
            resolved = _deepest_existing_module(candidate, modules_package, package_name)
            if resolved is None:
                continue
            message = _violation_message(resolved, current_module, is_carve_out, package_name)
            if message is None:
                continue
            segment = ast.get_source_segment(source, node) or ".".join(resolved)
            if (message, segment) in seen:
                continue
            seen.add((message, segment))
            violations.append(BoundaryViolation(file, f"{segment}: {message}"))
    return violations


def _package_parts(file: Path, modules_package: Path, package_name: str) -> list[str] | None:
    """The ``__package__`` name parts for ``file``, for resolving relative imports.

    ``None`` for files outside the module tree (transport), whose relative
    imports resolve against their own package and are not module imports.
    """
    try:
        relative = file.relative_to(modules_package)
    except ValueError:
        return None
    return [package_name, *relative.parts[:-1]]


def check_module_boundaries(
    modules_package: Path = DEFAULT_MODULES_PACKAGE,
    carve_out_roots: Sequence[Path] = DEFAULT_CARVE_OUT_ROOTS,
    package_name: str = MODULES_PACKAGE_NAME,
) -> tuple[BoundaryViolation, ...]:
    """Check the import graph and namespace prefixes of ``modules_package``.

    Returns every violation, sorted by path then message, so the output is
    deterministic and the unit tests can assert on exact violations.
    """
    violations: list[BoundaryViolation] = []
    for file, current_module, is_carve_out in _iter_checked_files(modules_package, carve_out_roots):
        source = file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(file))
        except SyntaxError:
            violations.append(BoundaryViolation(file, "unparseable python file"))
            continue
        package_parts = _package_parts(file, modules_package, package_name)
        violations.extend(
            _check_file_imports(
                file,
                tree,
                source,
                [] if package_parts is None else package_parts,
                current_module,
                is_carve_out,
                modules_package,
                package_name,
            )
        )
    violations.extend(check_namespace_prefixes(modules_package))
    return _sorted_violations(violations)


def _sorted_violations(
    violations: Sequence[BoundaryViolation],
) -> tuple[BoundaryViolation, ...]:
    """Sort violations by path then message so the gate's output is deterministic."""
    return tuple(sorted(violations, key=lambda v: (str(v.path), v.message)))


def _call_name(func: ast.expr) -> str | None:
    """The dotted-tail name of a call target (``Table``, ``sqlalchemy.Table``)."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _iter_calls(tree: ast.Module, name: str) -> Iterable[ast.Call]:
    """Yield ``Call`` nodes whose target name is ``name``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node.func) == name:
            yield node


def _constant_string(node: ast.AST | None) -> str | None:
    """The value of ``node`` when it is a string literal, else ``None``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _table_name_violations(
    module_name: str,
    models_file: Path,
    source: str,
    tree: ast.Module,
) -> list[BoundaryViolation]:
    """Assert every ``Table`` declared in ``models_file`` carries the module prefix."""
    prefix = f"{module_name}_"
    violations: list[BoundaryViolation] = []
    for call in _iter_calls(tree, "Table"):
        name = _constant_string(call.args[0]) if call.args else None
        if name is None:
            segment = ast.get_source_segment(source, call) or "Table(...)"
            violations.append(
                BoundaryViolation(models_file, f"{segment}: table name must be a static string")
            )
            continue
        if not name.startswith(prefix):
            segment = ast.get_source_segment(source, call) or f'Table("{name}", ...)'
            violations.append(
                BoundaryViolation(models_file, f"{segment}: table {name} lacks the {prefix} prefix")
            )
    return violations


def _metadata_schema_violations(
    module_name: str,
    models_file: Path,
    source: str,
    tree: ast.Module,
) -> list[BoundaryViolation]:
    """Assert every ``MetaData`` schema literal in ``models_file`` is the module's own."""
    violations: list[BoundaryViolation] = []
    for call in _iter_calls(tree, "MetaData"):
        schema_node: ast.AST | None = None
        for keyword in call.keywords:
            if keyword.arg == "schema":
                schema_node = keyword.value
        if schema_node is None and call.args:
            schema_node = call.args[0]
        schema = _constant_string(schema_node)
        if schema is not None and schema != module_name:
            segment = ast.get_source_segment(source, call) or "MetaData(...)"
            violations.append(
                BoundaryViolation(
                    models_file,
                    f"{segment}: MetaData schema {schema} != module {module_name}",
                )
            )
    return violations


def _outbox_constant_violations(
    module_name: str,
    outbox_file: Path,
    source: str,
    tree: ast.Module,
) -> list[BoundaryViolation]:
    """Assert ``outbox.py`` declares the module's outbox table name contract."""
    constant_name = f"{module_name.upper()}_OUTBOX_TABLE"
    expected = f"{module_name}_outbox"
    violations: list[BoundaryViolation] = []
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets: Sequence[ast.expr] = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        else:
            continue
        for target in targets:
            if not isinstance(target, ast.Name) or target.id != constant_name:
                continue
            found = True
            value = _constant_string(node.value)
            if value != expected:
                segment = ast.get_source_segment(source, node) or f"{constant_name} = ..."
                violations.append(
                    BoundaryViolation(
                        outbox_file,
                        f"{segment}: outbox table name must be {expected}",
                    )
                )
    if not found:
        violations.append(BoundaryViolation(outbox_file, f"missing {constant_name} = {expected}"))
    return violations


def check_namespace_prefixes(
    modules_package: Path = DEFAULT_MODULES_PACKAGE,
) -> tuple[BoundaryViolation, ...]:
    """Assert table namespace prefixes and the outbox table name for every module."""
    violations: list[BoundaryViolation] = []
    for module_name in _module_names(modules_package):
        models_file = modules_package / module_name / "schema" / "models.py"
        if models_file.is_file():
            source = models_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(models_file))
            violations.extend(_table_name_violations(module_name, models_file, source, tree))
            violations.extend(_metadata_schema_violations(module_name, models_file, source, tree))
        outbox_file = modules_package / module_name / "outbox.py"
        if outbox_file.is_file():
            source = outbox_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(outbox_file))
            violations.extend(_outbox_constant_violations(module_name, outbox_file, source, tree))
    return _sorted_violations(violations)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the boundary check over the real backend tree; exit 1 on violations."""
    parser = argparse.ArgumentParser(
        description="Enforce the module isolation rule (ADR-0003, coding-standards §2).",
    )
    parser.add_argument(
        "--modules-package",
        type=Path,
        default=DEFAULT_MODULES_PACKAGE,
        help=f"path to the modules package (default: {DEFAULT_MODULES_PACKAGE})",
    )
    parser.add_argument(
        "--carve-out",
        type=Path,
        action="append",
        default=None,
        help="transport carve-out root to whitelist (repeatable); default: bus/ and alembic/",
    )
    args = parser.parse_args(argv)
    if not args.modules_package.is_dir():
        print(f"boundary check FAILED: {args.modules_package} is not a directory", file=sys.stderr)
        return 1
    carve_out_roots = tuple(args.carve_out) if args.carve_out else DEFAULT_CARVE_OUT_ROOTS
    violations = check_module_boundaries(args.modules_package, carve_out_roots)
    for violation in violations:
        print(f"{violation.path}: {violation.message}", file=sys.stderr)
    if violations:
        print(f"boundary check FAILED: {len(violations)} violation(s)", file=sys.stderr)
        return 1
    print("boundary check OK: module isolation holds (ADR-0003)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
