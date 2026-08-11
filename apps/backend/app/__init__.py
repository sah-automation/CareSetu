"""CareSetu FastAPI application shell (PHASE-1 T7a, #28).

The shared application entrypoint: env-driven ``Settings`` (config.py) and the
``create_app`` factory plus the module-level ASGI ``app`` instance (main.py)
that uvicorn serves. The worker (#30) and gateway (#29) build on this shell;
no business routes live here - those arrive with the module adapters from
Phase 2 onward.
"""
