"""MOD-014: canonical ops event payloads.

Event names follow the registry dot-notation in ``internal-modules.md``
§4.2; payloads are typed Pydantic models (coding-standards §3) and carry
only the lineage identity and lifecycle facts - never record content or
any other PHI.
"""

from __future__ import annotations

from pydantic import BaseModel


class OpsRuntimeSettingChangedPayload(BaseModel):
    """Subject of ``ops.runtime_setting_changed``: a runtime switch was flipped."""

    key: str
    value: bool
    version: int


PRODUCER_MODULE = "ops"


def ops_runtime_setting_changed_envelope(
    key: str,
    value: bool,
    version: int,
) -> BaseModel:
    """Build the ``ops.runtime_setting_changed`` envelope payload."""
    return OpsRuntimeSettingChangedPayload(
        key=key,
        value=value,
        version=version,
    )
