"""MOD-001: HTTP adapters for the iam module (PHASE-2 T3/T4/T5, tickets #54, #55, #56).

Endpoints are thin adapters (api-standards §1): parse the typed request, call
the module facade, return the typed result. Every expected failure answers the
shared error envelope at the top level (api-standards §2): a stable
``SCREAMING_SNAKE`` code, a human-safe message, a trace id, and details.
``register_error_handlers`` maps iam domain errors to that envelope; the route
itself carries no business logic. The register/verify routes sit behind the
gateway middleware stack in ``app.main`` - the rate-limit policy for the
OTP/auth surface is a Phase 2 gateway ticket.
"""

from __future__ import annotations

import uuid
from typing import cast

from fastapi import APIRouter, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from modules.iam.domain.exceptions import (
    IamError,
    InvalidPhoneError,
    SessionIssuanceError,
    SmsDeliveryError,
)
from modules.iam.facade import (
    IamFacade,
    IssueSessionResult,
    RegisterPatientResult,
    ResendOtpResult,
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


class ErrorEnvelope(BaseModel):
    """The single error shape every CareSetu endpoint answers (api-standards §2)."""

    code: str
    message: str
    trace_id: str
    details: dict[str, object]


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
    return await facade.register_patient(body.phone)


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
    return await facade.verify_otp(body.phone, body.otp)


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
    return await facade.resend_otp(body.phone)


@router.post(
    "/session",
    response_model=IssueSessionResult,
    status_code=status.HTTP_200_OK,
    summary="Issue an authenticated session for a verified patient",
)
async def issue_session(
    request: Request,
    body: IssueSessionRequest,
) -> IssueSessionResult:
    """Mint an access JWT + refresh token for a verified patient's phone.

    The PWA calls this only after a ``verified`` outcome: the facade requires
    the identity to be Active with a patient role grant, so an unverified or
    Suspended phone is refused with a ``409`` ``SESSION_REFUSED`` envelope the
    client must resolve (verify the OTP, or await the role grant) before a
    session can be minted. The returned session is what the PWA stores so it
    can reach protected routes.
    """
    facade = cast(IamFacade, request.app.state.iam_facade)
    return await facade.issue_session(body.phone)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    envelope = ErrorEnvelope(code=code, message=message, trace_id=uuid.uuid4().hex, details={})
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


def register_error_handlers(app: FastAPI) -> None:
    """Attach the MOD-001 error envelope to every expected iam failure."""

    async def _invalid_phone(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(status.HTTP_422_UNPROCESSABLE_CONTENT, "PHONE_INVALID", str(exc))

    async def _sms_failed(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(status.HTTP_502_BAD_GATEWAY, "SMS_DELIVERY_FAILED", str(exc))

    async def _session_refused(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(
            status.HTTP_409_CONFLICT,
            "SESSION_REFUSED",
            str(exc),
        )

    async def _iam_failed(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "IAM_INTERNAL",
            "Internal identity error",
        )

    async def _validation_failed(request: Request, exc: Exception) -> JSONResponse:
        validation_errors = cast(RequestValidationError, exc).errors()
        details = {
            "errors": [
                {
                    "path": ".".join(str(part) for part in error["loc"] if part != "body"),
                    "reason": error["msg"],
                }
                for error in validation_errors
            ]
        }
        envelope = ErrorEnvelope(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            trace_id=uuid.uuid4().hex,
            details=details,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=envelope.model_dump(mode="json"),
        )

    app.add_exception_handler(InvalidPhoneError, _invalid_phone)
    app.add_exception_handler(SmsDeliveryError, _sms_failed)
    app.add_exception_handler(SessionIssuanceError, _session_refused)
    app.add_exception_handler(IamError, _iam_failed)
    app.add_exception_handler(RequestValidationError, _validation_failed)
