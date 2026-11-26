"""Shared read-cache foundation (ARCH-P1 #816).

Every cache built on ARCH-P1 reads through this helper. It owns namespace
prefixing, TTL resolution, JSON serialization with validation-as-miss,
per-cache hit/miss metrics, the PHI gate, and the degraded-mode TTL cap.

A miss, a Redis error, or a malformed/incompatible payload resolves to a miss;
the caller recomputes from SQL. A cache problem never fails a request.

The helper takes a Redis client (or ``None``) so unit tests use a fake and
callers can run without Redis. ``None`` is always a miss on read and a no-op
on write/invalidate.

Runtime toggles for cache/redis are consumed from ``ops.runtime_setting_changed``
events and applied via in-process atomic flags so changes take effect within
seconds without restart (ticket #895).
"""

from __future__ import annotations

import contextlib
import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.config import Settings, get_settings
from app.runtime_toggles import cache_enabled, set_cache_enabled, set_redis_enabled
from bus.envelope import Envelope
from bus.events import EVENT_OPS_RUNTIME_SETTING_CHANGED
from bus.registry import HandlerRegistry
from modules.ops.domain.events import OpsRuntimeSettingChangedPayload
from observability import otel as _otel

_LOG = logging.getLogger(__name__)
# Preserve the builtin ``set`` before the module-level alias shadows it.
_builtin_set = set

_PHI_CACHE_NAMES = {"profile", "intake"}


async def _handle_runtime_setting_changed(envelope: Envelope[BaseModel]) -> None:
    """Handle ``ops.runtime_setting_changed`` event by flipping atomic flags.

    The event carries the setting key (``cache.enabled`` or ``redis.enabled``),
    the new boolean value, and the version. We update the corresponding flag
    so subsequent cache/redis operations respect the new value immediately.
    """

    payload_raw = envelope.payload
    payload = (
        payload_raw
        if isinstance(payload_raw, OpsRuntimeSettingChangedPayload)
        else OpsRuntimeSettingChangedPayload.model_validate(payload_raw.model_dump())
    )
    key = payload.key
    value = payload.value

    if key == "cache.enabled":
        set_cache_enabled(value)
        _LOG.info(
            "cache.enabled toggled to %s via runtime event (version=%d)", value, payload.version
        )
    elif key == "redis.enabled":
        set_redis_enabled(value)
        _LOG.info(
            "redis.enabled toggled to %s via runtime event (version=%d)", value, payload.version
        )
    else:
        _LOG.warning("Unknown runtime setting key in ops.runtime_setting_changed: %s", key)


def register_handlers(registry: HandlerRegistry) -> None:
    """Register cache module event handlers for runtime toggles (ticket #895)."""
    registry.register(EVENT_OPS_RUNTIME_SETTING_CHANGED, _handle_runtime_setting_changed)


