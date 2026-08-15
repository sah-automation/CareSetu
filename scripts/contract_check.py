"""TEST-F (#132): OpenAPI vs frontend auth client contract check.

The frontend/backend drift bug class hit during DEPLOY-7 (a field-name or
type mismatch between the PWA's auth client and the API, surfacing as 422s) is
prevented here: the checker parses the client's request/response contract out
of ``apps/frontend/src/lib/auth/api.ts`` and verifies every auth path, method,
request shape, and response shape resolves in the backend's OpenAPI schema
(``/openapi.json``). A missing endpoint, a renamed or dropped field, or a
changed type fails the check with a diff-style message; CI hard-fails PR and
merge on it (test-suite plan section 3.F).

The schema is read from a ``--openapi`` URL (a running backend), a local JSON
file, or generated in-process from ``app.main`` when the flag is omitted - the
same ``create_app`` tree the server serves, so local runs need no booted
server. Stdlib-only like the other gate scripts.

The dev/test/demo OTP read-back route is treated in-band: the client tolerates
a 404 (``DEV_OTP_UNAVAILABLE``) at runtime, but its 200 shape - ``MockOtpResponse``
with a nullable ``code`` - must still resolve exactly like every other
endpoint, so the client and schema cannot drift on the happy path. The error
envelope (``ErrorEnvelope``) is deliberately not checked against the schema:
the backend's error responses are produced by exception handlers and are not
modelled as response schemas in ``/openapi.json``, so there is no document
side to drift against.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "apps" / "backend"
DEFAULT_API_FILE = REPO_ROOT / "apps" / "frontend" / "src" / "lib" / "auth" / "api.ts"

_INTERFACE_RE = re.compile(r"export interface (\w+) \{\n(.*?)\n\}", re.S)
_FIELD_RE = re.compile(r"^\s{2}(\w+):\s*(.+?);\s*$", re.M)
_FUNCTION_START_RE = re.compile(r"^export (?:async )?function (\w+)", re.M)
_POST_CALL_RE = re.compile(r"post<[^>]*>\s*\(([^)]*)\)")
_OBJECT_LITERAL_RE = re.compile(r"\{([^}]*)\}")
_PATH_RE = re.compile(r"(/v1/[^\"'?]+)")
_QUERY_RE = re.compile(r"\?([^\"']+)")
_QUERY_PARAM_RE = re.compile(r"(\w+)=")
_PROMISE_RE = re.compile(r"Promise<([A-Za-z_]\w*)>")
_CAST_RE = re.compile(r"\bas\s+(\w+)")
_HTTP_METHOD_RE = re.compile(r'method:\s*"(\w+)"')
_IDENTIFIER_RE = re.compile(r"[A-Za-z_]\w*")

_SCHEMAS_REF_PREFIX = "#/components/schemas/"

_STRING_BASE = frozenset({"string"})
_NUMBER_BASE = frozenset({"integer", "number"})
_BOOLEAN_BASE = frozenset({"boolean"})
_OBJECT_BASE = frozenset({"object"})


class ContractParseError(Exception):
    """The frontend client or OpenAPI schema could not be parsed."""


@dataclass(frozen=True)
class TypeSpec:
    """A normalized request/response type, client- or OpenAPI-side.

    ``base`` is the set of compatible JSON base types (``string``, ``integer``,
    ``number``, ``boolean``, ``object``); ``number`` and ``integer`` are treated
    as interchangeable because FastAPI serializes integers as JSON numbers.
    ``values`` carries the string-literal union members when the type is an
    enum; ``nullable`` mirrors the ``| null`` / ``anyOf: null`` spelling.
    """

    base: frozenset[str] = field(default_factory=frozenset)
    nullable: bool = False
    values: frozenset[str] | None = None


@dataclass(frozen=True)
class ClientEndpoint:
    """One HTTP call the frontend auth client makes (one function in api.ts)."""

    name: str
    method: str
    path: str
    request_fields: tuple[str, ...]
    response: str


def _client_type(expr: str) -> TypeSpec:
    """Normalize a TypeScript type expression (``"a" | "b" | null``) to a ``TypeSpec``."""
    expr = " ".join(expr.split())
    nullable = False
    if expr.endswith("| null"):
        nullable = True
        expr = expr[: -len("| null")].strip()
    parts = [part.strip() for part in expr.split("|")]
    literals = [part for part in parts if part.startswith('"') and part.endswith('"')]
    if literals and len(literals) == len(parts):
        values = frozenset(part[1:-1] for part in literals)
        return TypeSpec(base=_STRING_BASE, nullable=nullable, values=values)
    bases = {
        "string": _STRING_BASE,
        "number": _NUMBER_BASE,
        "boolean": _BOOLEAN_BASE,
        "Record<string, unknown>": _OBJECT_BASE,
    }
    if expr in bases:
        return TypeSpec(base=bases[expr], nullable=nullable)
    raise ContractParseError(f"unsupported client type: {expr!r}")


def parse_interfaces(source: str) -> dict[str, dict[str, TypeSpec]]:
    """Every ``export interface`` in ``source``, mapped to its typed fields."""
    interfaces: dict[str, dict[str, TypeSpec]] = {}
    for match in _INTERFACE_RE.finditer(source):
        name, body = match.group(1), match.group(2)
        fields: dict[str, TypeSpec] = {}
        for field_match in _FIELD_RE.finditer(body):
            fields[field_match.group(1)] = _client_type(field_match.group(2))
        interfaces[name] = fields
    return interfaces


def _post_request_fields(body: str, context: str) -> list[str]:
    """The request-body field names of a ``post<T>(...)`` call, else ``[]``."""
    call = _POST_CALL_RE.search(body)
    if call is None:
        raise ContractParseError(f"{context}: cannot parse the post() call")
    literal = _OBJECT_LITERAL_RE.search(call.group(1))
    if literal is None:
        return []
    return _IDENTIFIER_RE.findall(literal.group(1))


def _get_request_fields(body: str) -> list[str]:
    """The query-parameter names of a ``fetch(...)`` URL, else ``[]``."""
    query = _QUERY_RE.search(body)
    if query is None:
        return []
    return _QUERY_PARAM_RE.findall(query.group(1))


def _response_interface(body: str, interfaces: dict[str, dict[str, TypeSpec]], context: str) -> str:
    """The response interface a function is typed against.

    ``Promise<X>`` when ``X`` is one of the parsed interfaces (the four post
    helpers), falling back to the ``as X`` cast in the body (``fetchDemoOtp``
    returns ``Promise<string | null>`` but parses a ``DemoOtpResult``).
    """
    promise = _PROMISE_RE.search(body)
    if promise is not None and promise.group(1) in interfaces:
        return promise.group(1)
    cast = _CAST_RE.search(body)
    if cast is not None:
        return cast.group(1)
    raise ContractParseError(f"{context}: cannot determine the response interface")


def parse_api(source: str) -> tuple[dict[str, dict[str, TypeSpec]], list[ClientEndpoint]]:
    """Parse the auth client's interfaces and request functions out of ``source``."""
    interfaces = parse_interfaces(source)
    endpoints: list[ClientEndpoint] = []
    starts = list(_FUNCTION_START_RE.finditer(source))
    for index, match in enumerate(starts):
        name = match.group(1)
        end = starts[index + 1].start() if index + 1 < len(starts) else len(source)
        body = source[match.start() : end]
        path_match = _PATH_RE.search(body)
        if path_match is None:
            raise ContractParseError(f"{name}: no /v1 auth path found in api.ts")
        method = "POST" if "post<" in body else _http_method(body)
        if method == "POST":
            request_fields = _post_request_fields(body, name)
        else:
            request_fields = _get_request_fields(body)
        endpoints.append(
            ClientEndpoint(
                name=name,
                method=method,
                path=path_match.group(1),
                request_fields=tuple(request_fields),
                response=_response_interface(body, interfaces, name),
            )
        )
    return interfaces, endpoints


