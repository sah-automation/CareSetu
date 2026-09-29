"""Shared private profile-media object-storage surface (parent #529, ADR-0020).

Leaf package (no schema, no outbox) hosting the encrypted ``profile-media``
store used by the MOD-001 (patient) and MOD-002 (doctor) profile surfaces. Only
the facade seam (``modules.profile_media.facade``) is a legal cross-module import
target (ADR-0003) - the concrete backends under ``adapters/`` stay internal and
are reached through the composition root only.
"""
