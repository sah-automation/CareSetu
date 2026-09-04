"""MOD-001: HTTP adapters for the iam module (PHASE-2 T3/T4/T5, tickets #54, #55, #56).

Endpoints are thin adapters (api-standards §1): parse the typed request, call
the module facade, return the typed result. Every expected failure answers the
shared error envelope at the top level (api-standards §2): a stable
``SCREAMING_SNAKE`` code, a human-safe message, a trace id, and details.
``register_error_handlers`` maps iam domain errors to that envelope; the route
itself carries no business logic. The auth routes sit behind the gateway
middleware stack in ``app.main`` - the rate-limit policy for the OTP/auth
surface is a Phase 2 gateway ticket. The register/verify/resend/session
mutations honour the edge's ``Idempotency-Key`` contract
(api-standards §5, PHASE-2 REM T11, #80) via ``run_idempotent``: a duplicate
key replays the stored result instead of re-executing.
"""

from __future__ import annotations

import re
from typing import Annotated, cast

from fastapi import APIRouter, Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.gateway.errors import error_response
from app.gateway.idempotency import run_idempotent
from app.gateway.principal import Principal
from app.gateway.rbac import require_operator
from modules.iam.adapters.sms import mask_phone
from modules.iam.domain.exceptions import (
    IamError,
    InvalidOperatorCodeError,
    InvalidPhoneError,
    OperatorMfaError,
    RefreshTokenExpiredError,
    RefreshTokenRevokedError,
    RefreshTokenUnknownError,
    SessionIssuanceError,
    SmsDeliveryError,
)
from modules.iam.facade import (
    EnrollMfaResult,
    IamFacade,
    OperatorInvitedResult,
    RegisterPatientResult,
    ResendOtpResult,
    SessionResult,
    VerifyOtpResult,
)

router = APIRouter(prefix="/v1/auth", tags=["iam"])


class RegisterPatientRequest(BaseModel):
    """Body of ``POST /v1/auth/register``: the raw phone the PWA collected."""

    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, description="10-digit Indian mobile number, or with 91 prefix")


class VerifyOtpRequest(BaseModel):
    """Body of ``POST /v1/auth/verify``: the phone and the submitted 6-digit code."""

    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, description="10-digit Indian mobile number, or with 91 prefix")
    otp: str = Field(
        pattern=r"^[0-9]{6}$",
        description="The 6-digit code the patient received; only well-formed guesses count",
    )


class ResendOtpRequest(BaseModel):
    """Body of ``POST /v1/auth/resend``: the phone needing a fresh code."""

    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, description="10-digit Indian mobile number, or with 91 prefix")


class IssueSessionRequest(BaseModel):
    """Body of ``POST /v1/auth/session``: the verified phone to mint a session for."""

    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, description="10-digit Indian mobile number, or with 91 prefix")


class RefreshSessionRequest(BaseModel):
    """Body of ``POST /v1/auth/refresh``: the refresh token to rotate."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(
        min_length=1, description="Opaque refresh token from a previous session"
    )


class OperatorInviteRequest(BaseModel):
    """Body of ``POST /v1/auth/operator/invite`` (S9, #262)."""

    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, description="10-digit Indian mobile number, or with 91 prefix")


class OperatorLoginRequest(BaseModel):
    """Body of ``POST /v1/auth/operator/login`` (S9, #262)."""

    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, description="10-digit Indian mobile number, or with 91 prefix")
    code: str = Field(
        pattern=r"^[0-9]{6}$",
        description="The 6-digit RFC-6238 TOTP code from the enrolled MFA factor",
    )


_DEV_TEST_ENVIRONMENTS = frozenset({"dev", "test"})
_JWT_COOKIE_NAME = "caresetu_session"


def _is_secure_cookie(request: Request) -> bool:
    """True when the cookie ``secure`` flag should be set (non-dev/test)."""
    settings = cast(Settings, request.app.state.settings)
    return settings.app_environment.strip().lower() not in _DEV_TEST_ENVIRONMENTS


def _set_jwt_cookie(response: Response, jwt_value: str, ttl_seconds: int, *, secure: bool) -> None:
    """Attach the JWT as an httpOnly cookie on ``response``.

    Cookie attributes match the acceptance criteria:
    - ``httpOnly=true``: JS cannot read the cookie (XSS mitigation)
    - ``secure=true`` when not in dev/test: cookie only sent over HTTPS
    - ``sameSite=strict``: no cross-origin cookie submission
    - ``path=/``: cookie sent on every request path
    - ``maxAge`` matching JWT TTL so the browser drops it at expiry
    """
    response.set_cookie(
        key=_JWT_COOKIE_NAME,
        value=jwt_value,
        max_age=ttl_seconds,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )


