"""MOD-014: HTTP adapter for effective settings read (#771)."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.gateway.principal import Principal
from app.gateway.rbac import require_admin
from modules.ops.facade import OpsFacade


class EffectiveSettingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    value: object | None
    source: str
    editable: bool
    restart_required: bool


class EffectiveSettingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: list[EffectiveSettingResponse]


router = APIRouter(tags=["ops"])


def _facade(request: Request) -> OpsFacade:
    return cast(OpsFacade, request.app.state.ops_facade)


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


@router.get(
    "/v1/operator/settings/effective",
    response_model=EffectiveSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Read effective settings with source and allowlist (admin only)",
)
async def read_effective_settings(
    request: Request,
    principal: Annotated[Principal, Depends(require_admin)],
) -> EffectiveSettingsResponse:
    del principal
    facade = _facade(request)
    settings_list = await facade.get_effective_settings()
    return EffectiveSettingsResponse(
        settings=[
            EffectiveSettingResponse(
                key=item.key,
                value=item.value,
                source=item.source,
                editable=item.editable,
                restart_required=item.restart_required,
            )
            for item in settings_list
        ]
    )
