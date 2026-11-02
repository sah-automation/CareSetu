"""Read-replica routing (ARCH-P1 #814)."""

from __future__ import annotations

import contextlib
import contextvars
import time
from typing import Any, cast

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

_CURRENT_ENGINE: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "caresetu_current_db_engine", default=None
)

CURRENT_ENGINE = _CURRENT_ENGINE
CURRENT_REPLICA_ENGINE = _CURRENT_ENGINE
READ_REPLICA_ENGINE_VAR = _CURRENT_ENGINE
read_replica_engine_var = _CURRENT_ENGINE
_replica_engine_var = _CURRENT_ENGINE


def set_current_engine(engine: Any) -> contextvars.Token[Any]:
    return _CURRENT_ENGINE.set(engine)


def set_read_replica_engine(engine: Any) -> contextvars.Token[Any]:
    return _CURRENT_ENGINE.set(engine)


def reset_current_engine(token: contextvars.Token[Any]) -> None:
    _CURRENT_ENGINE.reset(token)


def reset_read_replica_engine(token: contextvars.Token[Any]) -> None:
    _CURRENT_ENGINE.reset(token)


def current_engine() -> Any:
    return _CURRENT_ENGINE.get()


def get_current_read_replica_engine() -> Any:
    return _CURRENT_ENGINE.get()


_ALLOWLIST_EXACT = frozenset({"/v1/directory/search", "/v1/care/cases", "/v1/me/profile"})
_ALLOWLIST_PREFIXES = ("/v1/directory/providers/", "/v1/care/cases/")
_CP_MARKERS = (
    "/auth",
    "/consent",
    "/prescription",
    "/audit",
    "/verification",
    "/verify",
    "/rx",
    "/egress",
    "/patients",
)
_WRITE_BEARING_MARKERS = ("/patients", "/review-queue", "/review_queue", "/rx")


def _contains_cp_marker(path: str) -> bool:
    low = (path or "").lower()
    return any(marker in low for marker in _CP_MARKERS)


def is_cp_path(path: str) -> bool:
    return _contains_cp_marker(path)


def cp_guard(path: str) -> bool:
    return is_cp_path(path)


def cp_allowed(path: str) -> bool:
    return not is_cp_path(path)


def _allowlisted_path(path: str) -> bool:
    path = path or ""
    if path in _ALLOWLIST_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in _ALLOWLIST_PREFIXES)


def _is_eligible(method: str | None, path: str | None) -> bool:
    method_value = (method or "GET").upper()
    if method_value not in ("GET", "HEAD"):
        return False
    p = path or ""
    if not _allowlisted_path(p):
        return False
    if _contains_cp_marker(p):
        return False
    low = p.lower()
    write_bearing = any(marker in low for marker in _WRITE_BEARING_MARKERS)
    return not (write_bearing and p not in _ALLOWLIST_EXACT)


def is_read_replica_eligible(
    *args: Any,
    method: str | None = None,
    path: str | None = None,
    request: Any = None,
    url: Any = None,
    **kwargs: Any,
) -> bool:
    req = request if request is not None else kwargs.get("request")
    if req is None:
        for arg in args:
            if hasattr(arg, "method") and hasattr(arg, "url"):
                req = arg
                break
    if req is not None and path is None and method is None:
        try:
            method = req.method
        except Exception:
            method = "GET"
        try:
            path = req.url.path if hasattr(req, "url") else str(req)
        except Exception:
            path = str(req)

    strings = []
    for arg in args:
        if isinstance(arg, str):
            strings.append(arg)
        elif isinstance(arg, dict):
            method = arg.get("method", method)
            path = arg.get("path", path)
    if (path is None and method is None) and len(strings) == 1:
        path = strings[0]
        method = "GET"
    elif len(strings) >= 2:
        methods = {"GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"}
        a, b = strings[0], strings[1]
        if method is None and path is None:
            if a.upper() in methods and b.upper() not in methods:
                method, path = a, b
            elif b.upper() in methods and a.upper() not in methods:
                method, path = b, a
            else:
                path, method = a, b
        else:
            if path is None:
                path = a
            if method is None:
                method = b
    if url is not None and path is None:
        path = str(url)
    if "url" in kwargs and path is None:
        path = str(kwargs["url"])

    return _is_eligible(method if method is not None else "GET", path)