@router.post(
    "/register",
    response_model=RegisterPatientResult,
    status_code=status.HTTP_200_OK,
    summary="Begin or resume phone registration",
)
async def register_patient(
    request: Request,
    body: RegisterPatientRequest,
) -> RegisterPatientResult:
    """Enter a mobile number: create the identity on first use, else resolve it.

    First-time registration and out-of-cooldown login issue a hashed OTP
    challenge, send it via the EXT-001 adapter, and return the flow state the
    PWA drives (is-existing notice, countdown, resend cooldown, attempts
    left). An existing phone inside the resend cooldown, the brute-force
    lockout, or Suspended is refused with the matching outcome and no code is
    sent (spec #51 §2.4).
    """
    facade = cast(IamFacade, request.app.state.iam_facade)
    return await run_idempotent(request, lambda: facade.register_patient(body.phone))


@router.post(
    "/verify",
    response_model=VerifyOtpResult,
    status_code=status.HTTP_200_OK,
    summary="Verify a submitted OTP code",
)
async def verify_otp(
    request: Request,
    body: VerifyOtpRequest,
) -> VerifyOtpResult:
    """Submit the 6-digit code: consume the challenge and verify the patient.

    Returns the outcome the PWA renders - ``verified``, ``wrong_code`` with
    the remaining attempts, ``expired``/``spent`` ("request a new code"), or
    ``locked`` with the lockout countdown.
    """
    facade = cast(IamFacade, request.app.state.iam_facade)
    return await run_idempotent(request, lambda: facade.verify_otp(body.phone, body.otp))


@router.post(
    "/resend",
    response_model=ResendOtpResult,
    status_code=status.HTTP_200_OK,
    summary="Resend the OTP code (latest-wins)",
)
async def resend_otp(
    request: Request,
    body: ResendOtpRequest,
) -> ResendOtpResult:
    """Request a fresh code: invalidate the pending one and issue a new one.

    Returns the outcome the PWA renders - ``sent`` with the fresh challenge
    fields, or the refuse states ``cooldown``/``locked``/``suspended`` with the
    countdown the disable state needs. The facade enforces the >= 60 s resend
    cooldown and the brute-force lockout.
    """
    facade = cast(IamFacade, request.app.state.iam_facade)
    return await run_idempotent(request, lambda: facade.resend_otp(body.phone))


@router.post(
    "/session",
    response_model=SessionResult,
    status_code=status.HTTP_200_OK,
    summary="Issue an authenticated session for a verified patient",
)
async def issue_session(
    request: Request,
    body: IssueSessionRequest,
) -> Response:
    """Mint an access JWT + refresh token for a verified patient's phone.

    The PWA calls this only after a ``verified`` outcome: the facade requires
    the identity to be Active with a patient role grant, so an unverified or
    Suspended phone is refused with a ``409`` ``SESSION_REFUSED`` envelope the
    client must resolve (verify the OTP, or await the role grant) before a
    session can be minted. The returned session is what the PWA stores so it
    can reach protected routes. The JWT is also set as an httpOnly cookie for
    Next.js middleware route protection.
    """
    facade = cast(IamFacade, request.app.state.iam_facade)
    result = await run_idempotent(request, lambda: facade.issue_session(body.phone))
    response = Response(
        content=result.model_dump_json(),
        media_type="application/json",
        status_code=status.HTTP_200_OK,
    )
    _set_jwt_cookie(
        response,
        result.jwt,
        result.expires_in_seconds,
        secure=_is_secure_cookie(request),
    )
    return response


