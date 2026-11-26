"""MOD-005: single effective AI configuration resolver (issue #919)."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config import Settings, get_settings


@dataclass(frozen=True)
class AiConfig:
    provider: str = "mock"
    model: str = "mock-model"
    fallback_provider: str = ""
    fallback_model: str = ""
    asr_model: str = ""
    base_url: str = ""
    fallback_base_url: str = ""
    api_key: str = field(default="", repr=False)
    fallback_api_key: str = field(default="", repr=False)
    pricing_table_raw: str = ""
    pricing_table: Mapping[str, Any] = field(default_factory=dict)
    monthly_budget_paise: int = 200000
    timeout_seconds: float = 30.0
    max_retries: int = 1
    circuit_breaker_threshold: int = 5
    circuit_breaker_cooldown_seconds: float = 30.0
    circuit_breaker_enabled: bool = True
    degraded_mode: bool = False

    @property
    def chat_model(self) -> str:
        return self.model

    @property
    def primary_model(self) -> str:
        return self.model

    @property
    def ai_provider(self) -> str:
        return self.provider

    @property
    def ai_model(self) -> str:
        return self.model

    @property
    def ai_asr_model(self) -> str:
        return self.asr_model

    @property
    def ai_base_url(self) -> str:
        return self.base_url

    @property
    def ai_api_key(self) -> str:
        return self.api_key

    @property
    def ai_fallback_provider(self) -> str:
        return self.fallback_provider

    @property
    def ai_fallback_model(self) -> str:
        return self.fallback_model

    @property
    def ai_fallback_base_url(self) -> str:
        return self.fallback_base_url

    @property
    def ai_fallback_api_key(self) -> str:
        return self.fallback_api_key

    @property
    def ai_pricing_table(self) -> str:
        return self.pricing_table_raw

    @property
    def ai_monthly_budget_paise(self) -> int:
        return self.monthly_budget_paise

    @property
    def ai_timeout_seconds(self) -> float:
        return self.timeout_seconds

    @property
    def ai_max_retries(self) -> int:
        return self.max_retries


class AiConfigOverrideSource(Protocol):
    def get_overrides(self) -> Mapping[str, Any]: ...


_KEY_ALIASES: dict[str, str] = {
    "provider": "provider",
    "ai_provider": "provider",
    "ai.provider": "provider",
    "model": "model",
    "chat_model": "model",
    "primary_model": "model",
    "ai_model": "model",
    "ai.model": "model",
    "fallback_provider": "fallback_provider",
    "ai_fallback_provider": "fallback_provider",
    "ai.fallback_provider": "fallback_provider",
    "fallback_model": "fallback_model",
    "ai_fallback_model": "fallback_model",
    "ai.fallback_model": "fallback_model",
    "asr_model": "asr_model",
    "ai_asr_model": "asr_model",
    "ai.asr_model": "asr_model",
    "base_url": "base_url",
    "ai_base_url": "base_url",
    "ai.base_url": "base_url",
    "fallback_base_url": "fallback_base_url",
    "ai_fallback_base_url": "fallback_base_url",
    "ai.fallback_base_url": "fallback_base_url",
    "api_key": "api_key",
    "ai_api_key": "api_key",
    "ai.api_key": "api_key",
    "fallback_api_key": "fallback_api_key",
    "ai_fallback_api_key": "fallback_api_key",
    "ai.fallback_api_key": "fallback_api_key",
    "pricing_table": "pricing_table_raw",
    "pricing": "pricing_table_raw",
    "ai_pricing_table": "pricing_table_raw",
    "ai.pricing_table": "pricing_table_raw",
    "monthly_budget_paise": "monthly_budget_paise",
    "ai_monthly_budget_paise": "monthly_budget_paise",
    "ai.monthly_budget_paise": "monthly_budget_paise",
    "timeout_seconds": "timeout_seconds",
    "ai_timeout_seconds": "timeout_seconds",
    "ai.timeout_seconds": "timeout_seconds",
    "max_retries": "max_retries",
    "ai_max_retries": "max_retries",
    "circuit_breaker_threshold": "circuit_breaker_threshold",
    "ai_circuit_breaker_threshold": "circuit_breaker_threshold",
    "circuit_breaker_cooldown_seconds": "circuit_breaker_cooldown_seconds",
    "ai_circuit_breaker_cooldown_seconds": "circuit_breaker_cooldown_seconds",
    "circuit_breaker_enabled": "circuit_breaker_enabled",
}


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _extract_overrides(source: Any) -> MutableMapping[str, Any]:
    if source is None:
        return {}
    if isinstance(source, Mapping):
        return dict(source)
    for attr in ("overrides", "db_overrides", "_overrides", "values", "data"):
        if hasattr(source, attr):
            val = getattr(source, attr)
            if isinstance(val, Mapping):
                return dict(val)
    for meth in (
        "get_overrides",
        "get_all",
        "fetch_overrides",
        "load_overrides",
        "resolve_overrides",
    ):
        if hasattr(source, meth) and callable(getattr(source, meth)):
            try:
                result = getattr(source, meth)()
            except (TypeError, AttributeError, RuntimeError):
                result = None
            if isinstance(result, Mapping):
                return dict(result)
    if callable(source) and not hasattr(source, "resolve"):
        try:
            result = source()
        except (TypeError, RuntimeError):
            result = None
        if isinstance(result, Mapping):
            return dict(result)
    try:
        return dict(source)
    except (TypeError, ValueError):
        return {}


def _normalize_overrides(raw: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in raw.items():
        canonical = _KEY_ALIASES.get(str(key))
        if canonical is None:
            canonical = _KEY_ALIASES.get(str(key).strip().lower())
        if canonical is None:
            seg = str(key).split(".")[-1]
            canonical = _KEY_ALIASES.get(seg)
            if canonical is None:
                canonical = _KEY_ALIASES.get(seg.lower())
        if canonical is None:
            lowered = str(key).strip().lower().replace(" ", "_")
            canonical = _KEY_ALIASES.get(lowered)
        if canonical is not None and _present(value):
            out[canonical] = value
    return out


def _pricing_raw_from_override(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        parts = []
        for model, price in value.items():
            if isinstance(price, (tuple, list)) and len(price) >= 2:
                parts.append(f"{model}:{price[0]}:{price[1]}")
            elif hasattr(price, "price_in_paise"):
                parts.append(f"{model}:{price.price_in_paise}:{price.price_out_paise}")
            else:
                parts.append(f"{model}:{price}")
        return ",".join(parts)
    return str(value)


def _pricing_table_from_raw(raw: str) -> Mapping[str, Any]:
    from app.config import parse_ai_pricing_table
    from modules.intake.pricing import PRICING_TABLE, ModelPrice

    parsed = parse_ai_pricing_table(raw) if raw.strip() else {}
    table: dict[str, Any] = {}
    for model, (price_in, price_out) in parsed.items():
        table[model] = ModelPrice(price_in_paise=price_in, price_out_paise=price_out)
    if not table and not raw.strip():
        try:
            table = dict(PRICING_TABLE)
        except Exception:
            table = {}
    return table


def _settings_value(settings: Settings, field: str) -> Any:
    mapping = {
        "provider": getattr(settings, "ai_provider", "mock"),
        "model": getattr(settings, "ai_model", "") or "mock-model",
        "fallback_provider": getattr(settings, "ai_fallback_provider", ""),
        "fallback_model": getattr(settings, "ai_fallback_model", ""),
        "asr_model": getattr(settings, "ai_asr_model", ""),
        "base_url": getattr(settings, "ai_base_url", ""),
        "fallback_base_url": getattr(settings, "ai_fallback_base_url", ""),
        "api_key": getattr(settings, "ai_api_key", ""),
        "fallback_api_key": getattr(settings, "ai_fallback_api_key", ""),
        "pricing_table_raw": getattr(settings, "ai_pricing_table", ""),
        "monthly_budget_paise": getattr(settings, "ai_monthly_budget_paise", 200000),
        "timeout_seconds": getattr(settings, "ai_timeout_seconds", 30.0),
        "max_retries": getattr(settings, "ai_max_retries", 1),
        "circuit_breaker_threshold": getattr(settings, "ai_circuit_breaker_threshold", 5),
        "circuit_breaker_cooldown_seconds": getattr(
            settings, "ai_circuit_breaker_cooldown_seconds", 30.0
        ),
        "circuit_breaker_enabled": getattr(settings, "circuit_breaker_enabled", True),
        "degraded_mode": getattr(settings, "degraded_mode", False),
    }
    return mapping.get(field)


class AiConfigResolver:
    """Resolve effective AI config with precedence: override -> env -> default."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        override_source: Any = None,
        override: Any = None,
        overrides: Any = None,
        source: Any = None,
        db_overrides: Any = None,
        config: Any = None,
        **kwargs: Any,
    ) -> None:
        if settings is None:
            for key in ("settings", "env_settings", "base_settings"):
                if key in kwargs and kwargs[key] is not None:
                    settings = kwargs[key]
                    break
        if settings is None:
            try:
                settings = get_settings()
            except Exception:
                settings = Settings()
        self._settings = settings
        src = override_source
        if src is None:
            src = override
        if src is None:
            src = overrides
        if src is None:
            src = source
        if src is None:
            src = db_overrides
        if src is None and config is not None:
            src = config
        for k, v in kwargs.items():
            if src is None and ("override" in k or "source" in k):
                src = v
        self._override_source = src
        self._override_config: AiConfig | None = None
        self._override_values: dict[str, Any] = {}
        if isinstance(src, AiConfig):
            self._override_config = src
        else:
            self._override_values = _normalize_overrides(_extract_overrides(src))
        if "overrides_values" in kwargs and isinstance(kwargs["overrides_values"], Mapping):
            self._override_values = _normalize_overrides(kwargs["overrides_values"])
        # Direct mapping kwargs (e.g. overrides={"ai.provider": ...})
        for k, v in kwargs.items():
            if isinstance(v, Mapping) and ("override" in k or k in ("db_overrides",)):
                self._override_values = _normalize_overrides(
                    {**_extract_overrides(v), **self._override_values}
                )

    def _resolve_sync(self) -> AiConfig:
        settings = self._settings
        overrides = dict(self._override_values)
        if self._override_config is not None:
            oc = self._override_config
            for fld in (
                "provider",
                "model",
                "fallback_provider",
                "fallback_model",
                "asr_model",
                "base_url",
                "fallback_base_url",
                "api_key",
                "fallback_api_key",
                "pricing_table_raw",
                "monthly_budget_paise",
                "timeout_seconds",
                "max_retries",
                "circuit_breaker_threshold",
                "circuit_breaker_cooldown_seconds",
                "circuit_breaker_enabled",
                "degraded_mode",
            ):
                val = getattr(oc, fld, None)
                if _present(val):
                    overrides[fld] = val
        if "pricing_table_raw" in overrides and not isinstance(overrides["pricing_table_raw"], str):
            overrides["pricing_table_raw"] = _pricing_raw_from_override(
                overrides["pricing_table_raw"]
            )

        def _get(field: str) -> Any:
            if field in overrides and _present(overrides[field]):
                return overrides[field]
            val = _settings_value(settings, field)
            if _present(val):
                return val
            defaults = {
                "provider": "mock",
                "model": "mock-model",
                "fallback_provider": "",
                "fallback_model": "",
                "asr_model": getattr(settings, "ai_asr_model", "") or "",
                "base_url": "",
                "fallback_base_url": "",
                "api_key": "",
                "fallback_api_key": "",
                "pricing_table_raw": "",
                "monthly_budget_paise": 200000,
                "timeout_seconds": 30.0,
                "max_retries": 1,
                "circuit_breaker_threshold": 5,
                "circuit_breaker_cooldown_seconds": 30.0,
                "circuit_breaker_enabled": True,
                "degraded_mode": False,
            }
            return defaults.get(field)

        provider = str(_get("provider")).strip().lower() or "mock"
        model = str(_get("model")).strip() or "mock-model"
        fallback_provider = str(_get("fallback_provider")).strip().lower()
        fallback_model = str(_get("fallback_model")).strip()
        asr_model = str(_get("asr_model")).strip()
        base_url = str(_get("base_url")).strip()
        fallback_base_url = str(_get("fallback_base_url")).strip()
        api_key = str(_get("api_key"))
        fallback_api_key = str(_get("fallback_api_key"))
        pricing_table_raw = str(_get("pricing_table_raw")).strip()
        monthly_budget_paise = int(_get("monthly_budget_paise") or 200000)
        timeout_seconds = float(_get("timeout_seconds") or 30.0)
        max_retries = int(_get("max_retries") or 1)
        circuit_breaker_threshold = int(_get("circuit_breaker_threshold") or 5)
        circuit_breaker_cooldown_seconds = float(_get("circuit_breaker_cooldown_seconds") or 30.0)
        circuit_breaker_enabled = bool(_get("circuit_breaker_enabled"))
        degraded_mode = bool(_get("degraded_mode"))

        if not base_url and provider == "openai_compatible":
            base_url = getattr(settings, "ai_base_url", "") or ""
        if not fallback_base_url and fallback_provider == "openai_compatible":
            fallback_base_url = getattr(settings, "ai_fallback_base_url", "") or ""

        pricing_table = _pricing_table_from_raw(pricing_table_raw)

        return AiConfig(
            provider=provider,
            model=model,
            fallback_provider=fallback_provider,
            fallback_model=fallback_model,
            asr_model=asr_model,
            base_url=base_url,
            fallback_base_url=fallback_base_url,
            api_key=api_key,
            fallback_api_key=fallback_api_key,
            pricing_table_raw=pricing_table_raw,
            pricing_table=pricing_table,
            monthly_budget_paise=monthly_budget_paise,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            circuit_breaker_threshold=circuit_breaker_threshold,
            circuit_breaker_cooldown_seconds=circuit_breaker_cooldown_seconds,
            circuit_breaker_enabled=circuit_breaker_enabled,
            degraded_mode=degraded_mode,
        )

    def resolve(self) -> AiConfig:
        return self._resolve_sync()

    async def aresolve(self) -> AiConfig:
        src = self._override_source
        overrides = dict(self._override_values)
        for meth in (
            "get_overrides",
            "get_all",
            "fetch_overrides",
            "load_overrides",
            "resolve_overrides",
            "resolve",
        ):
            if hasattr(src, meth) and callable(getattr(src, meth)):
                import inspect

                fn = getattr(src, meth)
                if inspect.iscoroutinefunction(fn):
                    try:
                        result = await fn()
                    except (RuntimeError, TypeError, ValueError, OSError):
                        result = None
                    if isinstance(result, Mapping):
                        overrides.update(_normalize_overrides(result))
                    elif isinstance(result, AiConfig):
                        self._override_config = result
        if hasattr(src, "get_effective_settings") and callable(src.get_effective_settings):
            import inspect

            fn = src.get_effective_settings
            if inspect.iscoroutinefunction(fn):
                try:
                    effective = await fn()
                except (RuntimeError, TypeError, ValueError, OSError):
                    effective = None
                if isinstance(effective, (list, tuple)):
                    mapped: dict[str, Any] = {}
                    for item in effective:
                        key = getattr(item, "key", None)
                        if key is None and isinstance(item, Mapping):
                            key = item.get("key")
                        value = (
                            getattr(item, "value", None)
                            if not isinstance(item, Mapping)
                            else item.get("value")
                        )
                        if key is not None:
                            mapped[key] = value
                    overrides.update(_normalize_overrides(mapped))
        self._override_values = overrides
        return self._resolve_sync()

    def __call__(self) -> AiConfig:
        return self.resolve()


