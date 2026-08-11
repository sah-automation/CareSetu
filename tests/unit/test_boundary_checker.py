"""PHASE-1 T6a (#26): module boundary checker - fixture tests.

Feeds throwaway module trees to ``scripts.check_module_boundaries`` and asserts
the four acceptance criteria: forbidden cross-module imports (of ``domain``/
``schema``/``adapters`` and any other non-``facade`` target) are rejected, legal
facade-only imports pass, the transport carve-out (dispatcher) is whitelisted
for outbox/schema plumbing, and the table namespace prefixes are asserted. The
real 11-module tree must pass the same gate.
"""

from pathlib import Path

import pytest
from scripts.check_module_boundaries import (
    BoundaryViolation,
    check_module_boundaries,
    check_namespace_prefixes,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "apps" / "backend"


def _write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _module(root: Path, name: str) -> None:
    """Emit a minimal hexagonal module scaffold for ``name``."""
    title = name.title()
    _write(root, f"modules/{name}/__init__.py", "")
    _write(root, f"modules/{name}/facade.py", "from __future__ import annotations\n")
    _write(root, f"modules/{name}/domain/__init__.py", "")
    _write(
        root, f"modules/{name}/domain/exceptions.py", f"class {title}Error(Exception):\n    pass\n"
    )
    _write(root, f"modules/{name}/schema/__init__.py", "")
    _write(root, f"modules/{name}/schema/models.py", "MODULE_METADATA = None\n")
    _write(root, f"modules/{name}/outbox.py", f'{name.upper()}_OUTBOX_TABLE = "{name}_outbox"\n')


def _messages(violations: tuple[BoundaryViolation, ...]) -> list[str]:
    return [violation.message for violation in violations]


def test_rejects_cross_module_domain_import(tmp_path: Path) -> None:
    _module(tmp_path, "alpha")
    _module(tmp_path, "beta")
    _write(
        tmp_path,
        "modules/beta/domain/exceptions.py",
        "from modules.alpha.domain.exceptions import AlphaError\n",
    )

    messages = _messages(check_module_boundaries(tmp_path / "modules", ()))

    assert any("alpha.domain" in message for message in messages)


@pytest.mark.parametrize(
    "import_line,subpackage",
    [
        ("from modules.beta.domain.exceptions import BetaError", "domain"),
        ("from modules.beta.schema.models import BetaModel", "schema"),
        ("from modules.beta.adapters import BetaRouter", "adapters"),
        ("from modules.beta.outbox import BETA_OUTBOX_TABLE", "outbox"),
        ("import modules.beta", "module package"),
    ],
)
def test_rejects_each_forbidden_cross_module_target(
    tmp_path: Path, import_line: str, subpackage: str
) -> None:
    _module(tmp_path, "alpha")
    _module(tmp_path, "beta")
    _write(
        tmp_path, "modules/alpha/facade.py", f"from __future__ import annotations\n{import_line}\n"
    )

    messages = _messages(check_module_boundaries(tmp_path / "modules", ()))

    assert any(subpackage in message for message in messages)


def test_allows_facade_only_and_intra_module_imports(tmp_path: Path) -> None:
    _module(tmp_path, "alpha")
    _module(tmp_path, "beta")
    _write(
        tmp_path,
        "modules/alpha/facade.py",
        "from __future__ import annotations\n"
        "from modules.beta.facade import BetaFacade\n"
        "import modules.beta.facade as beta_facade\n"
        "from modules.alpha.domain.exceptions import AlphaError\n",
    )

    assert check_module_boundaries(tmp_path / "modules", ()) == ()


def test_transport_carve_out_allows_schema_plumbing(tmp_path: Path) -> None:
    _module(tmp_path, "consent")
    _write(
        tmp_path,
        "bus/dispatcher.py",
        "from modules.consent.schema.models import MODULE_METADATA\n"
        "from modules.consent.outbox import CONSENT_OUTBOX_TABLE\n",
    )

    assert check_module_boundaries(tmp_path / "modules", (tmp_path / "bus",)) == ()


def test_transport_carve_out_still_rejects_domain(tmp_path: Path) -> None:
    _module(tmp_path, "consent")
    _write(
        tmp_path,
        "bus/dispatcher.py",
        "from modules.consent.domain.exceptions import ConsentError\n",
    )

    messages = _messages(check_module_boundaries(tmp_path / "modules", (tmp_path / "bus",)))

    assert any("consent.domain" in message for message in messages)


def test_namespace_prefixes_pass(tmp_path: Path) -> None:
    _module(tmp_path, "consent")
    _write(
        tmp_path,
        "modules/consent/schema/models.py",
        "from sqlalchemy import BigInteger, Column, MetaData, Table\n"
        'MODULE_METADATA = MetaData(schema="consent")\n'
        "consent_consents = Table(\n"
        '    "consent_consents", MODULE_METADATA,\n'
        '    Column("id", BigInteger, primary_key=True),\n'
        ")\n",
    )

    assert check_namespace_prefixes(tmp_path / "modules") == ()


def test_table_without_module_prefix_rejected(tmp_path: Path) -> None:
    _module(tmp_path, "consent")
    _write(
        tmp_path,
        "modules/consent/schema/models.py",
        "from sqlalchemy import BigInteger, Column, MetaData, Table\n"
        'MODULE_METADATA = MetaData(schema="consent")\n'
        "stray_table = Table(\n"
        '    "stray_table", MODULE_METADATA,\n'
        '    Column("id", BigInteger, primary_key=True),\n'
        ")\n",
    )

    messages = _messages(check_namespace_prefixes(tmp_path / "modules"))

    assert any("stray_table" in message and "prefix" in message for message in messages)


def test_metadata_schema_mismatch_rejected(tmp_path: Path) -> None:
    _module(tmp_path, "consent")
    _write(
        tmp_path,
        "modules/consent/schema/models.py",
        'from sqlalchemy import MetaData\nMODULE_METADATA = MetaData(schema="other_schema")\n',
    )

    messages = _messages(check_namespace_prefixes(tmp_path / "modules"))

    assert any("other_schema" in message and "!= module consent" in message for message in messages)


def test_outbox_table_name_mismatch_rejected(tmp_path: Path) -> None:
    _module(tmp_path, "consent")
    _write(tmp_path, "modules/consent/outbox.py", 'CONSENT_OUTBOX_TABLE = "wrong_name"\n')

    messages = _messages(check_namespace_prefixes(tmp_path / "modules"))

    assert any("consent_outbox" in message for message in messages)


def test_missing_outbox_constant_rejected(tmp_path: Path) -> None:
    _module(tmp_path, "consent")
    _write(tmp_path, "modules/consent/outbox.py", "from __future__ import annotations\n")

    messages = _messages(check_namespace_prefixes(tmp_path / "modules"))

    assert any("CONSENT_OUTBOX_TABLE" in message for message in messages)


def test_typed_outbox_constant_accepted(tmp_path: Path) -> None:
    _module(tmp_path, "consent")
    _write(
        tmp_path,
        "modules/consent/outbox.py",
        'CONSENT_OUTBOX_TABLE: str = "consent_outbox"\n',
    )

    assert check_namespace_prefixes(tmp_path / "modules") == ()


def test_real_module_tree_passes() -> None:
    violations = check_module_boundaries(
        BACKEND_ROOT / "modules",
        (BACKEND_ROOT / "bus", BACKEND_ROOT / "alembic"),
    )

    assert violations == ()
