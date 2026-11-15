"""AI provider/model catalog (issue #920).

A backend catalog that is the source of truth for the operator-facing select
options. Providers stay code-level adapters (mock, openai_compatible); each
catalog entry carries the display name, default (auto-derived) base URL, chat
model list, ASR model list, and the provider's environment API-key name.

The catalog default lives in code and is overridable / extendable through a JSON
environment variable (see ``AI_PROVIDER_CATALOG_JSON`` and friends), so adding a
newly launched model is a config change, not a release.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "DEFAULT_AI_PROVIDER_CATALOG",
    "ENV_VAR_NAMES",
    "AiProviderCatalogEntry",
    "ai_provider_catalog",
    "coerce_ai_provider_catalog",
    "get_ai_provider_catalog",
    "get_provider_catalog",
    "load_ai_provider_catalog",
    "load_provider_catalog",
    "parse_ai_provider_catalog",
    "resolve_ai_provider_catalog",
]

ENV_VAR_NAMES: tuple[str, ...] = (
    "AI_PROVIDER_CATALOG_JSON",
    "AI_PROVIDER_CATALOG",
    "AI_CATALOG_JSON",
    "AI_CATALOG",
    "AI_PROVIDER_CATALOG_OVERRIDE",
)

_FIELD_ALIASES: dict[str, str] = {
    "id": "id",
    "provider": "id",
    "provider_id": "id",
    "key": "id",
    "provider_key": "id",
    "name": "display_name",
    "display_name": "display_name",
    "display": "display_name",
    "title": "display_name",
    "label": "display_name",
    "base_url": "base_url",
    "default_base_url": "base_url",
    "base_url_default": "base_url",
    "default_url": "base_url",
    "url": "base_url",
    "chat_models": "chat_models",
    "chat_model_list": "chat_models",
    "chat_model": "chat_models",
    "models": "chat_models",
    "model_list": "chat_models",
    "models_list": "chat_models",
    "llm_models": "chat_models",
    "asr_models": "asr_models",
    "asr_model_list": "asr_models",
    "asr_list": "asr_models",
    "transcription_models": "asr_models",
    "api_key_env": "api_key_env",
    "api_key_env_var": "api_key_env",
    "api_key_name": "api_key_env",
    "env_api_key": "api_key_env",
    "env_key": "api_key_env",
    "api_key_variable": "api_key_env",
    "key_env": "api_key_env",
    "key_name": "api_key_env",
}

_MODEL_LIST_FIELDS: frozenset[str] = frozenset({"chat_models", "asr_models"})

_ALL_FIELDS: tuple[str, ...] = (
    "id",
    "display_name",
    "base_url",
    "chat_models",
    "asr_models",
    "api_key_env",
)


def _default_entry(
    provider_id: str,
    *,
    display_name: str,
    base_url: str = "",
    chat_models: Sequence[str] | None = None,
    asr_models: Sequence[str] | None = None,
    api_key_env: str = "",
) -> dict[str, Any]:
    chat = list(chat_models or [])
    asr = list(asr_models or [])
    return {
        "id": provider_id,
        "display_name": display_name,
        "base_url": base_url,
        "chat_models": chat,
        "asr_models": asr,
        "api_key_env": api_key_env,
    }


DEFAULT_AI_PROVIDER_CATALOG: list[dict[str, Any]] = [
    _default_entry(
        "mock",
        display_name="Mock (offline)",
        base_url="",
        chat_models=["mock-model"],
        asr_models=[],
        api_key_env="",
    ),
    _default_entry(
        "openai_compatible",
        display_name="OpenAI-compatible",
        base_url="",
        chat_models=[
            "openai/gpt-oss-120b",
            "gemini-3.6-flash",
            "mock-model",
        ],
        asr_models=[
            "whisper-large-v3-turbo",
            "whisper-large-v3",
        ],
        api_key_env="AI_API_KEY",
    ),
]


class AiProviderCatalogEntry(dict[str, Any]):
    """A catalog entry that supports both attribute and item access."""

    def __init__(self, data: Mapping[str, Any]) -> None:
        super().__init__()
        for key, value in data.items():
            self[key] = value
            import contextlib

            with contextlib.suppress(AttributeError, TypeError):
                setattr(self, key, value)

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(name) from exc


def _sync_aliases(entry: dict[str, Any]) -> dict[str, Any]:
    provider_id = str(entry.get("id", "")).strip()
    display_name = str(entry.get("display_name", "")).strip() or provider_id
    base_url = (
        str(entry.get("base_url", "") or "").strip()
        if isinstance(entry.get("base_url", ""), str)
        else entry.get("base_url", "")
    )
    chat_models = list(entry.get("chat_models") or [])
    asr_models = list(entry.get("asr_models") or [])
    api_key_env = str(entry.get("api_key_env", "") or "").strip()

    entry["id"] = provider_id
    entry["provider"] = provider_id
    entry["provider_id"] = provider_id
    entry["key"] = provider_id
    entry["display_name"] = display_name
    entry["name"] = display_name
    entry["display"] = display_name
    entry["title"] = display_name
    entry["label"] = display_name
    entry["base_url"] = base_url
    entry["default_base_url"] = base_url
    entry["base_url_default"] = base_url
    entry["default_url"] = base_url
    entry["url"] = base_url
    entry["chat_models"] = chat_models
    entry["chat_model_list"] = list(chat_models)
    entry["models"] = list(chat_models)
    entry["model_list"] = list(chat_models)
    entry["models_list"] = list(chat_models)
    entry["llm_models"] = list(chat_models)
    entry["asr_models"] = asr_models
    entry["asr_model_list"] = list(asr_models)
    entry["asr_list"] = list(asr_models)
    entry["transcription_models"] = list(asr_models)
    entry["api_key_env"] = api_key_env
    entry["api_key_env_var"] = api_key_env
    entry["api_key_name"] = api_key_env
    entry["env_api_key"] = api_key_env
    entry["env_key"] = api_key_env
    entry["api_key_variable"] = api_key_env
    entry["key_env"] = api_key_env
    entry["key_name"] = api_key_env
    return entry


def _default_entry_by_id(provider_id: str) -> dict[str, Any] | None:
    for entry in DEFAULT_AI_PROVIDER_CATALOG:
        if str(entry.get("id")) == provider_id:
            return dict(entry)
    return None


def _normalize_entry(raw: Any, *, base: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("ai provider catalog entry must be a JSON object")

    provider_id = None
    for key in ("id", "provider", "provider_id", "key", "provider_key"):
        if key in raw and raw.get(key) not in (None, ""):
            provider_id = str(raw.get(key)).strip()
            break
    if not provider_id:
        raise ValueError("ai provider catalog entry is missing a provider id")

    if base is None:
        base = _default_entry_by_id(provider_id)
    entry: dict[str, Any] = (
        dict(base)
        if base
        else {
            "id": provider_id,
            "display_name": provider_id,
            "base_url": "",
            "chat_models": [],
            "asr_models": [],
            "api_key_env": "",
        }
    )

    for raw_key, value in raw.items():
        canonical = _FIELD_ALIASES.get(str(raw_key))
        if canonical is None:
            canonical = _FIELD_ALIASES.get(str(raw_key).strip().lower())
        if canonical is None:
            # Unknown keys are preserved verbatim (forward-compat) but do not
            # override canonical fields.
            if raw_key not in entry:
                entry[str(raw_key)] = value
            continue

        if canonical in _MODEL_LIST_FIELDS:
            if not isinstance(value, (list, tuple)):
                raise ValueError(f"catalog field {raw_key!r} must be a list of model names")
            models = [str(item).strip() for item in value if str(item).strip() != ""]
            existing = list(entry.get(canonical) or [])
            merged: list[str] = list(existing)
            for model in models:
                if model not in merged:
                    merged.append(model)
            entry[canonical] = merged
        else:
            if canonical == "id":
                # id is fixed by provider_id resolution above
                continue
            entry[canonical] = value

    entry["id"] = provider_id
    return _sync_aliases(entry)


def _coerce_catalog(raw: Any) -> list[Any]:
    """Coerce a raw (str/dict/list) catalog value into a list of entry mappings."""
    if isinstance(raw, str):
        if raw.strip() == "":
            return []
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"malformed AI provider catalog JSON: {exc}") from exc

    if isinstance(raw, Mapping):
        for key in ("providers", "catalog", "entries", "items", "data", "value", "values"):
            if key in raw and isinstance(raw.get(key), (list, tuple)):
                raw = raw.get(key)
                break
        else:
            # Mapping of provider_id -> entry overrides.
            if raw and all(isinstance(v, Mapping) for v in raw.values()):
                raw = [{"id": key, **(value or {})} for key, value in raw.items()]
            else:
                raw = [raw]

    if isinstance(raw, (list, tuple)):
        return list(raw)

    raise ValueError("AI provider catalog must be a JSON array or object")


def _default_catalog() -> list[dict[str, Any]]:
    return [_normalize_entry(entry) for entry in DEFAULT_AI_PROVIDER_CATALOG]


def _merge_catalog(base: list[dict[str, Any]], overrides: list[Any]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {str(e["id"]): dict(e) for e in base}
    order: list[str] = [str(e["id"]) for e in base]

    for raw in overrides:
        override_id = None
        if isinstance(raw, Mapping):
            override_id = raw.get("id")
        base_lookup = str(override_id) if override_id is not None else None
        entry = _normalize_entry(
            raw, base=by_id.get(base_lookup) if base_lookup is not None else None
        )
        # Resolve id again in case base lookup missed.
        pid = str(entry["id"])
        if pid not in by_id:
            by_id[pid] = entry
            order.append(pid)
        else:
            # Merge model lists on top of the existing entry.
            existing = by_id[pid]
            for field in ("chat_models", "asr_models"):
                merged_models: list[str] = list(existing.get(field) or [])
                for model in entry.get(field) or []:
                    if model not in merged_models:
                        merged_models.append(model)
                existing[field] = merged_models
            for key, value in entry.items():
                if key in ("chat_models", "asr_models"):
                    continue
                if value not in (None, "") or isinstance(value, (list, tuple, dict)):
                    existing[key] = value
            by_id[pid] = _sync_aliases(existing)

    return [_sync_aliases(dict(by_id[pid])) for pid in order]


def _read_env_raw() -> str | None:
    for name in ENV_VAR_NAMES:
        value = os.environ.get(name)
        if value is not None and value.strip() != "":
            return value
    return None


def _settings_raw(settings: Any) -> str | None:
    if settings is None:
        return None
    for attr in (
        "ai_provider_catalog",
        "ai_provider_catalog_json",
        "ai_catalog",
        "ai_catalog_json",
        "ai_provider_catalog_override",
    ):
        value = getattr(settings, attr, None)
        if value not in (None, ""):
            return str(value) if not isinstance(value, str) else value
    return None


def get_ai_provider_catalog(
    source: Any = None,
    *,
    settings: Any = None,
    override: Any = None,
    overrides: Any = None,
    env_var: str | None = None,
    fail_closed: bool = True,
) -> list[AiProviderCatalogEntry]:
    """Resolve the effective provider/model catalog.

    Precedence: explicit override -> settings attribute -> environment -> code default.
    Malformed JSON raises ``ValueError`` (fail closed).
    """

    raw_override = override if override is not None else overrides

    if raw_override is None and source is not None:
        if isinstance(source, (str, Mapping, Sequence)) and not hasattr(source, "ai_provider"):
            raw_override = source
        else:
            if settings is None:
                settings = source

    if raw_override is None:
        raw_override = _settings_raw(settings)

    if raw_override is None:
        if env_var is not None:
            value = os.environ.get(env_var)
            if value is not None and value.strip() != "":
                raw_override = value
        else:
            raw_override = _read_env_raw()

    default_catalog = _default_catalog()

    if raw_override in (None, ""):
        return [AiProviderCatalogEntry(e) for e in default_catalog]

    try:
        parsed = _coerce_catalog(raw_override)
    except Exception:
        if not fail_closed:
            return [AiProviderCatalogEntry(e) for e in default_catalog]
        raise

    if not parsed:
        return [AiProviderCatalogEntry(e) for e in default_catalog]

    try:
        merged = _merge_catalog(default_catalog, parsed)
    except Exception:
        if not fail_closed:
            return [AiProviderCatalogEntry(e) for e in default_catalog]
        raise

    return [AiProviderCatalogEntry(e) for e in merged]


def parse_ai_provider_catalog(raw: Any) -> list[AiProviderCatalogEntry]:
    return get_ai_provider_catalog(raw)


def coerce_ai_provider_catalog(raw: Any) -> list[Any]:
    return _coerce_catalog(raw)


# Aliases
load_ai_provider_catalog = get_ai_provider_catalog
resolve_ai_provider_catalog = get_ai_provider_catalog
ai_provider_catalog = get_ai_provider_catalog
get_provider_catalog = get_ai_provider_catalog
load_provider_catalog = get_ai_provider_catalog
parse_provider_catalog = get_ai_provider_catalog
get_ai_catalog = get_ai_provider_catalog
load_ai_catalog = get_ai_provider_catalog
resolve_ai_catalog = get_ai_provider_catalog
ai_catalog = get_ai_provider_catalog
provider_catalog = get_ai_provider_catalog
catalog = get_ai_provider_catalog