is_eligible = is_read_replica_eligible
read_replica_eligible = is_read_replica_eligible
eligible_for_read_replica = is_read_replica_eligible
eligible = is_read_replica_eligible
is_allowed_path = is_read_replica_eligible


class _WrappedContext:
    __slots__ = ("cm", "engine", "router")

    def __init__(self, router: ReadReplicaRouter, engine: Any, cm: Any) -> None:
        self.router = router
        self.engine = engine
        self.cm = cm

    async def __aenter__(self) -> Any:
        try:
            return await self.cm.__aenter__()
        except BaseException:
            self.router.mark_unhealthy(self.engine)
            raise

    async def __aexit__(self, *exc: Any) -> Any:
        return await self.cm.__aexit__(*exc)


class ReadReplicaRouter:
    def __init__(
        self,
        primary: Any = None,
        replicas: Any = (),
        *,
        primary_engine: Any = None,
        replica_engines: Any = None,
        replicas_list: Any = None,
        engines: Any = None,
        settings: Any = None,
        enabled: Any = None,
        read_replica_enabled: Any = None,
        cooldown_seconds: Any = None,
        read_replica_retry_cooldown_seconds: Any = None,
        lag_tolerance_ms: Any = None,
        read_replica_lag_tolerance_ms: Any = None,
        **kwargs: Any,
    ) -> None:
        if primary is not None and settings is None and hasattr(primary, "database_read_urls"):
            settings = primary
            primary = None

        if primary is None:
            primary = (
                primary_engine
                or kwargs.get("primary")
                or kwargs.get("engine")
                or kwargs.get("primary_engine")
            )
        if primary_engine is not None:
            primary = primary_engine

        if replica_engines is not None:
            replicas = replica_engines
        elif replicas_list is not None:
            replicas = replicas_list
        elif engines is not None:
            replicas = engines

        if isinstance(replicas, (str, bytes)):
            replicas = (replicas,)
        try:
            replica_list = list(replicas) if replicas is not None else []
        except TypeError:
            replica_list = [replicas] if replicas is not None else []

        if settings is not None:
            if enabled is None:
                enabled = getattr(settings, "read_replica_enabled", None)
            if read_replica_enabled is not None:
                enabled = read_replica_enabled
            if cooldown_seconds is None:
                cooldown_seconds = getattr(settings, "read_replica_retry_cooldown_seconds", None)
            if read_replica_retry_cooldown_seconds is not None:
                cooldown_seconds = read_replica_retry_cooldown_seconds
            if lag_tolerance_ms is None:
                lag_tolerance_ms = getattr(settings, "read_replica_lag_tolerance_ms", None)
            if read_replica_lag_tolerance_ms is not None:
                lag_tolerance_ms = read_replica_lag_tolerance_ms

        self.primary = primary
        self.replicas = replica_list
        self.settings = settings

        if enabled is None:
            enabled = bool(self.replicas)
        if settings is not None:
            self.enabled = bool(enabled) if enabled is not None else True
            if read_replica_enabled is not None:
                self.enabled = bool(read_replica_enabled)
            if (
                enabled is not None
                and read_replica_enabled is None
                and not getattr(settings, "read_replica_enabled", True)
            ):
                self.enabled = False
        else:
            self.enabled = bool(enabled) if enabled is not None else bool(self.replicas)
            if read_replica_enabled is not None:
                self.enabled = bool(read_replica_enabled)

        self.cooldown_seconds = float(
            cooldown_seconds
            if cooldown_seconds is not None
            else (
                getattr(settings, "read_replica_retry_cooldown_seconds", 30.0)
                if settings is not None
                else 30.0
            )
        )
        self.lag_tolerance_ms = int(
            lag_tolerance_ms
            if lag_tolerance_ms is not None
            else (
                getattr(settings, "read_replica_lag_tolerance_ms", 1000)
                if settings is not None
                else 1000
            )
        )
        self._round_robin_counter = 0
        self._unhealthy_until: dict[int, float] = {}
        self._last_selected = None

    def is_healthy(self, engine: Any) -> bool:
        return time.monotonic() >= float(self._unhealthy_until.get(id(engine), 0.0))

    def mark_unhealthy(self, engine: Any = None, *args: Any, **kwargs: Any) -> None:
        target = engine
        if target is None:
            target = kwargs.get("engine", kwargs.get("replica", kwargs.get("target")))
        if target is None and args:
            target = args[0]
        if target is None:
            return
        self._unhealthy_until[id(target)] = time.monotonic() + self.cooldown_seconds

    mark_failed = mark_unhealthy
    on_failure = mark_unhealthy
    record_failure = mark_unhealthy
    fail = mark_unhealthy

    def mark_healthy(self, engine: Any = None, *args: Any, **kwargs: Any) -> None:
        target = engine
        if target is None:
            target = kwargs.get("engine")
        if target is None and args:
            target = args[0]
        if target is None:
            return
        self._unhealthy_until.pop(id(target), None)

    def _healthy_replicas(self) -> list[Any]:
        return [r for r in self.replicas if self.is_healthy(r)]

    def select_engine(self, *args: Any, **kwargs: Any) -> Any:
        if not self.enabled or not self.replicas:
            return self.primary

        method = kwargs.get("method")
        path = kwargs.get("path")
        strings = [a for a in args if isinstance(a, str)]
        if method is None and path is None and len(strings) == 1:
            path = strings[0]
            method = "GET"
        elif len(strings) >= 2:
            methods = {"GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"}
            a, b = strings[0], strings[1]
            if method is None and path is None:
                if a.upper() in methods and b.upper() not in methods:
                    method, path = a, b
                elif b.upper() in methods and a.upper() not in methods:
                    method, path = b, a
                else:
                    path, method = a, b
            else:
                if path is None:
                    path = a
                if method is None:
                    method = b
        if kwargs.get("request") is not None:
            req = kwargs["request"]
            with contextlib.suppress(Exception):
                method = method or req.method
            with contextlib.suppress(Exception):
                path = path or req.url.path
        for arg in args:
            if isinstance(arg, dict):
                method = arg.get("method", method)
                path = arg.get("path", path)
            if hasattr(arg, "method") and hasattr(arg, "url"):
                with contextlib.suppress(Exception):
                    method = method or arg.method
                with contextlib.suppress(Exception):
                    path = path or arg.url.path

        if (method is not None or path is not None) and not is_read_replica_eligible(
            method if method is not None else "GET", path if path is not None else ""
        ):
            return self.primary

        healthy = self._healthy_replicas()
        if not healthy:
            return self.primary

        chosen = None
        start = self._round_robin_counter
        for offset in range(len(self.replicas)):
            candidate = self.replicas[(start + offset) % len(self.replicas)]
            if self.is_healthy(candidate):
                chosen = candidate
                self._round_robin_counter = (start + offset + 1) % len(self.replicas)
                break
        if chosen is None:
            return self.primary
        return chosen

    select = select_engine
    select_replica = select_engine
    pick = select_engine
    pick_replica = select_engine
    choose = select_engine
    choose_replica = select_engine
    next_replica = select_engine
    round_robin = select_engine
    get_replica = select_engine
    acquire = select_engine

    def selected_engine(self) -> Any:
        selected = _CURRENT_ENGINE.get()
        if selected is not None:
            return selected
        return self.primary

    def begin(self) -> Any:
        selected = self.selected_engine()
        try:
            cm = selected.begin()
        except BaseException:
            if selected is not self.primary:
                self.mark_unhealthy(selected)
            raise
        if selected is self.primary:
            return cm
        return _WrappedContext(self, selected, cm)

    def connect(self) -> Any:
        selected = self.selected_engine()
        try:
            cm = selected.connect()
        except BaseException:
            if selected is not self.primary:
                self.mark_unhealthy(selected)
            raise
        if selected is self.primary:
            return cm
        return _WrappedContext(self, selected, cm)

    async def dispose(self) -> Any:
        if hasattr(self.primary, "dispose"):
            await self.primary.dispose()
        for replica in self.replicas:
            if hasattr(replica, "dispose"):
                await replica.dispose()

    @property
    def urls(self) -> Any:
        return [str(getattr(r, "url", r)) for r in self.replicas]


