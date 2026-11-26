# ADR-0020: Private profile-media bucket for profile photos

**Status:** accepted
**Date:** 2026-09-24
**Decides:** US-20/34 of the parent spec (#529) - where profile photos live so they never leak. A private `profile-media` Supabase bucket keyed by role prefix (`patient/`, `doctor/`) and user id, never public, AES-256-GCM at rest, service-role writes, object keys referenced only in SQL, and reads streamed through the backend.
**Traceability:** `FEAT-005` (profiles), `MOD-001` (identity profile), `MOD-002` (partner profile), `security-phii-standards.md`, parent #529 US-20/34. Implemented by #532 (storage adapter), #533 (patient upload/remove/read surface), #542 (doctor profile photo surface), and #543 (doctor profile photo wiring).

## Context

Profile photos are PII: a photo reliably identifies a person. The patient profile surface (`/v1/me/*`) already stores identity data in SQL, and doctors need to see a patient's photo inside the consent-gated patient detail. The existing intake-media store (protocol + factory + local/supabase backends, AES-256-GCM encryption, service-role writes) is the proven media-holding pattern in the repo - a public bucket or frontend-writable path would violate `NFR-SEC-006` and the PHI storage rules (media refs only in SQL, `coding-standards.md` §7).

## Decision

### D1 - Private bucket, role-prefixed keys

A new private Supabase bucket `profile-media` (never public, no public-read policies) storing objects keyed by role prefix and owner id: `patient/{user_id}/...` and `doctor/{user_id}/...`. The role prefix and key layout are fixed up front so a later image-resize step slots in without an API change. The delivered adapter exposes `PATIENT_PREFIX = "patient"`, `DOCTOR_PREFIX = "doctor"`, `MEDIA_BUCKET = "profile-media"`, and enforces the prefix invariant on both save and read paths.

### D2 - Backend-only writes, gated reads

Writes use the service-role only - never the client - through a new storage adapter (`ProfileMediaStore` protocol, `build_profile_media_store` factory) that copies the intake-media adapter shape (AES-256-GCM at rest, local + Supabase backends). The adapter and config (`backend`, `root`, `key`, retry policy, circuit-breaker thresholds, timeout) are selected at the composition root. Reads stream through the backend: the session user reads their own photo via the profile surface, and a doctor reads a patient's photo only through the consent-gated patient-detail route. SQL holds object keys only (`photo_ref`), never blobs. The remote (Supabase) store is wrapped by `ResilientProfileMediaStore` with bounded timeouts, exponential backoff with capped retries, and a shared cooldown circuit breaker on transient errors (`NFR-PERF-003`); the `local` filesystem backend is deliberately bare, since a local disk call is neither remote nor flaky.

### D3 - Upload contract

Uploads validate content-type (JPEG/PNG/WebP only, GIF rejected) and size, then record the stored object key on the profile. Removal deletes the object and clears the key. Object keys are generated as `{prefix}/{subject_id}/{hex32}.enc` (`secrets.token_hex(16)` - 16 random bytes, 32 hex characters), written with a `.enc` extension to signal encrypted ciphertext, and validated on every read to enforce prefix/shape. The ceiling is enforced before full body ingestion, but by two different mechanisms that must be kept in step: the doctor profile-photo route reads `PROFILE_MEDIA_MAX_UPLOAD_BYTES` from `app.state.profile_media_max_upload_bytes`, while the patient `/v1/me/photo` route uses the `MAX_PROFILE_PHOTO_BYTES` constant in the identity facade (5 MB, matching the documented default). `build_profile_media_store` itself takes explicit keyword arguments and reads no settings, so raising `PROFILE_MEDIA_MAX_UPLOAD_BYTES` alone relaxes only the doctor path.

## Consequences

- Photos are never publicly addressable; a leaked URL is not a leak because the bucket has no public policies.
- The proven intake-media shape is reused, keeping encryption, backends, and factory wiring consistent across the codebase.
- Keys (not resized blobs) in SQL mean the image-resize pipeline can be added later without touching the profile API contract.
- Every doctor read of a patient photo flows through the consent gate, preserving the standing-grant boundary for visual PHI.
- The adapter is registered in `internal-modules.md` §3.13 under the same schema-less exception ADR-0019 registers for the `MOD-012` console seam: it owns no private schema, no outbox, and no domain tables, so the `coding-standards.md` §2 / ADR-0003 "one module, one schema" rule does not apply to it. It remains a port, not a `MOD-xxx` bounded context.
