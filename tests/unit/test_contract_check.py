"""TEST-F (#132): OpenAPI vs frontend auth client contract check - fixture tests.

Feeds throwaway ``api.ts`` sources and OpenAPI documents to
``scripts.contract_check`` and asserts the acceptance criteria: the checker
resolves every client path, method, request shape, and response shape against
the schema; a missing endpoint, a renamed or dropped field, a wrong type, a
nullability drift, or an enum literal drift fails with a diff-style message;
and the real ``api.ts`` passes against the real backend OpenAPI document (the
done-verify bar for the current tree).
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

CONTRACT_CHECK_FILE = Path(__file__).resolve().parents[2] / "scripts" / "contract_check.py"
API_FILE = (
    Path(__file__).resolve().parents[2] / "apps" / "frontend" / "src" / "lib" / "auth" / "api.ts"
)


def _load_contract_check():
    """Import ``scripts/contract_check.py`` by path.

    The root ``scripts/`` directory is not a Python package - ``scripts``
    resolves to ``apps/backend/scripts`` (the package the gate scripts live
    under) - while the TEST-suite checker lives where the plan says it does
    (``scripts/contract_check.py``), so the test loads it by file location.
    """
    spec = importlib.util.spec_from_file_location("contract_check", CONTRACT_CHECK_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cc = _load_contract_check()

ClientEndpoint = cc.ClientEndpoint
ContractParseError = cc.ContractParseError
TypeSpec = cc.TypeSpec
check_contract = cc.check_contract
load_openapi = cc.load_openapi
main = cc.main
parse_api = cc.parse_api


def _spec() -> dict:
    """A minimal OpenAPI 3.1 document exercising every auth client surface."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "fixture", "version": "0.0.0"},
        "paths": {
            "/v1/auth/register": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/RegisterPatientRequest"}
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/RegisterPatientResult"}
                                }
                            }
                        }
                    },
                }
            },
            "/v1/auth/dev/otp": {
                "get": {
                    "parameters": [
                        {
                            "name": "phone",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/MockOtpResponse"}
                                }
                            }
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "RegisterPatientRequest": {
                    "type": "object",
                    "properties": {"phone": {"type": "string"}},
                    "required": ["phone"],
                },
                "RegisterPatientResult": {
                    "type": "object",
                    "properties": {
                        "outcome": {
                            "type": "string",
                            "enum": ["sent", "cooldown", "locked", "suspended"],
                        },
                        "phone_e164": {"type": "string"},
                        "identity_id": {"type": "integer"},
                        "challenge_id": {
                            "anyOf": [{"type": "integer"}, {"type": "null"}],
                        },
                        "is_existing": {"type": "boolean"},
                        "flow": {"type": "string", "enum": ["register", "login"]},
                        "expires_in_seconds": {
                            "anyOf": [{"type": "integer"}, {"type": "null"}],
                        },
                        "cooldown_remaining_seconds": {
                            "anyOf": [{"type": "integer"}, {"type": "null"}],
                        },
                        "attempts_left": {
                            "anyOf": [{"type": "integer"}, {"type": "null"}],
                        },
                        "lockout_remaining_seconds": {
                            "anyOf": [{"type": "integer"}, {"type": "null"}],
                        },
                    },
                    "required": ["outcome", "phone_e164", "identity_id", "is_existing", "flow"],
                },
                "MockOtpResponse": {
                    "type": "object",
                    "properties": {"code": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
                    "required": ["code"],
                },
            }
        },
    }


def _register_endpoint() -> ClientEndpoint:
    return ClientEndpoint(
        name="registerPhone",
        method="POST",
        path="/v1/auth/register",
        request_fields=("phone",),
        response="RegisterResult",
    )


def _otp_endpoint() -> ClientEndpoint:
    return ClientEndpoint(
        name="fetchDemoOtp",
        method="GET",
        path="/v1/auth/dev/otp",
        request_fields=("phone",),
        response="DemoOtpResult",
    )


def _register_interfaces() -> dict[str, dict[str, TypeSpec]]:
    return {
        "RegisterResult": {
            "outcome": TypeSpec(
                base=frozenset({"string"}),
                values=frozenset({"sent", "cooldown", "locked", "suspended"}),
            ),
            "phone_e164": TypeSpec(base=frozenset({"string"})),
            "identity_id": TypeSpec(base=frozenset({"integer", "number"})),
            "challenge_id": TypeSpec(base=frozenset({"integer", "number"}), nullable=True),
            "is_existing": TypeSpec(base=frozenset({"boolean"})),
            "flow": TypeSpec(base=frozenset({"string"}), values=frozenset({"register", "login"})),
            "expires_in_seconds": TypeSpec(base=frozenset({"integer", "number"}), nullable=True),
            "cooldown_remaining_seconds": TypeSpec(
                base=frozenset({"integer", "number"}), nullable=True
            ),
            "attempts_left": TypeSpec(base=frozenset({"integer", "number"}), nullable=True),
            "lockout_remaining_seconds": TypeSpec(
                base=frozenset({"integer", "number"}), nullable=True
            ),
        },
        "DemoOtpResult": {
            "code": TypeSpec(base=frozenset({"string"}), nullable=True),
        },
    }


