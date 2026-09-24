# ADR-0020: Private profile-media bucket for profile photos

**Status:** accepted
**Date:** 2026-09-24
**Decides:** US-20/34 of the parent spec (#529) - where profile photos live so they never leak. A private `profile-media` Supabase bucket keyed by role prefix (`patient/`, `doctor/`) and user id, never public, AES-256-GCM at rest, service-role writes, object keys referenced only in SQL, and reads streamed through the backend.
**Traceability:** `FEAT-005` (profiles), `MOD-001` (identity profile), `security-phii-standards.md`, parent #529 US-20/34. Implemented by #532 (storage adapter) and #533 (upload/remove routes).

## Context

Profile photos are PII: a photo reliably identifies a person. The patient profile surface (`/v1/me/*`) already stores identity data in SQL, and doctors need to see a patient's photo inside the consent-gated patient detail. The existing intake-media store (protocol + factory + local/supabase backends, AES-256-GCM encryption, service-role writes) is the proven media-holding pattern in the repo - a public bucket or frontend-writable path would violate `NFR-SEC-006` and the PHI storage rules (media refs only in SQL, `coding-standards.md` §7).

## Decision

### D1 - Private bucket, role-prefixed keys

A new private Supabase bucket `profile-media` (never public, no public-read policies) storing objects keyed by role prefix and owner id: `patient/{user_id}/...` and `doctor/{user_id}/...`. The role prefix and key layout are fixed up front so a later image-resize step slots in without an API change.

### D2 - Backend-only writes, gated reads

Writes use the service-role only - never the client - through a new storage adapter that copies the intake-media adapter shape (protocol + factory + local/supabase backends, AES-256-GCM at rest). The adapter and config (`backend`, `root`, `key`) are selected at the composition root. Reads stream through the backend: the session user reads their own photo via the profile surface, and a doctor reads a patient's photo only through the consent-gated patient-detail route. SQL holds object keys only, never blobs.

### D3 - Upload contract

Uploads validate content-type (JPEG/PNG/WebP only, GIF rejected) and size (≤ 5 MB), then record the stored object key on the profile. Removal deletes the object and clears the key.

## Consequences

- Photos are never publicly addressable; a leaked URL is not a leak because the bucket has no public policies.
- The proven intake-media shape is reused, keeping encryption, backends, and factory wiring consistent across the codebase.
- Keys (not resized blobs) in SQL mean the image-resize pipeline can be added later without touching the profile API contract.
- Every doctor read of a patient photo flows through the consent gate, preserving the standing-grant boundary for visual PHI.
