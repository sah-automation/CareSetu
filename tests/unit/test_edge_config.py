"""PHASE-1 T8a (#31): edge reverse-proxy scaffold lint - fixture tests.

Feeds throwaway Caddyfiles to ``scripts.check_edge_config`` and asserts the
acceptance criteria: the Caddyfile must exist and be non-empty, its braces must
balance, the site block must use the ``{$STAGING_DOMAIN:...}`` env
substitution (no hardcoded staging hostname), ``/api/*`` must reverse-proxy to
the FastAPI backend on ``127.0.0.1:8000``, the default ``handle`` must
reverse-proxy to the Next.js frontend on ``127.0.0.1:3000``, the
``Strict-Transport-Security`` header must be set (TLS termination boundary),
and no unsubstituted placeholders may remain. The real committed
``deploy/edge/Caddyfile`` must pass the same gate.
"""

from pathlib import Path

from scripts.check_edge_config import (
    DEFAULT_CADDYFILE,
    EdgeViolation,
    check_edge_config,
)


def _write(root: Path, content: str) -> Path:
    path = root / "Caddyfile"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _messages(violations: tuple[EdgeViolation, ...]) -> list[str]:
    return [violation.message for violation in violations]


def _valid() -> str:
    return """{$STAGING_DOMAIN:staging.caresetu.example} {
\tencode zstd gzip

\tlog {
\t\toutput stdout
\t\tformat json
\t}

\theader {
\t\tStrict-Transport-Security "max-age=31536000"
\t\tX-Content-Type-Options "nosniff"
\t\t-Server
\t}

\thandle /api/* {
\t\treverse_proxy 127.0.0.1:8000
\t}

\thandle {
\t\treverse_proxy 127.0.0.1:3000
\t}
}
"""


def test_valid_fixture_passes(tmp_path: Path) -> None:
    caddyfile = _write(tmp_path, _valid())

    assert check_edge_config(caddyfile) == ()


def test_real_caddyfile_passes() -> None:
    violations = check_edge_config(DEFAULT_CADDYFILE)

    assert violations == ()


def test_missing_file_violation(tmp_path: Path) -> None:
    missing = tmp_path / "nope" / "Caddyfile"

    messages = _messages(check_edge_config(missing))

    assert any("missing" in message for message in messages)


def test_empty_file_violation(tmp_path: Path) -> None:
    caddyfile = _write(tmp_path, "  \n\n")

    messages = _messages(check_edge_config(caddyfile))

    assert any("empty Caddyfile" in message for message in messages)


def test_hardcoded_site_address_rejected(tmp_path: Path) -> None:
    caddyfile = _write(
        tmp_path,
        _valid().replace("{$STAGING_DOMAIN:staging.caresetu.example}", "staging.caresetu.in"),
    )

    messages = _messages(check_edge_config(caddyfile))

    assert any("env substitution" in message for message in messages)


def test_missing_site_block_rejected(tmp_path: Path) -> None:
    caddyfile = _write(tmp_path, "reverse_proxy 127.0.0.1:8000\n")

    messages = _messages(check_edge_config(caddyfile))

    assert any("exactly one site block" in message for message in messages)


def test_two_site_blocks_rejected(tmp_path: Path) -> None:
    caddyfile = _write(
        tmp_path,
        "{$STAGING_DOMAIN:a.example} { reverse_proxy 127.0.0.1:8000 }\n"
        "{$STAGING_DOMAIN:b.example} { reverse_proxy 127.0.0.1:8000 }\n",
    )

    messages = _messages(check_edge_config(caddyfile))

    assert any("exactly one site block" in message for message in messages)


def test_unbalanced_braces_rejected(tmp_path: Path) -> None:
    caddyfile = _write(tmp_path, "{$STAGING_DOMAIN:a.example} {\n")

    messages = _messages(check_edge_config(caddyfile))

    assert any("braces" in message or "missing" in message for message in messages)


def test_placeholder_rejected(tmp_path: Path) -> None:
    caddyfile = _write(tmp_path, _valid().replace("Strict-Transport-Security", "CHANGE_ME"))

    messages = _messages(check_edge_config(caddyfile))

    assert any("placeholder" in message and "CHANGE_ME" in message for message in messages)


def test_example_com_placeholder_rejected(tmp_path: Path) -> None:
    caddyfile = _write(tmp_path, _valid() + "# TODO route to example.com\n")

    messages = _messages(check_edge_config(caddyfile))

    assert any("placeholder" in message and "example.com" in message for message in messages)


def test_wrong_backend_target_rejected(tmp_path: Path) -> None:
    caddyfile = _write(
        tmp_path,
        _valid().replace("reverse_proxy 127.0.0.1:8000", "reverse_proxy 127.0.0.1:9000"),
    )

    messages = _messages(check_edge_config(caddyfile))

    assert any("127.0.0.1:8000" in message for message in messages)


def test_missing_backend_handle_rejected(tmp_path: Path) -> None:
    caddyfile = _write(
        tmp_path,
        _valid().replace(
            "\thandle /api/* {\n\t\treverse_proxy 127.0.0.1:8000\n\t}\n",
            "\thandle /health {\n\t\treverse_proxy 127.0.0.1:8000\n\t}\n",
        ),
    )

    messages = _messages(check_edge_config(caddyfile))

    assert any("/api/* handle" in message for message in messages)


def test_wrong_frontend_target_rejected(tmp_path: Path) -> None:
    caddyfile = _write(
        tmp_path,
        _valid().replace("reverse_proxy 127.0.0.1:3000", "reverse_proxy 127.0.0.1:4000"),
    )

    messages = _messages(check_edge_config(caddyfile))

    assert any("127.0.0.1:3000" in message for message in messages)


def test_missing_frontend_handle_rejected(tmp_path: Path) -> None:
    caddyfile = _write(tmp_path, _valid().replace("\n\thandle {\n", "\n\thandle /operator/* {\n"))

    messages = _messages(check_edge_config(caddyfile))

    assert any("default handle" in message for message in messages)


def test_missing_hsts_rejected(tmp_path: Path) -> None:
    caddyfile = _write(
        tmp_path,
        _valid().replace('Strict-Transport-Security "max-age=31536000"\n', ""),
    )

    messages = _messages(check_edge_config(caddyfile))

    assert any("Strict-Transport-Security" in message for message in messages)
