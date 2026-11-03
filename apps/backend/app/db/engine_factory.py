"""Compatibility shim - implementation lives in ``app.db.engine`` (ARCH-P1 #813)."""

from app.db.engine import (
    AsyncEngineLike,
    AsyncEngineProtocol,
    EngineLike,
    create_engine,
    create_primary_engine,
    create_read_replica_engines,
    dispose_engine,
)

__all__ = [
    "AsyncEngineLike",
    "AsyncEngineProtocol",
    "EngineLike",
    "create_engine",
    "create_primary_engine",
    "create_read_replica_engines",
    "dispose_engine",
]
