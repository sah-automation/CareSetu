# ADR-0017: Professional prescription record cards with the issued snapshot

**Status:** accepted
**Date:** 2026-09-23
**Decides:** How a prescription surfaces on the patient My Record page (`/patient/record`) and the home Recent activity preview - the decisions D1-D6 of the spec (parent #512): the data path that carries the issued snapshot to the patient timeline, the Active/Delivered tags, the record-entry payload contract, the card anatomy and single frontend seam, the entry-detail medicine block, and the doc deltas.
**Traceability:** `FEAT-009`, `MOD-006` (Care), `MOD-003` (LHR), `REQ-033`. Delivered by the implementation tickets #513-#517 and closed out here (#518).
**Evidence:** `PrescriptionFacade.approve_prescription` publishing the enriched `prescription.issued` envelope (#513); the health tolerant consumer mirror copying `items`/`attributed_doctor_name` into the record entry payload (#514); `describeEntry` + `EntryCard` shaping both timeline surfaces (#515); `RecentActivityCard` per-type pills (#516); the `/patient/record/[entryId]` medicine block (#517). The event contract is the `prescription.issued` payload note in `internal-modules.md` §4.2.

## Context

A prescription entry on My Record rendered as an anonymous card - a pill icon, the title "Prescription", the folded line `Rx #<id> · <date>`, and an `Issued`/`Delivered` tag. It carried none of the professional detail a patient expects: which medicine, the dose, who prescribed it, and from which chemist it was received. The homepage Recent activity preview rendered the same anonymous shape. The root cause was not the UI alone: the patient record timeline payload carried only `prescription_id` + `status`, so the rich data forced a doctor-scoped read or no read at all. The enrichment moves the issued snapshot into the one write that already reaches the record and lets a single frontend view-model upgrade both surfaces at once.

## Decision

### D1 - Data path

Enrich the `prescription.issued` event published by MOD-006 (Care) so it carries the issued snapshot, and let MOD-003 (Health) copy it into the record entry payload. Chosen over a new MOD-003 -> MOD-006 sync facade seam: one write, an immutable snapshot that matches the immutable `e-prescription`, no new seam to register in the sync matrix, and it mirrors how `report.filed` and `settlement.recorded` payloads already reach the record. Care resolves the doctor's display name at issue time through its module-isolated partner seam (`attributed_doctor_name_resolver`); a missing seam or unresolvable partner resolves to `None`, never an error, and the approval succeeds.

### D2 - Tags

The issued-state badge changes from `Issued` to `Active`; `Delivered` is unchanged. Both use the success tone, matching the PROTO-3.1 binding. This is a dictionary change only (`record.badge.active`) plus a tone mapping.

### D3 - Record-entry payload contract, `chemist_name` reserved

The patient timeline `prescription` entry carries the decision-rich shape:

```jsonc
{
  "prescription_id": 123,
  "status": "issued", // "issued" | "delivered"
  "items": [
    {
      "name": "Amlodipine",
      "dose": "5 mg",
      "frequency": "once daily",
      "duration": "30 tablets"
    }
  ],
  "attributed_doctor_name": "Dr. A. Kumar", // absent -> neutral copy ("issued by your care team")
  "fulfillment_order_id": null, // present only on "delivered" entries
  "chemist_name": null // RESERVED for Phase 10 `order.delivered` (MOD-008)
}
```

`items` and `attributed_doctor_name` are stored **only when the event carried them** - the health consumer copies them through when present and drops them when empty/absent, so a legacy (pre-enrichment) envelope still stores the lean `{prescription_id, status}` shape (honest degradation, REQ-033 / parent #512 US13). The frontend parses both shapes defensively.

`chemist_name` is render-if-present: the frontend shows a chemist line only when the payload carries one, which it cannot today because MOD-008 fulfilment does not exist yet. The contract doc reserves the key so Phase 10's `order.delivered` handler fills it in; no premature MOD-008 work.

### D4 - Card anatomy and the single frontend seam

All five timeline types get the PROTO-3.1 anatomy polish (already largely live: tinted icon chip, colored left edge, inline lab flags). The prescription card receives the full content upgrade - medicine-name title, dose line, attribution line, chemist line when present, "+N more" for multi-item prescriptions - and the home Recent activity rows switch from the status pill to the per-type pill (icon + type label, tinted) reusing the `record.badge.*` dictionary. `describeEntry` is the single shaping point for `/patient/record` cards, `RecentActivityCard`, `HealthSnapshotCard`, and the entry-detail header, so one upgrade reaches every surface. Cards always render only what the payload documents (REQ-033 honesty rule): a pre-enrichment entry with no `items` degrades to today's lean `Rx #<id> · date` form rather than empty fields.

### D5 - Entry-detail medicine block

`/patient/record/[entryId]` for a prescription renders a medicine-item block (one line per item: name · dose · frequency · duration), the prescribing doctor, and the Rx reference, alongside the existing header, source card, and egress trail. The same honesty rule applies: no `items` means the block is skipped, never placeholder rows.

### D6 - Docs

This ADR records D1-D6; the async event registry (`internal-modules.md` §4.2) gains a payload note on the `prescription.issued` row in the style of the existing `intake.captured` note documenting `items` / `attributed_doctor_name` and the reserved `chemist_name`; and PROTO-3.1 is finalized in `prototype/PLAN.md` with its three open review questions resolved against the live implementation.

## Consequences

- The patient timeline and home preview stay honest and immutable: the record entry is a self-contained snapshot of what was issued and by whom, with no extra reads.
- Old pre-enrichment entries degrade gracefully to the lean form; nothing renders as a lie (REQ-033).
- No schema or migration: the record entry `payload` is untyped JSONB and the event payload growth is purely additive.
- Phase 10 (`order.delivered`, MOD-008) fills a key that is already reserved and render-if-present - no contract churn when fulfilment lands.