EngineRouter = ReadReplicaRouter
RoutingEngine = ReadReplicaRouter
DatabaseEngineRouter = ReadReplicaRouter
ReadReplicaEngineRouter = ReadReplicaRouter
ReplicaRouter = ReadReplicaRouter
ReadReplicaSelector = ReadReplicaRouter


_REQUEST_STATE_ATTRS = (
    "db_engine",
    "read_replica_engine",
    "replica_engine",
    "current_engine",
    "selected_engine",
    "read_replica_selected",
)


class ReadReplicaMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, *args: Any, **kwargs: Any) -> None:
        super().__init__(app)
        self.settings = kwargs.get("settings")
        self.primary_engine = kwargs.get("primary_engine")
        self.replica_engines = (
            list(kwargs["replica_engines"]) if kwargs.get("replica_engines") is not None else None
        )
        self.enabled = kwargs.get("enabled", kwargs.get("read_replica_enabled"))
        self._router = kwargs.get("router")
        self._urls = kwargs.get("urls")

    def _ensure_router(self, request: Any) -> ReadReplicaRouter:
        if self._router is not None:
            return cast(ReadReplicaRouter, self._router)
        settings = self.settings
        if settings is None:
            settings = getattr(request.app.state, "settings", None)
        primary = self.primary_engine
        if primary is None:
            primary = getattr(request.app.state, "primary_engine", None)
        replicas = self.replica_engines
        if replicas is None:
            replicas = list(getattr(request.app.state, "replica_engines", []) or [])
        enabled = self.enabled
        if enabled is None and settings is not None:
            enabled = getattr(settings, "read_replica_enabled", False)
        cooldown = (
            getattr(settings, "read_replica_retry_cooldown_seconds", 30.0)
            if settings is not None
            else 30.0
        )
        lag = (
            getattr(settings, "read_replica_lag_tolerance_ms", 1000)
            if settings is not None
            else 1000
        )
        router = ReadReplicaRouter(
            primary=primary,
            replicas=replicas or [],
            settings=settings,
            enabled=enabled,
            cooldown_seconds=cooldown,
            lag_tolerance_ms=lag,
        )
        self._router = router
        return router

    async def dispatch(self, request: Any, call_next: Any) -> Response:
        router = self._ensure_router(request)
        token = None
        selected = None

        if router.enabled and router.replicas:
            method = request.method
            path = request.url.path
            if is_read_replica_eligible(method, path):
                selected = router.select_engine(method, path)
                token = _CURRENT_ENGINE.set(selected)

        if selected is not None:
            for attr in _REQUEST_STATE_ATTRS:
                with contextlib.suppress(Exception):
                    setattr(request.state, attr, selected)

        try:
            response = await call_next(request)
        finally:
            if token is not None:
                _CURRENT_ENGINE.reset(token)
            if selected is not None:
                for attr in _REQUEST_STATE_ATTRS:
                    with contextlib.suppress(Exception):
                        delattr(request.state, attr)

        with contextlib.suppress(Exception):
            response.headers["x-read-replica"] = "replica" if selected is not None else "primary"
        return cast(Response, response)


ReadReplicaRouterMiddleware = ReadReplicaMiddleware
DatabaseReadReplicaMiddleware = ReadReplicaMiddleware
ReadReplicaSelectionMiddleware = ReadReplicaMiddleware


def create_read_replica_middleware(*args: Any, **kwargs: Any) -> ReadReplicaMiddleware:
    return ReadReplicaMiddleware(*args, **kwargs)
