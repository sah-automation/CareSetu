"""MOD-014: HTTP adapter for effective settings read and feature flags (#771, #773)."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from app.gateway.idempotency import run_idempotent
from app.gateway.principal import Principal
from app.gateway.rbac import require_admin, require_operator
from modules.ops.domain.exceptions import InvalidFeatureFlagWriteError, InvalidSettingWriteError
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


class FeatureFlagReadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flag_key: str
    enabled: bool
    flag_kind: str
    description: str | None
    editable: bool
    updated_at: str


class FeatureFlagsReadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flags: list[FeatureFlagReadResponse]


class FeatureFlagWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flag_key: str
    enabled: bool


class FeatureFlagWriteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flag_key: str
    enabled: bool
    flag_kind: str
    version: int


class SettingWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    setting_key: str
    value: str | int | float | bool | list[str] | dict[str, Any] | None


class SettingWriteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    setting_key: str
    value: str | int | float | bool | list[str] | dict[str, Any] | None
    version: int


class SettingHistoryEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    setting_key: str
    value: object | None
    version: int
    changed_by: int | None
    changed_at: str


class SettingsHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    history: list[SettingHistoryEntryResponse]


router = APIRouter(tags=["ops"])


def _facade(request: Request) -> OpsFacade:
    return cast(OpsFacade, request.app.state.ops_facade)


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


@router.get(
    "/v1/operator/settings/history",
    response_model=SettingsHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Read the append-only setting history (admin only)",
)
async def read_setting_history(
    request: Request,
    principal: Annotated[Principal, Depends(require_admin)],
    setting_key: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SettingsHistoryResponse:
    del principal
    facade = _facade(request)
    history = await facade.get_setting_history(setting_key=setting_key, limit=limit)
    return SettingsHistoryResponse(
        history=[
            SettingHistoryEntryResponse(
                setting_key=entry.setting_key,
                value=entry.value,
                version=entry.version,
                changed_by=entry.changed_by,
                changed_at=entry.changed_at,
            )
            for entry in history
        ]
    )


@router.get(
    "/v1/operator/feature-flags",
    response_model=FeatureFlagsReadResponse,
    status_code=status.HTTP_200_OK,
    summary="Read all feature flags (operator visible)",
)
async def read_feature_flags(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
) -> FeatureFlagsReadResponse:
    del principal
    facade = _facade(request)
    flags = await facade.get_feature_flags()
    return FeatureFlagsReadResponse(flags=flags)


@router.get(
    "/v1/operator/feature-flags/{flag_key}",
    response_model=FeatureFlagReadResponse,
    status_code=status.HTTP_200_OK,
    summary="Read a single feature flag (operator visible)",
)
async def read_feature_flag(
    request: Request,
    flag_key: str,
    principal: Annotated[Principal, Depends(require_operator)],
) -> FeatureFlagReadResponse:
    del principal
    facade = _facade(request)
    flag = await facade.get_feature_flag(flag_key)
    if flag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "FEATURE_FLAG_NOT_FOUND",
                "message": f"Feature flag '{flag_key}' not found",
                "trace_id": request.state.trace_id if hasattr(request.state, "trace_id") else None,
            },
        )
    return FeatureFlagReadResponse(
        flag_key=flag.flag_key,
        enabled=flag.enabled,
        flag_kind=flag.flag_kind,
        description=flag.description,
        editable=flag.editable,
        updated_at=flag.updated_at,
    )


@router.put(
    "/v1/operator/feature-flags/{flag_key}",
    response_model=FeatureFlagWriteResponse,
    status_code=status.HTTP_200_OK,
    summary="Write a runtime feature flag with history and audit (admin only)",
)
async def write_feature_flag(
    request: Request,
    flag_key: str,
    body: FeatureFlagWriteRequest,
    principal: Annotated[Principal, Depends(require_admin)],
) -> FeatureFlagWriteResponse:
    if body.flag_key != flag_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "FLAG_KEY_MISMATCH",
                "message": "Flag key in path and body must match",
                "trace_id": request.state.trace_id if hasattr(request.state, "trace_id") else None,
            },
        )

    facade = _facade(request)

    async def _call() -> FeatureFlagWriteResponse:

        try:
            result = await facade.write_feature_flag(
                flag_key=flag_key,
                enabled=body.enabled,
                updated_by=int(principal.subject_id) if principal.subject_id is not None else None,
            )
        except InvalidFeatureFlagWriteError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_FEATURE_FLAG_WRITE",
                    "message": e.reason,
                    "trace_id": request.state.trace_id
                    if hasattr(request.state, "trace_id")
                    else None,
                },
            ) from e
        return FeatureFlagWriteResponse(
            flag_key=result.flag_key,
            enabled=result.enabled,
            flag_kind=result.flag_kind,
            version=result.version,
        )

    namespace = f"ops:{principal.subject_id}" if principal.subject_id is not None else "ops"
    response = await run_idempotent(request, _call, namespace=namespace)
    return response


@router.put(
    "/v1/operator/settings",
    response_model=SettingWriteResponse,
    status_code=status.HTTP_200_OK,
    summary="Write an allowlisted setting with history and audit (admin only)",
)
async def write_setting(
    request: Request,
    body: SettingWriteRequest,
    principal: Annotated[Principal, Depends(require_admin)],
) -> SettingWriteResponse:
    facade = _facade(request)

    async def _call() -> SettingWriteResponse:
        try:
            result = await facade.write_setting(
                setting_key=body.setting_key,
                value=body.value,
                updated_by=int(principal.subject_id) if principal.subject_id is not None else None,
            )
        except InvalidSettingWriteError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_SETTING_WRITE",
                    "message": e.reason,
                    "trace_id": request.state.trace_id
                    if hasattr(request.state, "trace_id")
                    else None,
                },
            ) from e
        return SettingWriteResponse(
            setting_key=result["setting_key"],
            value=result["value"],
            version=result["version"],
        )

    namespace = f"ops:{principal.subject_id}" if principal.subject_id is not None else "ops"
    response = await run_idempotent(request, _call, namespace=namespace)
    return response
