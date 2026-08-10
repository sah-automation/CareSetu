"""CareSetu event-bus infrastructure (ADR-0002/0003, PHASE-1).

The async seam between modules: the transactional-outbox DDL template and
bootstrap constants, the typed event ``Envelope``, the transactional outbox
writer, the idempotent-subscriber ``consumed_events`` ledger helper, the
``HandlerRegistry``, and the synchronous dispatch/fan-out step. The dispatcher
poll loop that drives ``dispatch`` arrives in T3a (#22) in this package too.
"""
