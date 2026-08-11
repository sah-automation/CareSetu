"""Caller identity attached by the gateway (PHASE-1 T7b, #29).

``Principal`` is the typed shape the gateway attaches to ``request.state`` so
route handlers and Phase 2 RBAC checks read a settled identity contract instead
of scraping headers. The accept-all stub currently builds it from a test header;
real JWT claim parsing replaces that logic in Phase 2 behind this seam.
"""

from pydantic import BaseModel, ConfigDict


class Principal(BaseModel):
    """Identity of the caller as established by the gateway's ``jwt_verify``.

    ``is_authenticated`` separates an anonymous caller from one the gateway
    recognized; ``roles`` carries the RBAC roles for the Phase 2 edge checks.
    """

    model_config = ConfigDict(extra="forbid")

    subject_id: str
    roles: tuple[str, ...] = ()
    is_authenticated: bool = False

    @classmethod
    def anonymous(cls) -> "Principal":
        """Build the principal attached to an unrecognized caller."""
        return cls(subject_id="anonymous", is_authenticated=False)

    @classmethod
    def for_subject(cls, subject_id: str, *roles: str) -> "Principal":
        """Build an authenticated principal for a verified subject."""
        return cls(subject_id=subject_id, roles=roles, is_authenticated=True)