def _http_method(body: str) -> str:
    """The HTTP verb of a non-post call (``fetch``), defaulting to GET."""
    match = _HTTP_METHOD_RE.search(body)
    return match.group(1) if match is not None else "GET"


def _deref(spec: dict, schema: dict) -> dict:
    """Resolve a ``$ref`` against the OpenAPI components, or return ``schema``."""
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema
    if not ref.startswith(_SCHEMAS_REF_PREFIX):
        raise ContractParseError(f"unsupported $ref target: {ref}")
    name = ref[len(_SCHEMAS_REF_PREFIX) :]
    try:
        return spec["components"]["schemas"][name]
    except KeyError as exc:
        raise ContractParseError(f"OpenAPI $ref target not found: {ref}") from exc


def _flatten_leaves(spec: dict, schema: dict) -> list[dict]:
    """Every dereferenced type alternative under ``anyOf``/``oneOf``/plain type."""
    schema = _deref(spec, schema)
    if "anyOf" in schema:
        return [leaf for alt in schema["anyOf"] for leaf in _flatten_leaves(spec, alt)]
    if "oneOf" in schema:
        return [leaf for alt in schema["oneOf"] for leaf in _flatten_leaves(spec, alt)]
    return [schema]


def _openapi_type(spec: dict, schema: dict) -> TypeSpec:
    """Normalize an OpenAPI 3.1 schema object (refs, anyOf null) to a ``TypeSpec``."""
    bases: set[str] = set()
    nullable = False
    enum_values: frozenset[str] | None = None
    for leaf in _flatten_leaves(spec, schema):
        if leaf.get("type") == "null":
            nullable = True
            continue
        if "enum" in leaf:
            enum_values = frozenset(str(value) for value in leaf["enum"])
        if "const" in leaf:
            enum_values = frozenset({str(leaf["const"])})
        type_value = leaf.get("type")
        if isinstance(type_value, list):
            for member in type_value:
                if member == "null":
                    nullable = True
                elif member in {"string", "integer", "number", "boolean", "object"}:
                    bases.add(member)
        elif type_value in {"string", "integer", "number", "boolean", "object"}:
            bases.add(type_value)
        else:
            bases.add("unknown")
    return TypeSpec(base=frozenset(bases), nullable=nullable, values=enum_values)


