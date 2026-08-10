"""CareSetu event-bus infrastructure (ADR-0002/0003, PHASE-1).

The async seam between modules: the transactional-outbox DDL template and
bootstrap constants. The dispatcher, envelope, and handler registry arrive in
later Phase 1 tickets and live in this package too.
"""
