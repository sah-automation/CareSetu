"""Common result models used across partner sub-facades."""

from pydantic import BaseModel


class PartnerView(BaseModel):
    """The typed result of a partner lifecycle mutation."""

    partner_id: int
    status: str
    round: int
