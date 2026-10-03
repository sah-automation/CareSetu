"""#624: the checked-in doctor console OpenAPI slice the frontend test asserts on.

The frontend contract test builds its fixture from
``apps/frontend/src/lib/doctor/openapi-doctor-console.json`` rather than
hand-copying one, so a backend field rename cannot silently re-introduce the
wire drift that broke the doctor Patients page (#624). That guarantee only
holds while the checked-in file equals what the backend serves today, which is
what this asserts.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORTER_FILE = REPO_ROOT / "scripts" / "export_openapi_schemas.py"
FRONTEND_FIXTURE = (
    REPO_ROOT / "apps" / "frontend" / "src" / "lib" / "doctor" / "openapi-doctor-console.json"
)

REGENERATE_HINT = (
    "regenerate it with `node scripts/py.cjs scripts/export_openapi_schemas.py` "
    "and commit the result"
)


def _load_exporter():
    """Import ``scripts/export_openapi_schemas.py`` by path.

    The root ``scripts/`` directory is not an importable package (as in
    ``test_contract_check.py``), so the module is loaded by file location.
    """
    spec = importlib.util.spec_from_file_location("export_openapi_schemas", EXPORTER_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


exporter = _load_exporter()


@pytest.fixture(scope="module")
def live_spec() -> dict:
    """The OpenAPI document the app shell actually serves."""
    return exporter.load_openapi(None)


def test_checked_in_slice_matches_the_served_schema(live_spec: dict) -> None:
    # Compared as parsed documents, not as text: the repo's JSON formatter
    # reflows the file, so a byte comparison would call a formatting-only
    # change schema drift - and teach the next author to ignore a real one.
    assert FRONTEND_FIXTURE.is_file(), f"{FRONTEND_FIXTURE} is missing; {REGENERATE_HINT}"
    checked_in = json.loads(FRONTEND_FIXTURE.read_text(encoding="utf-8"))
    assert checked_in == exporter.build(live_spec), (
        f"{FRONTEND_FIXTURE.name} is stale against the backend OpenAPI document, so the "
        f"frontend contract test would assert a shape the server no longer serves; "
        f"{REGENERATE_HINT}"
    )


@pytest.mark.parametrize("name", exporter.EXPORTED_SCHEMAS)
def test_every_exported_schema_is_published(live_spec: dict, name: str) -> None:
    assert name in (live_spec.get("components", {}).get("schemas") or {})


def test_the_export_carries_no_backend_prose() -> None:
    # Descriptions are the backend docstring's job; keeping them would triple the
    # artifact and bury the shape the frontend test exists to pin.
    payload = json.loads(FRONTEND_FIXTURE.read_text(encoding="utf-8"))

    def keys(node: object) -> set[str]:
        if isinstance(node, dict):
            found = set(node)
            for value in node.values():
                found |= keys(value)
            return found
        if isinstance(node, list):
            found: set[str] = set()
            for item in node:
                found |= keys(item)
            return found
        return set()

    assert not (keys(payload) & exporter.DROPPED_KEYS)
