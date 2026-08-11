"""Gateway middleware stack (PHASE-1 T7b, #29).

The in-app FastAPI middleware seam where caller identity is established before
routes run - distinct from the ``edge`` (the TLS reverse proxy at the VM
perimeter). ``jwt_verify`` and ``rate_limit`` are accept-all stubs disabled by
default; their order and the ``Principal`` shape are the contract Phase 2 fills
in with real verification and limiting.
"""

from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.gateway.principal import Principal
from app.gateway.rate_limit import RateLimitMiddleware

__all__ = ["JWTVerifyMiddleware", "Principal", "RateLimitMiddleware"]
