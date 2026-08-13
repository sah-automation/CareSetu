"""MOD-001: domain errors for the ``iam`` module (coding-standards §3).

Phase 1 carries the module base error only; the hierarchy grows
with the tickets that introduce real validation.
"""

from __future__ import annotations


class IamError(Exception):
    """Base error for the iam module."""


class InvalidPhoneError(IamError):
    """A phone number failed +91 E.164 normalization (spec #51 §2.2).

    Raised by ``register_patient`` when the caller's number cannot be
    normalized server-side to the launch-scope Indian form; the message is a
    clear, human-safe validation error for the gateway envelope.
    """


class SmsDeliveryError(IamError):
    """An EXT-001 SMS delivery failed after the retry budget was exhausted.

    Raised by the provider adapter only; the mock never raises. The message is
    safe for logs - it never carries the OTP, the API key, or the raw payload.
    """


class SessionIssuanceError(IamError):
    """``issue_session`` refused: the identity cannot hold a patient session.

    Raised when the phone is unknown, the identity is not Active (unverified
    or Suspended), or the active patient role grant is missing - states the
    caller must resolve (register, verify the OTP, or await the role grant)
    before a session can be minted (spec #51 §2.5, ticket #57). The message
    is human-safe and names the missing precondition.
    """


class InvalidAccessTokenError(IamError):
    """Base for an access token the gateway must reject (spec #51 §2.5).

    One subclass per rejection reason - expired, malformed, or wrong
    signature - so the gateway denies every rejection with a single 401 while
    logs keep the distinguishing cause (ticket #57).
    """


class AccessTokenExpiredError(InvalidAccessTokenError):
    """The token's ``exp`` has passed; the session window is over."""


class AccessTokenMalformedError(InvalidAccessTokenError):
    """The token envelope, header, or claims are structurally invalid."""


class AccessTokenSignatureError(InvalidAccessTokenError):
    """The token is signed with the wrong key or an unsupported algorithm."""