@router.post(
    "/partner/session",
    response_model=SessionResult,
    status_code=status.HTTP_200_OK,
    summary="Issue a partner-scoped session for a registered partner",
)
async def issue_partner_session(
    request: Request,
    body: IssueSessionRequest,
) -> Response:
    """Mint a partner-scoped access JWT for a registered (pre-activation) partner.

    The gap-plan loop needs the partner to submit credentials and read their
    own pending status immediately after registration. The partner identity is
    ``[Unverified]`` with no role grant (ADR-0010), so the standard
    ``POST /v1/auth/session`` (patient-only) always refuses 409
    ``SESSION_REFUSED``. This endpoint instead gates on the existence of a
    partner profile for the phone and mints a ``partner``-scoped JWT
    (self-service surface only). Identity-state refusals (unknown phone, no
    partner profile) stay 409 ``SESSION_REFUSED``.
    """
    facade = cast(IamFacade, request.app.state.iam_facade)
    result = await run_idempotent(request, lambda: facade.issue_partner_session(body.phone))
    response = Response(
        content=result.model_dump_json(),
        media_type="application/json",
        status_code=status.HTTP_200_OK,
    )
    _set_jwt_cookie(
        response,
        result.jwt,
        result.expires_in_seconds,
        secure=_is_secure_cookie(request),
    )
    return response


@router.post(
    "/refresh",
    response_model=SessionResult,
    status_code=status.HTTP_200_OK,
    summary="Rotate a refresh token into a fresh session",
)
async def refresh_session(
    request: Request,
    body: RefreshSessionRequest,
) -> Response:
    """Rotate an opaque refresh token into a fresh JWT + new refresh token.

    The refresh path is independent of SMS (NFR-004): it only reads the
    ``sessions`` table and mints tokens, so an EXT-001 outage never bricks an
    existing session. A revoked or expired token is refused with the matching
    error envelope. The rotated JWT is also set as an httpOnly cookie for
    Next.js middleware route protection.
    """
    facade = cast(IamFacade, request.app.state.iam_facade)
    result = await facade.refresh_session(body.refresh_token)
    response = Response(
        content=result.model_dump_json(),
        media_type="application/json",
        status_code=status.HTTP_200_OK,
    )
    _set_jwt_cookie(
        response,
        result.jwt,
        result.expires_in_seconds,
        secure=_is_secure_cookie(request),
    )
    return response


@router.post(
    "/operator/invite",
    response_model=OperatorInvitedResult,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a new operator (operator only)",
)
async def invite_operator(
    request: Request,
    operator: Annotated[Principal, Depends(require_operator)],
    body: OperatorInviteRequest,
) -> OperatorInvitedResult:
    """Grow the trusted queue-running group (US-22).

    Operator-scoped (``require_operator``): only an attested operator can
    invite another phone. The invited identity is created ``[Unverified]``
    with an ``Active`` ``operator`` role grant, so the invited phone completes
    MFA at first login. The requesting operator is recorded as the inviter on
    the ``operator.invited`` audit event. Duplicate phones resolve to the
    existing identity (idempotent by phone, plus the edge ``Idempotency-Key``).
    """
    invited_by = int(operator.subject_id)
    facade = cast(IamFacade, request.app.state.iam_facade)
    return await run_idempotent(
        request,
        lambda: facade.create_operator_account(body.phone, invited_by_identity_id=invited_by),
    )


@router.post(
    "/operator/login",
    response_model=SessionResult,
    status_code=status.HTTP_200_OK,
    summary="MFA-gated operator login",
)
async def operator_login(
    request: Request,
    body: OperatorLoginRequest,
) -> Response:
    """Log an operator in with the MFA second factor (US-15, S8).

    Accepts the phone and an RFC-6238 TOTP code. A wrong or absent second
    factor is refused with a 401 ``SESSION_MFA_REQUIRED`` envelope - an
    operator can never land an operator-scoped session on the phone alone.
    Identity-state refusals (unknown/not-Active phone, no operator role) stay
    409 ``SESSION_REFUSED``. On success the operator-scoped JWT is returned and
    set as the httpOnly session cookie.
    """
    facade = cast(IamFacade, request.app.state.iam_facade)
    result = await facade.issue_operator_session(body.phone, body.code)
    response = Response(
        content=result.model_dump_json(),
        media_type="application/json",
        status_code=status.HTTP_200_OK,
    )
    _set_jwt_cookie(
        response,
        result.jwt,
        result.expires_in_seconds,
        secure=_is_secure_cookie(request),
    )
    return response