def _describe(spec_type: TypeSpec) -> str:
    """A short human rendering of a ``TypeSpec`` for mismatch messages."""
    if spec_type.values is not None:
        joined = ", ".join(sorted(spec_type.values))
        rendered = f"literal union [{joined}]"
    elif spec_type.base == _NUMBER_BASE:
        rendered = "number"
    elif len(spec_type.base) == 1:
        rendered = next(iter(spec_type.base))
    else:
        rendered = "unknown"
    return f"{rendered} | null" if spec_type.nullable else rendered


def _type_mismatches(iface: str, field_name: str, client: TypeSpec, schema: TypeSpec) -> list[str]:
    """Diff-style messages when ``client`` and ``schema`` types disagree."""
    if client.nullable != schema.nullable:
        allows = "client" if client.nullable else "OpenAPI"
        other = "OpenAPI" if client.nullable else "client"
        return [
            f"{iface}.{field_name}: nullability mismatch: {allows} allows null, {other} does not"
        ]
    if client.values is not None or schema.values is not None:
        if client.values is None:
            return [
                f"{iface}.{field_name}: type mismatch: client declares string, "
                f"OpenAPI declares {_describe(schema)}"
            ]
        if schema.values is None:
            return [
                f"{iface}.{field_name}: type mismatch: client declares {_describe(client)}, "
                "OpenAPI declares string"
            ]
        messages: list[str] = []
        for value in sorted(client.values - schema.values):
            messages.append(
                f"{iface}.{field_name}: literal {value!r} missing in OpenAPI (client allows it, "
                f"backend enum is [{', '.join(sorted(schema.values))}])"
            )
        for value in sorted(schema.values - client.values):
            messages.append(
                f"{iface}.{field_name}: literal {value!r} missing in client (backend returns it, "
                f"client union is [{', '.join(sorted(client.values))}])"
            )
        return messages
    if not client.base.intersection(schema.base):
        return [
            f"{iface}.{field_name}: type mismatch: client declares {_describe(client)}, "
            f"OpenAPI declares {_describe(schema)}"
        ]
    return []