@dataclass
class CacheNamespace:
    """Descriptor for one cache namespace."""

    name: str
    ttl_seconds: int | None = None
    phi: bool = False

    @property
    def namespace(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name


# Aliases for the namespace descriptor - different names callers may expect.
ReadCacheNamespace = CacheNamespace
ReadCacheSpec = CacheNamespace
CacheSpec = CacheNamespace
CacheConfig = CacheNamespace
CacheDescriptor = CacheNamespace
ReadCacheDescriptor = CacheNamespace
ReadCacheConfig = CacheNamespace
Namespace = CacheNamespace
CacheNamespaceSpec = CacheNamespace


def record_cache_hit(cache: str) -> None:
    try:
        _otel.record_cache_hit(cache)
    except Exception:
        _LOG.debug("cache hit metric failed", exc_info=False)


def record_cache_miss(cache: str) -> None:
    try:
        _otel.record_cache_miss(cache)
    except Exception:
        _LOG.debug("cache miss metric failed", exc_info=False)


def _is_client(obj: Any) -> bool:
    return obj is None or (hasattr(obj, "get") and hasattr(obj, "set"))


def _namespace_name(ns: Any) -> str:
    if isinstance(ns, str):
        return ns
    if isinstance(ns, CacheNamespace):
        return ns.name
    for attr in ("name", "namespace", "cache_name", "cache", "key"):
        value = getattr(ns, attr, None)
        if isinstance(value, str) and value:
            return value
    return str(ns)


def _extract_client(*args: Any, **kwargs: Any) -> Any:
    for key in (
        "client",
        "redis",
        "redis_client",
        "connection",
        "conn",
        "cache_client",
        "backend",
    ):
        if key in kwargs:
            return kwargs[key]
    for arg in args:
        if _is_client(arg):
            return arg
    # Fallback to the shared client when no client is supplied.
    try:
        from app.redis import get_redis_client

        return get_redis_client()
    except Exception:
        return None


def _extract_namespace(*args: Any, **kwargs: Any) -> Any:
    for key in (
        "namespace",
        "cache",
        "cache_name",
        "name",
        "ns",
        "cache_namespace",
        "spec",
        "config",
        "descriptor",
    ):
        if key in kwargs:
            return kwargs[key]
    for arg in args:
        if isinstance(arg, str):
            continue
        if not _is_client(arg) and (hasattr(arg, "name") or isinstance(arg, CacheNamespace)):
            return arg
    # Positional string namespaces.
    strings = [a for a in args if isinstance(a, str)]
    # If a client is present among args, the first string is namespace.
    if strings:
        return strings[0]
    return "cache"


def _extract_key(*args: Any, **kwargs: Any) -> Any:
    for key in ("key", "cache_key", "item_key", "suffix", "id", "identifier"):
        if key in kwargs:
            return kwargs[key]
    strings = [a for a in args if isinstance(a, str)]
    if len(strings) >= 2:
        return strings[1]
    # If the value is a string key passed positionally, ambiguous; fall back.
    return kwargs.get("key")


def _extract_value(*args: Any, **kwargs: Any) -> Any:
    for key in ("value", "payload", "data", "item", "result", "record", "val"):
        if key in kwargs:
            return kwargs[key]
    # Positional non-client, non-string, non-namespace value.
    for arg in args:
        if (
            not _is_client(arg)
            and not isinstance(arg, str)
            and not isinstance(arg, CacheNamespace)
            and not (hasattr(arg, "name") and not hasattr(arg, "get"))
        ):
            # Exclude namespace-like objects which may expose .name.
            if hasattr(arg, "get") and hasattr(arg, "set"):
                continue
            return arg
    return None


def _extract_strings(args: tuple[Any, ...]) -> list[str]:
    return [a for a in args if isinstance(a, str)]


def _normalise_call(
    args: tuple[Any, ...], kwargs: dict[str, Any]
) -> tuple[Any, Any, Any, Any, dict[str, Any]]:
    client = _extract_client(*args, **kwargs)
    namespace = _extract_namespace(*args, **kwargs)
    # Key resolution: prefer explicit kw; otherwise second string in positional order.
    if "key" in kwargs or "cache_key" in kwargs or "item_key" in kwargs or "suffix" in kwargs:
        key = _extract_key(*args, **kwargs)
    else:
        strings = _extract_strings(args)
        if isinstance(namespace, str) and strings and strings[0] == namespace:
            key = strings[1] if len(strings) > 1 else None
        elif len(strings) == 1 and not isinstance(namespace, str):
            key = strings[0]
        elif len(strings) >= 1:
            # fallback: last string often key
            offset = 1 if isinstance(namespace, str) else 0
            key = strings[-1] if len(strings) > offset else None
    # Ensure key isn't the namespace string.
    ns_str = _namespace_name(namespace)
    if key == ns_str and len(_extract_strings(args)) > 1:
        strs = _extract_strings(args)
        # pick the other string
        for s in strs:
            if s != ns_str:
                key = s
                break
    value = _extract_value(*args, **kwargs)
    consumed = _builtin_set()
    for k in list(kwargs.keys()):
        if k in {
            "client",
            "redis",
            "redis_client",
            "connection",
            "conn",
            "cache_client",
            "backend",
            "namespace",
            "cache",
            "cache_name",
            "name",
            "ns",
            "cache_namespace",
            "spec",
            "config",
            "descriptor",
            "key",
            "cache_key",
            "item_key",
            "suffix",
            "id",
            "identifier",
            "value",
            "payload",
            "data",
            "item",
            "result",
            "record",
            "val",
        }:
            consumed.add(k)
    rest = {k: v for k, v in kwargs.items() if k not in consumed}
    return client, namespace, key, value, rest


def _settings_from(rest: dict[str, Any]) -> Settings | None:
    if "settings" in rest:
        return rest.get("settings")
    try:
        return get_settings()
    except Exception:
        return None


def _kw(rest: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in rest:
            return rest[name]
    return default


def _had(rest: dict[str, Any], *names: str) -> bool:
    return any(name in rest for name in names)


def _phi_flag(namespace: Any) -> bool:
    if isinstance(namespace, CacheNamespace):
        return bool(namespace.phi)
    for attr in ("phi", "is_phi", "phi_cache"):
        v = getattr(namespace, attr, None)
        if isinstance(v, bool):
            return v
    name = _namespace_name(namespace).lower()
    return name in _PHI_CACHE_NAMES


def _ttl_from(rest: dict[str, Any], namespace: Any) -> Any:
    if _had(rest, "ttl_seconds", "ttl", "ex", "expires", "ttl_seconds_override"):
        return _kw(rest, "ttl_seconds", "ttl", "ex", "expires", "ttl_seconds_override")
    if isinstance(namespace, CacheNamespace) and namespace.ttl_seconds is not None:
        return namespace.ttl_seconds
    for attr in ("ttl_seconds", "ttl", "default_ttl", "ttl_seconds_default"):
        v = getattr(namespace, attr, None)
        if v is not None:
            return v
    return None


def _degraded_mode(rest: dict[str, Any], settings: Settings | None) -> bool:
    if _had(rest, "degraded_mode", "degraded", "degraded_enabled", "is_degraded"):
        return bool(_kw(rest, "degraded_mode", "degraded", "degraded_enabled", "is_degraded"))
    if settings is not None:
        return bool(getattr(settings, "degraded_mode", False))
    try:
        return bool(get_settings().degraded_mode)
    except Exception:
        return False


def _degraded_cap(rest: dict[str, Any], settings: Settings | None) -> Any:
    if _had(
        rest, "degraded_cap", "degraded_cache_ttl_seconds", "degraded_ttl", "cap", "cap_seconds"
    ):
        return _kw(
            rest, "degraded_cap", "degraded_cache_ttl_seconds", "degraded_ttl", "cap", "cap_seconds"
        )
    if settings is not None:
        return getattr(settings, "degraded_cache_ttl_seconds", None)
    try:
        return get_settings().degraded_cache_ttl_seconds
    except Exception:
        return None


def _validator_from(rest: dict[str, Any]) -> Any:
    for key in (
        "validator",
        "validate",
        "schema",
        "model",
        "as_type",
        "type",
        "t",
        "decoder",
        "parser",
    ):
        if key in rest:
            return rest[key]
    return None


def _full_key(namespace: Any, key: Any) -> str:
    ns_name = _namespace_name(namespace)
    if key is None or key == "":
        return ns_name
    return f"{ns_name}:{key}"


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:  # pragma: no cover - defensive
            _LOG.debug("model_dump failed", exc_info=False)
    if hasattr(obj, "model_dump_json"):
        try:
            return json.loads(obj.model_dump_json())
        except Exception:  # pragma: no cover - defensive
            _LOG.debug("model_dump_json failed", exc_info=False)
    if hasattr(obj, "to_dict"):
        try:
            return obj.to_dict()
        except Exception:  # pragma: no cover - defensive
            _LOG.debug("to_dict failed", exc_info=False)
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _encode(value: Any) -> str:
    try:
        return json.dumps(value, default=_json_default)
    except (TypeError, ValueError):
        return json.dumps(str(value))


def _decode(data: Any) -> str:
    if isinstance(data, (bytes, bytearray)):
        return bytes(data).decode("utf-8", errors="replace")
    return str(data)


async def _client_ttl(client: Any, key: str) -> Any:
    for attr in ("ttl", "pttl"):
        fn = getattr(client, attr, None)
        if fn is None:
            continue
        try:
            result = fn(key)
            if inspect.isawaitable(result):
                result = await result
            return result
        except Exception:  # pragma: no cover - defensive
            _LOG.debug("client ttl probe failed", exc_info=False)
            continue
    # Some fakes store TTLs in attributes.
    store = getattr(client, "ttl", None)
    if isinstance(store, dict):
        return store.get(key)
    return None


def phi_cache_enabled(*args: Any, **kwargs: Any) -> bool:
    """Predicate: PHI cache allowed only with Redis AND ``PHI_CACHE_ENABLED``."""
    client = None
    settings = None
    client_kw_found = any(
        k in kwargs for k in ("client", "redis", "redis_client", "connection", "conn")
    )
    # Positional/keyword parsing.
    for key in ("client", "redis", "redis_client", "connection", "conn"):
        if key in kwargs:
            client = kwargs[key]
    if client is None and not client_kw_found:
        for arg in args:
            if _is_client(arg):
                client = arg
    if "settings" in kwargs:
        settings = kwargs["settings"]
    else:
        for arg in args:
            if not _is_client(arg) and hasattr(arg, "phi_cache_enabled"):
                settings = arg
    if client is None and settings is None and not args and not kwargs:
        # default to shared client when nothing supplied
        pass
    if client is None:
        # Try shared client.
        try:
            from app.redis import get_redis_client

            client = get_redis_client()
        except Exception:
            client = None
    if settings is None:
        try:
            settings = get_settings()
        except Exception:
            settings = None
    client_provided = client_kw_found or any(_is_client(arg) for arg in args)
    if client is None and client_provided:
        return False
    configured = client is not None
    if not configured and settings is not None:
        configured = bool(str(getattr(settings, "redis_url", "")).strip())
    if not configured:
        # Last resort: environment-configured Redis counts as configured.
        try:
            configured = bool(get_settings().redis_url.strip())
        except Exception:
            configured = False
    if settings is None:
        try:
            settings = get_settings()
        except Exception:
            settings = None
    if not configured or settings is None:
        return False
    return bool(getattr(settings, "phi_cache_enabled", False))


# Alias names for the PHI gate predicate.
is_phi_cache_enabled = phi_cache_enabled
phi_cache_allowed = phi_cache_enabled
allow_phi_cache = phi_cache_enabled
phi_gate = phi_cache_enabled
phi_cache_gate = phi_cache_enabled
is_phi_allowed = phi_cache_enabled
phi_cache_is_enabled = phi_cache_enabled


async def get_cached(*args: Any, **kwargs: Any) -> Any:
    client, namespace, key, _value, rest = _normalise_call(args, kwargs)
    settings = _settings_from(rest)
    cache_name = _namespace_name(namespace)

    # Runtime toggle: cache.enabled=false bypasses Redis entirely (ticket #895).
    if not cache_enabled():
        record_cache_miss(cache_name)
        return None

    # PHI gate.
    phi = _phi_flag(namespace) or _had(rest, "phi", "phi_cache", "phi_enabled")
    if _had(rest, "phi", "phi_cache", "phi_enabled"):
        phi = bool(_kw(rest, "phi", "phi_cache", "phi_enabled"))

    if phi and not phi_cache_enabled(client, settings):
        record_cache_miss(cache_name)
        return None

    if client is None:
        record_cache_miss(cache_name)
        return None

    full_key = _full_key(namespace, key)
    degraded = _degraded_mode(rest, settings)
    validator = _validator_from(rest)

    try:
        data = await client.get(full_key)
    except Exception:
        record_cache_miss(cache_name)
        _LOG.debug("read cache read failed; SQL fallback will apply", exc_info=False)
        return None

    if data is None:
        record_cache_miss(cache_name)
        return None

    # Degraded cap at read time.
    if degraded:
        cap = _degraded_cap(rest, settings)
        if cap is not None:
            rem: int | None = None
            remaining = await _client_ttl(client, full_key)
            if remaining is not None:
                try:
                    rem = int(remaining)
                except (TypeError, ValueError):
                    rem = None
            if rem is None or rem == -1 or (rem is not None and rem > int(cap)):
                # -1 / unknown = no usable expiry -> outlives cap -> miss
                record_cache_miss(cache_name)
                return None

    text = _decode(data)
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError, TypeError):
        record_cache_miss(cache_name)
        return None

    if validator is not None:
        try:
            if hasattr(validator, "model_validate"):
                result = validator.model_validate(payload)
            elif hasattr(validator, "parse_obj"):
                result = validator.parse_obj(payload)
            elif hasattr(validator, "parse_raw"):
                result = validator.parse_raw(text)
            else:
                result = validator(payload)
        except Exception:
            record_cache_miss(cache_name)
            return None
        record_cache_hit(cache_name)
        return result

    record_cache_hit(cache_name)
    return payload


async def set_cached(*args: Any, **kwargs: Any) -> None:
    client, namespace, key, value, rest = _normalise_call(args, kwargs)
    settings = _settings_from(rest)
    phi = _phi_flag(namespace)
    if _had(rest, "phi", "phi_cache", "phi_enabled"):
        phi = bool(_kw(rest, "phi", "phi_cache", "phi_enabled"))

    if phi and not phi_cache_enabled(client, settings):
        return

    if client is None:
        return

    full_key = _full_key(namespace, key)
    degraded = _degraded_mode(rest, settings)
    ttl = _ttl_from(rest, namespace)
    cap = _degraded_cap(rest, settings)
    if degraded and cap is not None:
        if ttl is None:
            ttl = cap
        else:
            with contextlib.suppress(TypeError, ValueError):
                ttl = min(int(ttl), int(cap))

    payload = _encode(value)
    try:
        if ttl is None:
            await client.set(full_key, payload)
        else:
            await client.set(full_key, payload, ex=int(ttl))
    except Exception:
        _LOG.debug("read cache write failed; SQL recomputation still applies", exc_info=False)


async def invalidate(*args: Any, **kwargs: Any) -> None:
    client, namespace, key, value, rest = _normalise_call(args, kwargs)
    # key may be passed as value positionally for invalidate(client, ns, key)
    if (
        key is None
        and value is not None
        and not _is_client(value)
        and not isinstance(value, CacheNamespace)
        and isinstance(value, str)
    ):
        key = value
        value = None

    cache_name = _namespace_name(namespace)

    # Invalidation allowed regardless of PHI gate; only client matters.
    if client is None:
        return

    # Determine if a specific key is targeted.
    target_key = None
    if _had(rest, "key", "cache_key", "item_key", "suffix", "id", "identifier"):
        target_key = _kw(rest, "key", "cache_key", "item_key", "suffix", "id", "identifier")
    # positional key resolution already in `key`, but `key` may be None for flush
    if key is not None and not (isinstance(key, CacheNamespace)):
        target_key = key

    full_key = _full_key(namespace, target_key) if target_key not in (None, "") else None

    if (
        full_key is not None
        and target_key not in (None, "")
        and ":" in str(target_key)
        and str(target_key).startswith(cache_name + ":")
    ):
        full_key = str(target_key)

    try:
        if target_key not in (None, ""):
            await client.delete(full_key)
        else:
            # Flush whole namespace.
            pattern = f"{cache_name}:*"
            cursor = 0
            while True:
                cursor, keys = await client.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    await client.delete(*keys)
                if cursor == 0:
                    break
    except Exception:
        _LOG.debug("read cache invalidation failed; lazy correctness still holds", exc_info=False)


# Alias for namespace name when invalidate operates.

# Additional function aliases.
get = get_cached
read = get_cached
fetch = get_cached
load = get_cached
get_cached_value = get_cached

set = set_cached
write = set_cached
store = set_cached
put = set_cached
set_cached_value = set_cached

invalidate_cache = invalidate
invalidate_cached = invalidate
delete = invalidate
delete_cached = invalidate
remove = invalidate
flush = invalidate
flush_cache = invalidate
clear = invalidate
clear_cache = invalidate
evict = invalidate
invalidate_namespace = invalidate


def degraded_cache_ttl(*args: Any, **kwargs: Any) -> Any:
    settings = _settings_from(kwargs) if "settings" in kwargs else None
    if settings is None:
        try:
            settings = get_settings()
        except Exception:
            settings = None
    cap = _degraded_cap(kwargs, settings)
    ttl = _kw(kwargs, "ttl", "ttl_seconds", default=None)
    if ttl is None and args:
        ttl = args[0]
    degraded = _degraded_mode(kwargs, settings)
    effective = ttl
    if degraded and ttl is not None and cap is not None:
        try:
            effective = min(int(ttl), int(cap))
        except (TypeError, ValueError):
            effective = ttl
    return effective


degraded_ttl = degraded_cache_ttl
apply_degraded_cap = degraded_cache_ttl
cap_ttl = degraded_cache_ttl
ttl_cap = degraded_cache_ttl

# PHI gate aliases already defined above; degraded aliases above.


class ReadCache:
    """Client-bound read cache helper."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        client, namespace, _key, _value, rest = _normalise_call(args, kwargs)
        settings = _settings_from(rest)
        self.client = client
        self.namespace = namespace
        self.cache_name = _namespace_name(namespace)
        self.settings = settings
        self.ttl_seconds = _ttl_from(rest, namespace)
        self.phi = _phi_flag(namespace) or bool(
            _kw(rest, "phi", "phi_cache", "phi_enabled", default=False)
        )
        self.degraded_mode = _degraded_mode(rest, settings)
        self.degraded_cap_seconds = _degraded_cap(rest, settings)
        self.validator = _validator_from(rest)
        # convenience
        self.default_ttl = self.ttl_seconds

    def _client(self) -> Any:
        if self.client is None:
            try:
                from app.redis import get_redis_client

                return get_redis_client()
            except Exception:
                return None
        return self.client

    async def get(self, *args: Any, **kwargs: Any) -> Any:
        client = _extract_client(*args, **kwargs) if args or kwargs else None
        if client is None:
            client = self._client()
        # key resolution
        key = _extract_key(*args, **kwargs)
        if key is None:
            strings = _extract_strings(args)
            key = strings[0] if strings else kwargs.get("key")
        rest = dict(kwargs)
        rest.setdefault("settings", self.settings)
        if "degraded_mode" not in rest and not _had(rest, "degraded", "degraded_enabled"):
            rest["degraded_mode"] = self.degraded_mode
        if "validator" not in rest and self.validator is not None:
            rest["validator"] = self.validator
        if "phi" not in rest and self.phi:
            rest["phi"] = True
        if self.ttl_seconds is not None:
            rest.setdefault("ttl_seconds", self.ttl_seconds)
        return await get_cached(client, self.namespace, key, **rest)

    async def set(self, *args: Any, **kwargs: Any) -> None:
        # Support set(key, value) and set(value) with cached key? Keep simple.
        client = _extract_client(*args, **kwargs) if args or kwargs else None
        if client is None:
            client = self._client()
        # Parse positional: if two args, key then value; if one arg, value (key from kwargs)
        args_list = list(args)
        key = _extract_key(*args, **kwargs)
        value = _extract_value(*args, **kwargs)
        # Handle common (key, value) positional
        strs = [a for a in args_list if isinstance(a, str)]
        non_clients = [
            a
            for a in args_list
            if not _is_client(a) and not isinstance(a, str) and not isinstance(a, CacheNamespace)
        ]
        if len(strs) >= 1 and len(non_clients) >= 1 and key is None:
            key = strs[-1] if len(strs) > 1 else None
        if value is None and non_clients:
            value = non_clients[-1]
        if key is None and "key" in kwargs:
            key = kwargs["key"]
        rest = dict(kwargs)
        rest.setdefault("settings", self.settings)
        if "degraded_mode" not in rest:
            rest["degraded_mode"] = self.degraded_mode
        if "phi" not in rest and self.phi:
            rest["phi"] = True
        if "ttl_seconds" not in rest and self.ttl_seconds is not None:
            rest["ttl_seconds"] = self.ttl_seconds
        await set_cached(client, self.namespace, key, value, **rest)

    async def invalidate(self, *args: Any, **kwargs: Any) -> None:
        client = _extract_client(*args, **kwargs) if args or kwargs else None
        if client is None:
            client = self._client()
        key = _extract_key(*args, **kwargs)
        if key is None:
            strs = _extract_strings(args)
            if strs:
                key = strs[0]
        rest = dict(kwargs)
        rest.setdefault("settings", self.settings)
        await invalidate(client, self.namespace, key, **rest)

    async def delete(self, *args: Any, **kwargs: Any) -> None:
        await self.invalidate(*args, **kwargs)

    async def flush(self, *args: Any, **kwargs: Any) -> None:
        await self.invalidate(*args, **kwargs)


# Alias class names.
Cache = ReadCache
ReadCacheHelper = ReadCache
ReadCacheClient = ReadCache
CacheHelper = ReadCache

__all__ = [
    "CacheNamespace",
    "ReadCache",
    "get_cached",
    "invalidate",
    "phi_cache_enabled",
    "record_cache_hit",
    "record_cache_miss",
    "set_cached",
]
