"""MOD-012: export named OpenAPI component schemas to a file the frontend reads.

Ticket #624: the doctor console's frontend guards drifted from the backend's
serialised DTOs, and the drift shipped green because every page suite mocks the
transport module away, so no test ever executed the guards against a real body.

The frontend contract test therefore builds its fixture from the backend's
published OpenAPI schema rather than hand-copying one, and needs that schema
available in a language it can read. This script is the bridge: it reads the
schema the running app serves (``/openapi.json`` or in-process from
``app.main``) and writes the component schemas named below to a checked-in JSON
file. ``tests/unit/test_doctor_openapi_slice.py`` asserts the checked-in copy
still equals a freshly generated one, so a backend field rename fails the
backend suite instead of silently re-introducing the drift.

The exported slice is deliberately small and explicit - the doctor console
Patients DTOs, the doctor cases projection, the consent read models, and the
health DTOs the detail view embeds. Widening it is a one-line change here, not
a new script.

Usage:
    node scripts/py.cjs scripts/export_openapi_schemas.py
    node scripts/py.cjs scripts/export_openapi_schemas.py --openapi http://localhost:8000/openapi.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TypeAlias

JsonValue: TypeAlias = "bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None"

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "apps" / "backend"
DEFAULT_OUT = (
    REPO_ROOT / "apps" / "frontend" / "src" / "lib" / "doctor" / "openapi-doctor-console.json"
)

REF_PREFIX = "#/components/schemas/"

# The doctor console Patients DTOs (MOD-012) plus the health DTOs the detail view
# embeds, the doctor cases projection (#646), and the consent read models (#648).
# Names must match `class` names in modules/doctor/doctor_models.py,
# modules/health/facade.py, and modules/consent/facade.py; a rename on either
# side makes the export fail loudly.
EXPORTED_SCHEMAS: tuple[str, ...] = (
    "CaseWorkspaceLink",
    "ConsentView",
    "ContactSection",
    "DoctorCaseRow",
    "DoctorCasesListView",
    "DoctorPatientDetailView",
    "DoctorPatientRow",
    "EgressLogEntry",
    "HealthBackground",
    "HealthBackgroundView",
    "PatientsListView",
    "RecordEntryView",
    "RecordTimeline",
)

# Keys dropped on the way out. `description` is the backend docstring, which
# belongs next to the code it documents; `title` is Pydantic's field-name echo.
# Both would triple the artifact's size and bury the shape this file exists to
# pin. Everything the frontend needs to build and check a body survives.
DROPPED_KEYS: frozenset[str] = frozenset({"description", "title"})

# A schema fetch that hangs is worse than one that fails: the exporter is a
# dev/CI gate, so a bounded wait is the behaviour we want. Named because the
# value is a policy, not a fact about urlopen.
HTTP_TIMEOUT_SECONDS = 30


class SchemaExportError(RuntimeError):
    """A named schema is absent from the OpenAPI document."""


def load_openapi(source: str | None) -> dict[str, JsonValue]:
    """The OpenAPI schema: fetched from a URL, read from a file, or generated."""
    if source is None:
        return _generate_openapi()
    if source.startswith("http://") or source.startswith("https://"):
        import urllib.request

        with urllib.request.urlopen(source, timeout=HTTP_TIMEOUT_SECONDS) as response:  # nosec B310 - dev-only CLI; the URL is a fixed CI/localhost value, never user input, and urllib keeps the exporter stdlib-only
            return json.loads(response.read().decode("utf-8"))
    path = Path(source)
    if not path.is_file():
        raise SchemaExportError(f"OpenAPI source not found: {source}")
    return json.loads(path.read_text(encoding="utf-8"))


def _generate_openapi() -> dict[str, JsonValue]:
    """Build the OpenAPI document in-process from the app shell (local default)."""
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    import app.main  # type: ignore[import-not-found]

    return app.main.app.openapi()


def select_schemas(spec: dict[str, JsonValue], names: Sequence[str]) -> dict[str, JsonValue]:
    """Return the named component schemas, in the order given, or raise."""
    components = (spec.get("components") or {}).get("schemas") or {}
    missing = [name for name in names if name not in components]
    if missing:
        raise SchemaExportError(
            "these component schemas are absent from the OpenAPI document, "
            "which usually means a backend DTO was renamed: " + ", ".join(missing)
        )
    return {name: components[name] for name in names}


def strip_noise(node: JsonValue) -> JsonValue:
    """Drop ``description``/``title`` keys at every depth, keeping the shape."""
    if isinstance(node, dict):
        return {key: strip_noise(value) for key, value in node.items() if key not in DROPPED_KEYS}
    if isinstance(node, list):
        return [strip_noise(item) for item in node]
    return node


def build(
    spec: dict[str, JsonValue], names: Sequence[str] = EXPORTED_SCHEMAS
) -> dict[str, JsonValue]:
    """The exported slice as a dict - the shape any comparison should use.

    Compare parsed documents, never serialised text: the destination is run
    through the repo's JSON formatter, so a byte comparison would report a
    formatting-only change as schema drift.
    """
    return {"schemas": strip_noise(select_schemas(spec, names))}


def render(spec: dict[str, JsonValue], names: Sequence[str] = EXPORTED_SCHEMAS) -> str:
    """Serialise the exported slice deterministically, for a diffable file."""
    return json.dumps(build(spec, names), indent=2, sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Write the exported schemas to ``--out``; exit 0 on success."""
    parser = argparse.ArgumentParser(
        description="Export named backend OpenAPI component schemas to JSON "
        "for the frontend doctor console contract test (#624).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"destination JSON file (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--openapi",
        default=None,
        help="OpenAPI schema: a URL, a local JSON file, or omitted to generate from app.main",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 when the destination file is stale",
    )
    args = parser.parse_args(argv)

    try:
        spec = load_openapi(args.openapi)
        expected = build(spec)
    except (SchemaExportError, OSError, json.JSONDecodeError) as exc:
        print(f"schema export FAILED: {exc}", file=sys.stderr)
        return 1

    if args.check:
        try:
            current = json.loads(args.out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = None
        if current != expected:
            print(
                f"schema export FAILED: {args.out} is stale; regenerate it with\n"
                f"  node scripts/py.cjs scripts/export_openapi_schemas.py",
                file=sys.stderr,
            )
            return 1
        print(f"schema export OK: {args.out} matches the backend OpenAPI document")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(spec), encoding="utf-8")
    print(f"schema export OK: wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