def resolve_ai_config(*args: Any, **kwargs: Any) -> AiConfig:
    kwargs = dict(kwargs)
    settings = kwargs.pop("settings", None)
    if settings is None and args:
        first = args[0]
        if isinstance(first, Settings):
            settings = first
            if len(args) > 1:
                kwargs.setdefault("override_source", args[1])
        else:
            kwargs.setdefault("override_source", first)
    resolver = AiConfigResolver(settings, **kwargs)
    return resolver.resolve()


async def aresolve_ai_config(*args: Any, **kwargs: Any) -> AiConfig:
    kwargs = dict(kwargs)
    settings = kwargs.pop("settings", None)
    if settings is None and args:
        first = args[0]
        if isinstance(first, Settings):
            settings = first
            if len(args) > 1:
                kwargs.setdefault("override_source", args[1])
        else:
            kwargs.setdefault("override_source", first)
    resolver = AiConfigResolver(settings, **kwargs)
    return await resolver.aresolve()


AIConfig = AiConfig
AI_CONFIG = AiConfig
ConfigResolver = AiConfigResolver
AIConfigResolver = AiConfigResolver
resolve_ai = resolve_ai_config
get_ai_config = resolve_ai_config
load_ai_config = resolve_ai_config
effective_ai_config = resolve_ai_config
ai_config = resolve_ai_config
build_ai_config = resolve_ai_config


def extract_overrides(source: Any) -> dict[str, Any]:
    return _normalize_overrides(_extract_overrides(source))


__all__ = [
    "AiConfig",
    "AiConfigOverrideSource",
    "AiConfigResolver",
    "aresolve_ai_config",
    "extract_overrides",
    "resolve_ai_config",
]