@router.post(
    "/operator/mfa/enroll",
    response_model=EnrollMfaResult,
    status_code=status.HTTP_200_OK,
    summary="Enroll an operator's TOTP MFA factor",
)
async def enroll_operator_mfa(
    request: Request,
    operator: Annotated[Principal, Depends(require_operator)],
) -> EnrollMfaResult:
    """Enroll the authenticated operator's TOTP MFA factor (US-15, P1 #272).

    Operator-scoped (``require_operator``): only an authenticated operator can
    enroll their own factor. Generates a fresh base32 secret, encrypts it at
    rest, and returns the plaintext secret + provisioning URI exactly once so
    the operator can add the factor to an authenticator app. The operator can
    then complete login with a TOTP code from that factor.
    """
    facade = cast(IamFacade, request.app.state.iam_facade)
    return await run_idempotent(request, lambda: facade.enroll_mfa(int(operator.subject_id)))


_E164_IN_MESSAGE = re.compile(r"\+[0-9]{6,15}")


def _redact_phone(message: str) -> str:
    """Mask any full E.164 phone embedded in a message (security-phii: no PII).

    Belt-and-suspenders defense on the error envelope: the facades already
    mask phones in their messages (S1, #275), but a message from any other
    raise site must never surface a complete number to the client. Only the
    ``+<cc>`` and the last two digits survive.
    """
    return _E164_IN_MESSAGE.sub(
        lambda m: mask_phone(m.group(0)),
        message,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach the MOD-001 error envelope to every expected iam failure."""

    async def _invalid_phone(request: Request, exc: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "PHONE_INVALID",
            _redact_phone(str(exc)),
            log_tag="iam_rejection",
            request=request,
        )

    async def _sms_failed(request: Request, exc: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_502_BAD_GATEWAY,
            "SMS_DELIVERY_FAILED",
            _redact_phone(str(exc)),
            log_tag="iam_rejection",
            request=request,
        )

    async def _session_refused(request: Request, exc: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_409_CONFLICT,
            "SESSION_REFUSED",
            _redact_phone(str(exc)),
            log_tag="iam_rejection",
            request=request,
        )

    async def _operator_mfa_failed(request: Request, exc: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_401_UNAUTHORIZED,
            "SESSION_MFA_REQUIRED",
            str(exc),
            log_tag="iam_rejection",
            request=request,
        )

    async def _invalid_operator_code(request: Request, exc: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_401_UNAUTHORIZED,
            "INVALID_OPERATOR_CODE",
            str(exc),
            log_tag="iam_rejection",
            request=request,
        )

    async def _refresh_token_unknown(request: Request, exc: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_401_UNAUTHORIZED,
            "REFRESH_TOKEN_UNKNOWN",
            str(exc),
            log_tag="iam_rejection",
            request=request,
        )

    async def _refresh_token_expired(request: Request, exc: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_401_UNAUTHORIZED,
            "REFRESH_TOKEN_EXPIRED",
            str(exc),
            log_tag="iam_rejection",
            request=request,
        )

    async def _refresh_token_revoked(request: Request, exc: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_401_UNAUTHORIZED,
            "REFRESH_TOKEN_REVOKED",
            str(exc),
            log_tag="iam_rejection",
            request=request,
        )

    async def _iam_failed(request: Request, exc: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "IAM_INTERNAL",
            "Internal identity error",
            log_tag="iam_rejection",
            request=request,
        )

    async def _validation_failed(request: Request, exc: Exception) -> JSONResponse:
        validation_errors = cast(RequestValidationError, exc).errors()
        details: dict[str, object] = {
            "errors": [
                {
                    "path": ".".join(str(part) for part in error["loc"] if part != "body"),
                    "reason": error["msg"],
                }
                for error in validation_errors
            ]
        }
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            "Request validation failed",
            log_tag="iam_rejection",
            request=request,
            details=details,
        )

    app.add_exception_handler(InvalidPhoneError, _invalid_phone)
    app.add_exception_handler(SmsDeliveryError, _sms_failed)
    app.add_exception_handler(SessionIssuanceError, _session_refused)
    app.add_exception_handler(OperatorMfaError, _operator_mfa_failed)
    app.add_exception_handler(InvalidOperatorCodeError, _invalid_operator_code)
    app.add_exception_handler(RefreshTokenUnknownError, _refresh_token_unknown)
    app.add_exception_handler(RefreshTokenExpiredError, _refresh_token_expired)
    app.add_exception_handler(RefreshTokenRevokedError, _refresh_token_revoked)
    app.add_exception_handler(IamError, _iam_failed)
    app.add_exception_handler(RequestValidationError, _validation_failed)