def test_parse_api_extracts_interfaces_and_endpoints() -> None:
    source = (
        "export interface RegisterResult {\n"
        '  outcome: "sent" | "cooldown";\n'
        "  identity_id: number;\n"
        "}\n\n"
        "export function registerPhone(phone: string): Promise<RegisterResult> {\n"
        '  return post<RegisterResult>("/v1/auth/register", { phone });\n'
        "}\n\n"
        "export async function fetchDemoOtp(phone: string): Promise<string | null> {\n"
        "  const response = await fetch(\n"
        "    `${API_BASE_URL}/v1/auth/dev/otp?phone=${encodeURIComponent(phone)}`,\n"
        "  );\n"
        "  if (!response.ok) { return null; }\n"
        "  const body = (await response.json()) as DemoOtpResult;\n"
        '  return typeof body.code === "string" ? body.code : null;\n'
        "}\n"
    )

    interfaces, endpoints = parse_api(source)

    assert interfaces["RegisterResult"]["outcome"].values == frozenset({"sent", "cooldown"})
    assert interfaces["RegisterResult"]["identity_id"].base == frozenset({"integer", "number"})
    register = endpoints[0]
    assert (register.method, register.path) == ("POST", "/v1/auth/register")
    assert register.request_fields == ("phone",)
    assert register.response == "RegisterResult"
    otp = endpoints[1]
    assert (otp.method, otp.path) == ("GET", "/v1/auth/dev/otp")
    assert otp.request_fields == ("phone",)
    assert otp.response == "DemoOtpResult"


def test_parse_api_verify_two_request_fields() -> None:
    source = (
        "export interface VerifyResult {\n"
        '  outcome: "verified" | "wrong_code";\n'
        "}\n\n"
        "export function verifyOtp(phone: string, otp: string): Promise<VerifyResult> {\n"
        '  return post<VerifyResult>("/v1/auth/verify", { phone, otp });\n'
        "}\n"
    )

    _, endpoints = parse_api(source)

    assert endpoints[0].request_fields == ("phone", "otp")


def test_parse_api_unsupported_type_is_a_hard_failure() -> None:
    source = "export interface Broken {\n  id: bigint;\n}\n"

    with pytest.raises(ContractParseError):
        parse_api(source)


def test_clean_contract_passes() -> None:
    spec = _spec()
    interfaces = _register_interfaces()
    endpoints = [_register_endpoint(), _otp_endpoint()]

    assert check_contract(interfaces, endpoints, spec) == []


def test_missing_endpoint_fails() -> None:
    spec = _spec()
    del spec["paths"]["/v1/auth/register"]
    endpoints = [_register_endpoint(), _otp_endpoint()]

    violations = check_contract(_register_interfaces(), endpoints, spec)

    assert any("/v1/auth/register: endpoint missing in OpenAPI" in v for v in violations)


def test_missing_operation_method_fails() -> None:
    spec = _spec()
    del spec["paths"]["/v1/auth/register"]["post"]
    violations = check_contract(_register_interfaces(), [_register_endpoint()], spec)

    assert any("post operation missing in OpenAPI" in v for v in violations)


def test_missing_request_field_fails() -> None:
    spec = _spec()
    del spec["components"]["schemas"]["RegisterPatientRequest"]["properties"]["phone"]
    violations = check_contract(_register_interfaces(), [_register_endpoint()], spec)

    assert any("request field 'phone' missing in OpenAPI request body" in v for v in violations)


def test_request_field_type_mismatch_fails() -> None:
    spec = _spec()
    request = spec["components"]["schemas"]["RegisterPatientRequest"]["properties"]["phone"]
    request["type"] = "integer"
    violations = check_contract(_register_interfaces(), [_register_endpoint()], spec)

    assert any(
        "request field 'phone' type mismatch: client sends a string" in v for v in violations
    )


def test_required_request_field_missing_in_client_fails() -> None:
    spec = _spec()
    spec["components"]["schemas"]["RegisterPatientRequest"]["required"].append("otp")
    spec["components"]["schemas"]["RegisterPatientRequest"]["properties"]["otp"] = {
        "type": "string"
    }
    violations = check_contract(_register_interfaces(), [_register_endpoint()], spec)

    assert any("required request field 'otp' missing in client" in v for v in violations)


def test_required_query_parameter_missing_in_client_fails() -> None:
    spec = _spec()
    spec["paths"]["/v1/auth/dev/otp"]["get"]["parameters"].append(
        {"name": "tenant", "in": "query", "required": True, "schema": {"type": "string"}}
    )
    violations = check_contract(_register_interfaces(), [_otp_endpoint()], spec)

    assert any("required query parameter 'tenant' missing in client" in v for v in violations)


