"""PHASE-1 T8a (#31): edge reverse-proxy scaffold lint.

Lints ``deploy/edge/Caddyfile`` - the reverse proxy that terminates TLS at the
staging VM perimeter. The ``caddy`` binary is not installed locally or in CI,
so "config validates" is a deterministic lint pass: the Caddyfile is parsed
structurally and the staging boundary contract is asserted:

- the file exists, is non-empty, and its braces balance;
- exactly one site block whose address is the ``{$STAGING_DOMAIN:...}``
  environment-substituted form (no hardcoded staging hostname committed);
- ``/api/*`` is reverse-proxied to the FastAPI backend on ``127.0.0.1:8000``;
- the default ``handle`` block is reverse-proxied to the Next.js frontend on
  ``127.0.0.1:3000``;
- the ``Strict-Transport-Security`` header is set (TLS termination boundary);
- no unsubstituted placeholders remain (``CHANGE_ME``, ``example.com``, ...).

The edge (reverse proxy at the VM perimeter) is distinct from the in-app
gateway (FastAPI middleware) - see the CONTEXT.md glossary.

Stdlib-only by design: like the module boundary checker, this gate runs on a
bare interpreter in pre-commit and CI without third-party dependencies.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CADDYFILE = REPO_ROOT / "deploy" / "edge" / "Caddyfile"

SITE_ADDRESS_PREFIX = "{$STAGING_DOMAIN"
BACKEND_TARGET = "127.0.0.1:8000"
FRONTEND_TARGET = "127.0.0.1:3000"
PLACEHOLDER_MARKERS = (
    "CHANGE_ME",
    "YOUR_DOMAIN",
    "YOUR_HOST",
    "REPLACE_ME",
    "example.com",
    "TODO",
    "FIXME",
)


@dataclass(frozen=True)
class EdgeViolation:
    """One rule break in the edge Caddyfile."""

    path: Path
    message: str


@dataclass(frozen=True)
class Node:
    """One Caddyfile node: a directive line, or a block with nested children.

    ``labels`` are the leading tokens (directive name + args, or the block
    address). ``children`` is ``None`` for a bare directive line and a list of
    nested nodes for a block.
    """

    labels: tuple[str, ...]
    children: tuple[Node, ...] | None
    line: int


class EdgeConfigError(Exception):
    """The Caddyfile does not parse as a balanced block structure."""


def _tokenize(source: str) -> list[tuple[str, int]]:
    """Split the Caddyfile into ``(token, line)`` pairs.

    Whitespace separates tokens; double quotes group one token; a standalone
    ``{`` or ``}`` is its own token (a block delimiter), while a brace glued to
    other characters - as in the ``{$STAGING_DOMAIN:...}`` env substitution -
    stays part of its word; lines whose first non-space character is ``#`` are
    comments.
    """
    tokens: list[tuple[str, int]] = []
    line = 1
    i = 0
    length = len(source)
    while i < length:
        char = source[i]
        if char == "\n":
            line += 1
            i += 1
            continue
        if char in " \t\r":
            i += 1
            continue
        if char == "#":
            while i < length and source[i] != "\n":
                i += 1
            continue
        if char == '"':
            j = i + 1
            while j < length and source[j] != '"':
                if source[j] == "\n":
                    raise EdgeConfigError(f"line {line}: unterminated quoted string")
                j += 1
            if j >= length:
                raise EdgeConfigError(f"line {line}: unterminated quoted string")
            tokens.append((source[i : j + 1], line))
            i = j + 1
            continue
        j = i
        while j < length and source[j] not in ' \t\r\n"':
            j += 1
        tokens.append((source[i:j], line))
        i = j
    return tokens


def _parse_nodes(tokens: list[tuple[str, int]], start: int, stop: int) -> tuple[list[Node], int]:
    """Parse ``tokens[start:stop]`` (an already-opened block) into child nodes.

    Returns ``(nodes, index)`` where ``index`` points at the closing ``}``
    (or equals ``stop`` when the block is unterminated). The ``}`` is the
    current block's terminator and is consumed by the caller.
    """
    nodes: list[Node] = []
    i = start
    while i < stop:
        word, line = tokens[i]
        if word == "}":
            return nodes, i
        labels = [word]
        i += 1
        while i < stop and tokens[i][0] not in ("{", "}"):
            labels.append(tokens[i][0])
            i += 1
        if i < stop and tokens[i][0] == "{":
            children, j = _parse_nodes(tokens, i + 1, stop)
            if j >= stop or tokens[j][0] != "}":
                raise EdgeConfigError(f"line {line}: unbalanced braces - missing }}")
            i = j + 1
            nodes.append(Node(tuple(labels), tuple(children), line))
        else:
            nodes.append(Node(tuple(labels), None, line))
    return nodes, i


def _parse(source: str) -> list[Node]:
    """Parse the full Caddyfile into top-level (site block) nodes."""
    tokens = _tokenize(source)
    if not tokens:
        return []
    nodes, i = _parse_nodes(tokens, 0, len(tokens))
    if i < len(tokens) and tokens[i][0] == "}":
        raise EdgeConfigError(f"line {tokens[i][1]}: unexpected }}")
    return nodes


def _directives(node: Node) -> list[Node]:
    """The bare-directive lines directly inside a block."""
    return [child for child in node.children or () if child.children is None]


def _blocks(node: Node) -> list[Node]:
    """The nested blocks directly inside a block."""
    return [child for child in node.children or () if child.children is not None]


def _proxy_targets(block: Node) -> list[str]:
    """The ``reverse_proxy`` targets declared directly inside ``block``."""
    targets: list[str] = []
    for directive in _directives(block):
        if (
            directive.labels
            and directive.labels[0] == "reverse_proxy"
            and len(directive.labels) > 1
        ):
            targets.append(directive.labels[1])
    return targets


def _header_blocks(site: Node) -> list[Node]:
    """The ``header`` blocks declared directly inside the site block."""
    return [block for block in _blocks(site) if block.labels and block.labels[0] == "header"]


def _has_hsts(site: Node) -> bool:
    """Whether any ``header`` block sets ``Strict-Transport-Security``."""
    for header_block in _header_blocks(site):
        if any(
            d.labels and d.labels[0] == "Strict-Transport-Security"
            for d in _directives(header_block)
        ):
            return True
    return False


def _proxy_handle_violation(
    site: Node,
    path: Path,
    *,
    block_predicate: Callable[[Node], bool],
    handle_name: str,
    target: str,
    missing_message: str,
) -> EdgeViolation | None:
    """Assert a matching ``handle`` block reverse-proxies to ``target``.

    ``block_predicate`` selects the block to require (e.g. the ``/api/*`` block
    or the bare default block). ``handle_name`` only names it in messages.
    """
    for block in _blocks(site):
        if not block.labels or block.labels[0] not in ("handle", "handle_path"):
            continue
        if not block_predicate(block):
            continue
        if target in _proxy_targets(block):
            return None
        return EdgeViolation(
            path,
            f"line {block.line}: {handle_name} must reverse_proxy to {target}",
        )
    return EdgeViolation(path, missing_message)


def _backend_handle_violation(site: Node, path: Path) -> EdgeViolation | None:
    """Assert ``/api/*`` is reverse-proxied to the backend target."""
    return _proxy_handle_violation(
        site,
        path,
        block_predicate=lambda block: "/api/*" in block.labels[1:],
        handle_name="/api/* handle",
        target=BACKEND_TARGET,
        missing_message=(
            "missing /api/* handle that reverse_proxies to the backend (127.0.0.1:8000)"
        ),
    )


def _frontend_handle_violation(site: Node, path: Path) -> EdgeViolation | None:
    """Assert the bare ``handle`` block reverse-proxies to the frontend target."""
    return _proxy_handle_violation(
        site,
        path,
        block_predicate=lambda block: len(block.labels) == 1,
        handle_name="default handle",
        target=FRONTEND_TARGET,
        missing_message=(
            "missing default handle that reverse_proxies to the frontend (127.0.0.1:3000)"
        ),
    )


def _site_violations(site: Node, path: Path) -> list[EdgeViolation]:
    """Assert the required staging boundary contract inside one site block."""
    address = " ".join(site.labels)
    violations: list[EdgeViolation] = []
    if not address.startswith(SITE_ADDRESS_PREFIX):
        violations.append(
            EdgeViolation(
                path,
                f"line {site.line}: site address must be the "
                f"{{$STAGING_DOMAIN:...}} env substitution, found: {address}",
            )
        )
    backend_violation = _backend_handle_violation(site, path)
    if backend_violation is not None:
        violations.append(backend_violation)
    frontend_violation = _frontend_handle_violation(site, path)
    if frontend_violation is not None:
        violations.append(frontend_violation)
    if not _has_hsts(site):
        violations.append(
            EdgeViolation(path, "site block must set Strict-Transport-Security (TLS boundary)")
        )
    return violations


def check_edge_config(caddyfile: Path = DEFAULT_CADDYFILE) -> tuple[EdgeViolation, ...]:
    """Lint ``caddyfile`` against the staging TLS boundary contract.

    Returns every violation, sorted by message, so the output is deterministic
    and the unit tests can assert on exact violations.
    """
    if not caddyfile.is_file():
        return (EdgeViolation(caddyfile, f"missing {caddyfile}"),)
    source = caddyfile.read_text(encoding="utf-8")
    if not source.strip():
        return (EdgeViolation(caddyfile, "empty Caddyfile"),)

    violations: list[EdgeViolation] = []
    for marker in PLACEHOLDER_MARKERS:
        if marker in source:
            violations.append(
                EdgeViolation(caddyfile, f"unsubstituted placeholder left in file: {marker}")
            )
    try:
        nodes = _parse(source)
    except EdgeConfigError as exc:
        violations.append(EdgeViolation(caddyfile, str(exc)))
        return tuple(sorted(violations, key=lambda v: v.message))

    site_blocks = [node for node in nodes if node.children is not None]
    if len(site_blocks) != 1:
        violations.append(
            EdgeViolation(caddyfile, f"expected exactly one site block, found {len(site_blocks)}")
        )
        return tuple(sorted(violations, key=lambda v: v.message))
    violations.extend(_site_violations(site_blocks[0], caddyfile))
    return tuple(sorted(violations, key=lambda v: v.message))


def main(argv: list[str] | None = None) -> int:
    """Run the edge config lint; exit 1 on violations."""
    parser = argparse.ArgumentParser(
        description="Lint deploy/edge/Caddyfile (PHASE-1 T8a, #31).",
    )
    parser.add_argument(
        "--caddyfile",
        type=Path,
        default=DEFAULT_CADDYFILE,
        help=f"path to the edge Caddyfile (default: {DEFAULT_CADDYFILE})",
    )
    args = parser.parse_args(argv)
    violations = check_edge_config(args.caddyfile)
    for violation in violations:
        print(f"{violation.path}: {violation.message}", file=sys.stderr)
    if violations:
        print(f"edge config check FAILED: {len(violations)} violation(s)", file=sys.stderr)
        return 1
    print("edge config check OK: deploy/edge/Caddyfile satisfies the staging TLS boundary contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
