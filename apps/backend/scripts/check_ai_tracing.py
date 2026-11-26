"""AI-gateway Langfuse tracing gate (ai-engineering-standards A7).

Every LLM call must flow through the ``MOD-005`` AI gateway port and be traced
via Langfuse (``@observe`` from ``observability.langfuse_client``).  This gate
makes that a machine rule: a concrete method on any ``MOD-005`` class whose name
marks it as the AI boundary (class name contains ``gateway``, ``provider``,
``llm``, or a standalone ``ai`` token) must reference ``@observe`` or the
``langfuse`` client, or the build fails.

Deliberately narrow to avoid false positives:

- Scans only ``apps/backend/modules/intake/`` (where the LLM client lives per
  third-party-integration-standards §2, and where A6 places the gateway port).
- Only class names that *read* like the AI boundary are checked; a facade,
  outbox, or domain class is never flagged.
- Abstract stubs (a method body of ``...`` / ``pass`` / ``raise
  NotImplementedError``) are exempt - the port's interface can be declared
  before the concrete provider implements it.
- ``_private`` helpers are exempt: the public method's span covers them.
  ``@property`` and ``@staticmethod`` accessors are exempt (no LLM call).
- When run with no files (repo-wide, as pre-commit does) it scans the whole
  tracked tree under the intake module.  When files are passed explicitly it
  scans exactly those, so the unit tests can feed throwaway fixtures.

Stdlib-only by design: like the other ``check_*.py`` gates, this runs on a bare
interpreter in pre-commit and CI without third-party dependencies.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess  # nosec B404 - git enumeration with a fixed argv list, no shell
import sys
from dataclasses import dataclass
from pathlib import Path

# A class name that marks a file/class as the AI boundary of MOD-005.
_GATEWAY_CLASS_RE = re.compile(r"gateway|provider|llm|\bai\b", re.IGNORECASE)
# Body references that count as tracing the call (A7).  ``@observe`` is checked
# separately on the decorator list.
_TRACING_BODY_HINTS = frozenset({"langfuse", "get_langfuse_client"})
_OBSERVE_DECORATOR = "observe"

_BACKEND_PACKAGE = Path(__file__).resolve().parents[1]
_INTAKE_DIR = _BACKEND_PACKAGE / "modules" / "intake"


@dataclass(frozen=True)
class AiTracingViolation:
    """One concrete, untraced method on an AI-boundary class of MOD-005."""

    path: Path
    line: int
    method: str
    class_name: str


def _is_gateway_class(name: str) -> bool:
    return _GATEWAY_CLASS_RE.search(name) is not None


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_ellipsis_stmt(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and node.value.value is Ellipsis
    )


def _is_not_implemented_raise(node: ast.stmt) -> bool:
    if not isinstance(node, ast.Raise) or not isinstance(node.exc, (ast.Call, ast.Name)):
        return False
    target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
    return isinstance(target, ast.Name) and target.id == "NotImplementedError"


def _is_stub_body(body: list[ast.stmt]) -> bool:
    """True when the method body declares an interface without doing work."""
    statements = [node for node in body if not _is_docstring(node)]
    return all(
        isinstance(node, ast.Pass) or _is_ellipsis_stmt(node) or _is_not_implemented_raise(node)
        for node in statements
    )


def _decorator_name(decorator: ast.expr) -> str | None:
    target: ast.expr = decorator
    if isinstance(decorator, ast.Call):
        target = decorator.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _is_exempt_decorator(name: str | None) -> bool:
    return name in {"property", "staticmethod"}


def _has_observe(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_decorator_name(d) == _OBSERVE_DECORATOR for d in method.decorator_list)


def _references_client(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    names = {node.id for node in ast.walk(method) if isinstance(node, ast.Name)}
    return bool(names & _TRACING_BODY_HINTS)


def _check_method(
    path: Path, class_node: ast.ClassDef, method: ast.FunctionDef | ast.AsyncFunctionDef
) -> AiTracingViolation | None:
    """Flag ``method`` when it is a concrete, non-exempt AI-boundary method that
    is not Langfuse-traced."""
    if method.name.startswith("_"):
        return None
    if _is_stub_body(method.body):
        return None
    if any(_is_exempt_decorator(_decorator_name(d)) for d in method.decorator_list):
        return None
    if _has_observe(method) or _references_client(method):
        return None
    return AiTracingViolation(
        path=path,
        line=method.lineno,
        method=method.name,
        class_name=class_node.name,
    )


def scan_file(path: Path) -> list[AiTracingViolation]:
    """Concrete AI-boundary methods in ``path`` that skip Langfuse tracing."""
    if path.suffix != ".py":
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return []
    violations: list[AiTracingViolation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not _is_gateway_class(node.name):
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                violation = _check_method(path, node, child)
                if violation is not None:
                    violations.append(violation)
    return violations


def check_ai_tracing(files: list[Path]) -> tuple[AiTracingViolation, ...]:
    """Every untraced AI-boundary method across ``files``."""
    violations = [violation for path in files for violation in scan_file(path)]
    return tuple(sorted(violations, key=lambda v: (str(v.path), v.line, v.class_name, v.method)))


def _tracked_repo_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(  # nosec B603 B607 - hardcoded argv, no shell, no user input
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.decode("utf-8", "replace"))
    files: list[Path] = []
    for raw in result.stdout.split(b"\x00"):
        if raw:
            path = repo_root / raw.decode("utf-8", "replace")
            if path.is_file():
                files.append(path)
    return files


def _is_intake_file(intake_root: Path, path: Path) -> bool:
    return path.is_file() and path.suffix == ".py" and path.is_relative_to(intake_root)


def _tracked_intake_files(repo_root: Path) -> list[Path]:
    intake_root = repo_root / "apps" / "backend" / "modules" / "intake"
    if not intake_root.is_dir():
        return []
    return [path for path in _tracked_repo_files(repo_root) if _is_intake_file(intake_root, path)]


def main(argv: list[str] | None = None) -> int:
    """Scan the given files (or the whole tracked intake tree when none); exit 1
    when an AI-boundary method is untraced."""
    parser = argparse.ArgumentParser(
        description="Scan MOD-005 for AI-gateway methods that skip Langfuse tracing (A7).",
    )
    parser.add_argument("files", nargs="*", type=Path, help="files to scan")
    args = parser.parse_args(argv)
    files = [path for path in args.files if path.is_file()]
    if not args.files:
        files = _tracked_intake_files(Path.cwd())
    violations = check_ai_tracing(files)
    for violation in violations:
        print(
            f"{violation.path}:{violation.line}: method {violation.method!r} on "
            f"AI-boundary class {violation.class_name!r} in MOD-005 is not Langfuse-"
            f"traced: add @observe or reference get_langfuse_client "
            f"(ai-engineering-standards A7)",
            file=sys.stderr,
        )
    if violations:
        print(
            f"ai-tracing check FAILED: {len(violations)} untraced method(s)",
            file=sys.stderr,
        )
        return 1
    print("ai-tracing check OK: no untraced AI-boundary methods in MOD-005")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
