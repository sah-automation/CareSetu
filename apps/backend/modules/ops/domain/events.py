"""MOD-014: canonical ops event payloads.

Event names follow the registry dot-notation in ``internal-modules.md``
§4.2; payloads are typed Pydantic models (coding-standards §3) and carry
only the lineage identity and lifecycle facts - never record content or
any other PHI.
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from bus.envelope import Envelope
from bus.events import EVENT_AUDIT_EVENT, EVENT_OPS_RUNTIME_SETTING_CHANGED


class OpsRuntimeSettingChangedPayload(BaseModel):
    """Subject of ``ops.runtime_setting_changed``: a runtime switch was flipped."""

    key: str
    value: bool
    version: int


class OpsSettingWriteAuditPayload(BaseModel):
    """Subject of the generic ``audit.event`` for one ops setting write (issue #945).

    Carries the setting key, the old/new values as redacted upstream (a
    value for an encrypted key arrives as ``[REDACTED]``, never raw secret
    material), the new version, and the operator actor. Consumed by MOD-011
    and MOD-013 through the widened audit carrier.
    """

    action: Literal["setting.write"]
    setting_key: str
    old_value: object | None
    new_value: object | None
    version: int
    updated_by: int | None


class OpsFeatureFlagWriteAuditPayload(BaseModel):
    """Subject of the generic ``audit.event`` for one ops feature-flag write (issue #945)."""

    action: Literal["feature_flag.write"]
    flag_key: str
    old_enabled: bool | None
    new_enabled: bool
    flag_kind: str
    version: int
    updated_by: int | None


PRODUCER_MODULE = "ops"


def ops_runtime_setting_changed_envelope(
    key: str,
    value: bool,
    version: int,
) -> Envelope[OpsRuntimeSettingChangedPayload]:
    """Build the ``ops.runtime_setting_changed`` envelope for the ops outbox."""
    return Envelope[OpsRuntimeSettingChangedPayload](
        event_id=uuid4(),
        event_type=EVENT_OPS_RUNTIME_SETTING_CHANGED,
        producer=PRODUCER_MODULE,
        payload=OpsRuntimeSettingChangedPayload(
            key=key,
            value=value,
            version=version,
        ),
    )


def ops_setting_audit_envelope(
    setting_key: str,
    old_value: object | None,
    new_value: object | None,
    version: int,
    updated_by: int | None,
) -> Envelope[OpsSettingWriteAuditPayload]:
    """Build the ``audit.event`` envelope for one setting write (issue #945)."""
    return Envelope[OpsSettingWriteAuditPayload](
        event_id=uuid4(),
        event_type=EVENT_AUDIT_EVENT,
        producer=PRODUCER_MODULE,
        payload=OpsSettingWriteAuditPayload(
            action="setting.write",
            setting_key=setting_key,
            old_value=old_value,
            new_value=new_value,
            version=version,
            updated_by=updated_by,
        ),
    )


def ops_feature_flag_audit_envelope(
    flag_key: str,
    old_enabled: bool | None,
    new_enabled: bool,
    flag_kind: str,
    version: int,
    updated_by: int | None,
) -> Envelope[OpsFeatureFlagWriteAuditPayload]:
    """Build the ``audit.event`` envelope for one feature-flag write (issue #945)."""
    return Envelope[OpsFeatureFlagWriteAuditPayload](
        event_id=uuid4(),
        event_type=EVENT_AUDIT_EVENT,
        producer=PRODUCER_MODULE,
        payload=OpsFeatureFlagWriteAuditPayload(
            action="feature_flag.write",
            flag_key=flag_key,
            old_enabled=old_enabled,
            new_enabled=new_enabled,
            flag_kind=flag_kind,
            version=version,
            updated_by=updated_by,
        ),
    )