def test_missing_query_parameter_fails() -> None:
    spec = _spec()
    del spec["paths"]["/v1/auth/dev/otp"]["get"]["parameters"]
    violations = check_contract(_register_interfaces(), [_otp_endpoint()], spec)

    assert any("query parameter 'phone' missing in OpenAPI" in v for v in violations)


def test_missing_response_field_fails_with_clear_message() -> None:
    spec = _spec()
    del spec["components"]["schemas"]["RegisterPatientResult"]["properties"]["phone_e164"]
    violations = check_contract(_register_interfaces(), [_register_endpoint()], spec)

    assert any("RegisterResult.phone_e164: field missing in OpenAPI" in v for v in violations)


def test_enum_literal_missing_in_openapi_fails() -> None:
    spec = _spec()
    del spec["components"]["schemas"]["RegisterPatientResult"]["properties"]["outcome"]["enum"][0]
    violations = check_contract(_register_interfaces(), [_register_endpoint()], spec)

    assert any("outcome: literal 'sent' missing in OpenAPI" in v for v in violations)


def test_enum_literal_missing_in_client_fails() -> None:
    spec = _spec()
    spec["components"]["schemas"]["RegisterPatientResult"]["properties"]["outcome"]["enum"].append(
        "new_outcome"
    )
    violations = check_contract(_register_interfaces(), [_register_endpoint()], spec)

    assert any("outcome: literal 'new_outcome' missing in client" in v for v in violations)


def test_type_mismatch_fails() -> None:
    spec = _spec()
    spec["components"]["schemas"]["RegisterPatientResult"]["properties"]["is_existing"]["type"] = (
        "string"
    )
    violations = check_contract(_register_interfaces(), [_register_endpoint()], spec)

    assert any(
        "RegisterResult.is_existing: type mismatch: client declares boolean" in v
        for v in violations
    )


def test_nullability_mismatch_fails() -> None:
    spec = _spec()
    spec["components"]["schemas"]["RegisterPatientResult"]["properties"]["challenge_id"] = {
        "type": "integer"
    }
    violations = check_contract(_register_interfaces(), [_register_endpoint()], spec)

    assert any(
        "RegisterResult.challenge_id: nullability mismatch: client allows null" in v
        for v in violations
    )


def test_load_openapi_reads_a_local_file(tmp_path: Path) -> None:
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(_spec()), encoding="utf-8")

    assert load_openapi(str(path))["openapi"] == "3.1.0"


def test_load_openapi_missing_source_fails(tmp_path: Path) -> None:
    with pytest.raises(ContractParseError):
        load_openapi(str(tmp_path / "nope.json"))


def test_main_exits_zero_on_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    api = tmp_path / "api.ts"
    api.write_text(
        "export interface Result {\n"
        "  id: number;\n"
        "}\n\n"
        "export function getThing(phone: string): Promise<Result> {\n"
        '  return post<Result>("/v1/auth/register", { phone });\n'
        "}\n",
        encoding="utf-8",
    )
    spec = tmp_path / "openapi.json"
    spec.write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "x", "version": "0"},
                "paths": {
                    "/v1/auth/register": {
                        "post": {
                            "requestBody": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"phone": {"type": "string"}},
                                            "required": ["phone"],
                                        }
                                    }
                                }
                            },
                            "responses": {
                                "200": {
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {"id": {"type": "integer"}},
                                                "required": ["id"],
                                            }
                                        }
                                    }
                                }
                            },
                        }
                    }
                },
                "components": {"schemas": {}},
            }
        ),
        encoding="utf-8",
    )

    assert main(["--api", str(api), "--openapi", str(spec)]) == 0
    assert "contract check OK" in capsys.readouterr().out


def test_main_exits_one_on_mismatch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    api = tmp_path / "api.ts"
    api.write_text(
        "export interface Result {\n"
        "  renamed_field: string;\n"
        "}\n\n"
        "export function getThing(phone: string): Promise<Result> {\n"
        '  return post<Result>("/v1/auth/register", { phone });\n'
        "}\n",
        encoding="utf-8",
    )
    spec = tmp_path / "openapi.json"
    spec.write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "x", "version": "0"},
                "paths": {
                    "/v1/auth/register": {
                        "post": {
                            "requestBody": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"phone": {"type": "string"}},
                                        }
                                    }
                                }
                            },
                            "responses": {
                                "200": {
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {"old_field": {"type": "string"}},
                                            }
                                        }
                                    }
                                }
                            },
                        }
                    }
                },
                "components": {"schemas": {}},
            }
        ),
        encoding="utf-8",
    )

    assert main(["--api", str(api), "--openapi", str(spec)]) == 1
    assert "Result.renamed_field: field missing in OpenAPI" in capsys.readouterr().err


def test_real_api_ts_passes_against_real_openapi() -> None:
    interfaces, endpoints = parse_api(API_FILE.read_text(encoding="utf-8"))
    spec = load_openapi(None)

    assert len(endpoints) == 5
    assert check_contract(interfaces, endpoints, spec) == []
