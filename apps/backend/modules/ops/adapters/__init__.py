"""MOD-014: ops HTTP adapters."""

from __future__ import annotations

from bus.events import EVENT_OPS_RUNTIME_SETTING_CHANGED
from bus.registry import HandlerRegistry
from modules.ops.domain.events import OpsRuntimeSettingChangedPayload


def register_handlers(registry: HandlerRegistry) -> None:
    """Register ops module event handlers + payload models."""
    # Producer owns the payload model for the runtime setting changed event
    registry.register_payload_model(
        EVENT_OPS_RUNTIME_SETTING_CHANGED, OpsRuntimeSettingChangedPayload
    )
