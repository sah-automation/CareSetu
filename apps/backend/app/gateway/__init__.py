"""Gateway middleware stack (PHASE-1 T7b, #29; PHASE-2 T8, #59).

The in-app FastAPI middleware seam where caller identity is established before
routes run - distinct from the ``edge`` (the TLS reverse proxy at the VM
perimeter). ``jwt_verify`` verifies the presented access JWT and attaches a
scoped ``Principal``; ``rate_limit`` caps the OTP/auth surface per caller
(``NFR-SEC-004``). Both are disabled by default; their order and the
``Principal`` shape are the contract the app shell wires.
"""

from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.gateway.principal import Principal
from app.gateway.rate_limit import RateLimitMiddleware

__all__ = ["JWTVerifyMiddleware", "Principal", "RateLimitMiddleware"]