def _json_content_schema(obj: dict) -> dict | None:
    """The ``application/json`` body schema of an OpenAPI request/response object."""
    return ((obj.get("content") or {}).get("application/json") or {}).get("schema")


def _check_request(
    spec: dict,
    operation: dict,
    endpoint: ClientEndpoint,
    violations: list[str],
) -> None:
    """Verify the client's request fields resolve in the operation's schema."""
    if endpoint.method == "POST":
        request_body = operation.get("requestBody") or {}
        schema = _json_content_schema(request_body)
        if schema is None:
            violations.append(f"POST {endpoint.path}: request body schema missing in OpenAPI")
            return
        schema = _deref(spec, schema)
        properties = schema.get("properties") or {}
        sent = set(endpoint.request_fields)
        for name in endpoint.request_fields:
            prop = properties.get(name)
            if prop is None:
                violations.append(
                    f"POST {endpoint.path}: request field {name!r} missing in OpenAPI request body"
                )
                continue
            schema_type = _openapi_type(spec, prop)
            if "string" not in schema_type.base:
                violations.append(
                    f"POST {endpoint.path}: request field {name!r} type mismatch: client sends "
                    f"a string, OpenAPI declares {_describe(schema_type)}"
                )
        for name in schema.get("required") or []:
            if name not in sent:
                violations.append(
                    f"POST {endpoint.path}: required request field {name!r} missing in client "
                    f"(backend requires it, client sends [{', '.join(sorted(sent))}])"
                )
        return
    parameters = operation.get("parameters") or []
    for name in endpoint.request_fields:
        param = next(
            (p for p in parameters if p.get("in") == "query" and p.get("name") == name), None
        )
        if param is None:
            violations.append(f"GET {endpoint.path}: query parameter {name!r} missing in OpenAPI")
            continue
        param_schema = param.get("schema")
        if not param_schema:
            continue
        schema_type = _openapi_type(spec, param_schema)
        if "string" not in schema_type.base:
            violations.append(
                f"GET {endpoint.path}: query parameter {name!r} type mismatch: client sends "
                f"a string, OpenAPI declares {_describe(schema_type)}"
            )
    sent = set(endpoint.request_fields)
    for param in parameters:
        if param.get("in") == "query" and param.get("required") and param.get("name") not in sent:
            violations.append(
                f"GET {endpoint.path}: required query parameter {param['name']!r} missing in "
                f"client (backend requires it, client sends [{', '.join(sorted(sent))}])"
            )


def _check_response(
    spec: dict,
    operation: dict,
    interfaces: dict[str, dict[str, TypeSpec]],
    endpoint: ClientEndpoint,
    violations: list[str],
) -> None:
    """Verify every response-interface field resolves in the 200 response schema."""
    fields = interfaces.get(endpoint.response)
    if fields is None:
        violations.append(
            f"{endpoint.name}: response interface {endpoint.response!r} not found in api.ts"
        )
        return
    response = (operation.get("responses") or {}).get("200") or {}
    schema = _json_content_schema(response)
    if schema is None:
        violations.append(
            f"{endpoint.method} {endpoint.path}: 200 response schema missing in OpenAPI"
        )
        return
    schema = _deref(spec, schema)
    properties = schema.get("properties") or {}
    for field_name, client_type in fields.items():
        prop = properties.get(field_name)
        if prop is None:
            violations.append(f"{endpoint.response}.{field_name}: field missing in OpenAPI")
            continue
        schema_type = _openapi_type(spec, prop)
        violations.extend(_type_mismatches(endpoint.response, field_name, client_type, schema_type))


