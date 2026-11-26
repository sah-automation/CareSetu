# ADR-0009: Partner status notifications - WhatsApp-first with SMS fallback

**Status:** accepted
**Date:** 2026-08-31
**Traceability:** `FEAT-014`, `FEAT-015`, `MOD-010`, `MOD-002`, `EXT-003`, `EXT-001`.

## Context

Partners need to be notified of terminal status changes: `[Active]` (they can start receiving patients) and `[Rejected]` (with the specific failure reason, per `FEAT-014`). `MOD-010` already has `EXT-003` (WhatsApp templates) and a signed delivery webhook wired for `FEAT-019`, and `EXT-001` (SMS) is wired for OTP. Email is not an option - the partner model has no email field and the system is phone-OTP-based. WhatsApp alone is insufficient because a material fraction of peri-urban Daltonganj partners may not have WhatsApp linked to their phone number, so a single WhatsApp channel can silently miss partners.

## Decision

**Terminal partner status notifications use a WhatsApp-first delivery chain with an SMS fallback driven by the delivery webhook.**

1. **Primary:** send via `EXT-003` WhatsApp template to the partner's phone.
2. **Fallback trigger:** when `EXT-003`'s signed delivery webhook reports failure/undeliverable (`notification.failed`), retry via `EXT-001` SMS. The fallback is driven by the delivery-status event, not by guessing.
3. **Guarantee rationale:** SMS reaches a phone without any WhatsApp dependency, so this chain guarantees delivery of terminal notifications while using the cheaper WhatsApp channel when it works.
4. **Non-terminal updates** (`Under Verification`, re-submission confirmations) are in-app only - no WhatsApp/SMS cost.

## Consequences

- `EXT-001` SMS is now shared beyond OTP (it already exists in `MOD-001`); `MOD-010` consumes `EXT-001` for partner notifications through the same backend. This is a seam to keep in mind - SMS capability is no longer OTP-exclusive.
- `MOD-010` must support two delivery backends and a webhook-driven fallback for terminal partner notifications.
- Supports the `FEAT-014` acceptance requirement that a rejected partner is notified of the specific failure, reliably.
