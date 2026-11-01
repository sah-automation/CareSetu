"""Database engine factory (ARCH-P1 #813).

Exports a narrow engine-like protocol and a factory that resolves the primary
engine from settings. With pooling disabled it keeps today's no-pool behaviour;
with DB_POOL_ENABLED=true it creates a bounded pool using the configured
settings, with pre-ping.
"""

from app.db.engine import (
    AsyncEngineLike,
    AsyncEngineProtocol,
    EngineLike,
    create_engine,
    create_primary_engine,
    create_read_replica_engines,
    dispose_engine,
)
from app.db.read_replica import (
    ReadReplicaMiddleware,
    ReadReplicaRouter,
    is_read_replica_eligible,
)

__all__ = [
    "AsyncEngineLike",
    "AsyncEngineProtocol",
    "EngineLike",
    "ReadReplicaMiddleware",
    "ReadReplicaRouter",
    "create_engine",
    "create_primary_engine",
    "create_read_replica_engines",
    "dispose_engine",
    "is_read_replica_eligible",
]