def check_contract(
    interfaces: dict[str, dict[str, TypeSpec]],
    endpoints: list[ClientEndpoint],
    spec: dict,
) -> list[str]:
    """Verify each client endpoint resolves in ``spec``; return diff-style violations."""
    violations: list[str] = []
    paths = spec.get("paths") or {}
    for endpoint in sorted(endpoints, key=lambda e: (e.method, e.path)):
        path_item = paths.get(endpoint.path)
        if path_item is None:
            violations.append(f"{endpoint.method} {endpoint.path}: endpoint missing in OpenAPI")
            continue
        operation = path_item.get(endpoint.method.lower())
        if operation is None:
            violations.append(
                f"{endpoint.method} {endpoint.path}: "
                f"{endpoint.method.lower()} operation missing in OpenAPI"
            )
            continue
        _check_request(spec, operation, endpoint, violations)
        _check_response(spec, operation, interfaces, endpoint, violations)
    return violations


def load_openapi(source: str | None) -> dict:
    """The OpenAPI schema: fetched from a URL, read from a file, or generated."""
    if source is None:
        return _generate_openapi()
    if source.startswith("http://") or source.startswith("https://"):
        with urllib.request.urlopen(source, timeout=30) as response:  # nosec B310 - dev-only CLI; the URL is a fixed CI/localhost value, never user input, and urllib keeps the checker stdlib-only
            return json.loads(response.read().decode("utf-8"))
    path = Path(source)
    if not path.is_file():
        raise ContractParseError(f"OpenAPI source not found: {source}")
    return json.loads(path.read_text(encoding="utf-8"))


def _generate_openapi() -> dict:
    """Build the OpenAPI document in-process from the app shell (local fallback)."""
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    import app.main  # type: ignore[import-not-found]

    return app.main.app.openapi()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the contract check; exit 0 when the client resolves against the schema."""
    parser = argparse.ArgumentParser(
        description="Verify the frontend auth client contract against the backend OpenAPI "
        "schema (test-suite plan section 3.F).",
    )
    parser.add_argument(
        "--api",
        type=Path,
        default=DEFAULT_API_FILE,
        help=f"frontend auth client file (default: {DEFAULT_API_FILE})",
    )
    parser.add_argument(
        "--openapi",
        default=None,
        help="OpenAPI schema: a URL, a local JSON file, or omitted to generate from app.main",
    )
    args = parser.parse_args(argv)
    try:
        source = args.api.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"contract check FAILED: cannot read {args.api}: {exc}", file=sys.stderr)
        return 1
    try:
        interfaces, endpoints = parse_api(source)
    except ContractParseError as exc:
        print(f"contract check FAILED: {exc}", file=sys.stderr)
        return 1
    try:
        spec = load_openapi(args.openapi)
    except (ContractParseError, OSError, json.JSONDecodeError, urllib.error.URLError) as exc:
        print(f"contract check FAILED: cannot load the OpenAPI schema: {exc}", file=sys.stderr)
        return 1
    violations = check_contract(interfaces, endpoints, spec)
    for violation in sorted(violations):
        print(f"  {violation}", file=sys.stderr)
    if violations:
        print(
            f"contract check FAILED: {len(violations)} mismatch(es) against OpenAPI",
            file=sys.stderr,
        )
        return 1
    print(
        f"contract check OK: {len(endpoints)} auth client endpoint(s) match the backend "
        "OpenAPI schema"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
