# Phase 7 - Post-Verification Fixes Plan

**Status:** ready for `/to-tickets`
**Source:** Full Phase 7 verification against plans, prototypes, tests, configs, and live runtime.
**Upstream targets:** `docs/roadmap/implementation-roadmap.md` 2.7, `docs/architecture/internal-modules.md` 3.5 (MOD-005), `docs/prd/project-prd.md` 4.3 (FEAT-006/007), `prototype/PLAN.md` PROTO-PHASE-7/8, `docs/standards/coding-standards.md` 9 (config).

## Scope

Seven fix findings from the Phase 7 verification. Six are code/doc fixes; one is prototype bookkeeping.

**Verified green (no action needed):**

- Backend mypy: 0 errors (211 source files)
- Backend unit tests: 1619 passed, 3 failed (all pre-existing Phase 2 issues, not Phase 7)
- Frontend unit tests: all Phase 7 test suites pass (6 files)
- Security scan: gitleaks 0 leaks, bandit clean, pip-audit 0 vulnerabilities
- Migration check: single head, no cross-schema FKs
- Backend health: `{"status":"ok"}` on port 8000
- Frontend: HTTP 200 on port 3000
- AI pipeline: mock provider returns correct StructuredFields, confidence threshold 0.70 enforced, consent gate + budget meter active
- All 8 intake events registered in bus/events.py
- Module isolation: no cross-schema imports or FKs

### Fix findings

1. **TypeScript error** - `StructuredFields` passed to `Record<string, unknown>` parameter (`pre-summary/page.tsx:245`)
2. **TypeScript error** - string index on typed `StructuredFields` interface (`pre-summary/page.tsx:254`)
3. **TypeScript error** - test fixture `{}` missing required `StructuredFields` props (`pre-summary/page.test.tsx:364`)
4. **TypeScript error** - test fixture missing `symptoms` and `duration` fields (`status/page.test.tsx:100`)
5. **Documentation gap** - `.env.example` missing AI/intake environment variables
6. **Prototype bookkeeping** - `prototype/PLAN.md` Phase 7 screens should be marked `finalized`

---

## Fix 1 - Cast `structured_fields` to `Record<string, unknown>` in `orderedFieldKeys` call

**File:** `apps/frontend/src/app/(patient)/patient/intake/[intakeId]/pre-summary/page.tsx:245`

The `orderedFieldKeys` helper accepts `Record<string, unknown>` but `summary.structured_fields` is typed as `StructuredFields` (a strict interface with `chief_complaints`, `symptoms`, `duration`). TypeScript correctly flags the mismatch because `StructuredFields` has no index signature.

**Change:**

```typescript
// Before (line 245):
() => (summary ? orderedFieldKeys(summary.structured_fields ?? {}) : []),

// After:
() => (summary ? orderedFieldKeys((summary.structured_fields ?? {}) as Record<string, unknown>) : []),
```

The cast is safe because `orderedFieldKeys` only calls `Object.keys()` and `key in fields` - both accept any object. The alternative (changing the `StructuredFields` type to include an index signature) would weaken type safety elsewhere.

---

## Fix 2 - Cast `structured_fields` at field value access site

**File:** `apps/frontend/src/app/(patient)/patient/intake/[intakeId]/pre-summary/page.tsx:254`

Same root cause as Fix 1. The `displayValueFor` callback indexes into `structured_fields` with a string key, which TypeScript rejects on a typed interface.

**Change:**

```typescript
// Before (lines 250-256):
const displayValueFor = useCallback(
  (fieldKey: string): string => {
    if (!summary) return "";
    const merged = corrections[fieldKey] ?? summary.structured_fields[fieldKey];
    return formatFieldValue(merged);
  },
  [summary, corrections],
);

// After:
const displayValueFor = useCallback(
  (fieldKey: string): string => {
    if (!summary) return "";
    const fields = summary.structured_fields as Record<string, unknown>;
    const merged = corrections[fieldKey] ?? fields[fieldKey];
    return formatFieldValue(merged);
  },
  [summary, corrections],
);
```

---

## Fix 3 - Complete `structured_fields` fixture in pre-summary test

**File:** `apps/frontend/src/app/(patient)/patient/intake/[intakeId]/pre-summary/page.test.tsx:364`

The test passes `{ structured_fields: {} }` which does not satisfy the `StructuredFields` interface. The test intends to cover the empty-fields state, but TypeScript requires the full shape.

**Change:**

```typescript
// Before (line 364):
await renderLoaded({ structured_fields: {} });

// After:
await renderLoaded({
  structured_fields: { chief_complaints: [], symptoms: [], duration: null },
});
```

The test asserts `screen.getByTestId("fields-empty")` which fires when `fieldKeys.length === 0` - this remains true with empty arrays and null duration.

---

## Fix 4 - Complete `structured_fields` fixture in status test

**File:** `apps/frontend/src/app/(patient)/patient/intake/[intakeId]/status/page.test.tsx:100`

The `preSummary()` factory passes `{ chief_complaints: ["fever"] }` as `structured_fields`, missing `symptoms` and `duration`.

**Change:**

```typescript
// Before (line 100):
structured_fields: { chief_complaints: ["fever"] },

// After:
structured_fields: { chief_complaints: ["fever"], symptoms: [], duration: null },
```

---

## Fix 5 - Document AI/intake env vars in `.env.example`

**File:** `.env.example`

The `AI_*` and `INTAKE_*` environment variables are configured in `app/config.py` (lines 85-201) but not documented in `.env.example`. New developers cannot discover these without reading config source. Add after the Langfuse block (line 50) and before the frontend block (line 52):

```bash
# EXT-002 LLM/AI gateway (PHASE-7 T05, #348): provider selection with a
# fail-closed default (mock). AI_PROVIDER=provider with a real AI_API_KEY is
# staging/production only - Settings refuses it in dev/test unless DEMO_MODE
# forces the mock. AI_TIMEOUT_SECONDS is bounded to (0, 30].
AI_PROVIDER=mock
#AI_API_KEY=
#AI_BASE_URL=
#AI_TIMEOUT_SECONDS=30
#AI_MAX_RETRIES=3
#AI_CIRCUIT_BREAKER_THRESHOLD=5
#AI_CIRCUIT_BREAKER_COOLDOWN_SECONDS=30
# NFR-001: monthly AI spend cap in paise (200000 = Rs 2,000/month).
#AI_MONTHLY_BUDGET_PAISE=200000
# Intake media store (PHASE-7 T08, #373): encrypted local filesystem under
# the intake/ prefix. INTAKE_MEDIA_KEY is a base64 32-byte AES-256 key;
# empty derives an ephemeral dev key (never committed).
#INTAKE_MEDIA_ROOT=var/intake-media
#INTAKE_MEDIA_KEY=
```

---

## Fix 6 - Mark Phase 7 prototype screens as finalized

**File:** `prototype/PLAN.md`

The Phase 7 implementation was built against the prototype views and verified to match (see compliance report in the verification session). The PROTO-PHASE-7/8 status is still `building` (line 17). Update:

```markdown
// Before (line 17):
| 7 | PHASE-7 (FEAT-006, FEAT-007) | §5.4 | Intake flow + AI pre-summary review + low-confidence variant | building |

// After:
| 7 | PHASE-7 (FEAT-006, FEAT-007) | §5.4 | Intake flow + AI pre-summary review + low-confidence variant | finalized |
```

Also update the per-phase detail section (line 177):

```markdown
// Before (line 177):
Status: `building`

// After:
Status: `finalized` (built and reviewed. Review outcomes: (1) intake-start.html mode chooser matches implementation 1:1; (2) intake-voice.html mic target, state machine, poor-audio variant, upload retry all match; (3) intake-text.html textarea, voice-attach, char cap all match; (4) pre-summary-review.html honesty banner, confidence indicator, edit/save flow match - field groups simplified from 3-group prototype to actual StructuredFields shape (correct per backend design); (5) pre-summary-low-confidence.html amber framing, forced-review notice, low-conf tags all match. My intakes mini-list from prototype deferred to the separate status page.)
```

---

## Execution order

1. Fixes 1 + 2 (same file, same root cause) - unblocks `tsc --noEmit`
2. Fixes 3 + 4 (test fixtures) - unblocks full typecheck
3. Fix 5 (`.env.example`) - documentation
4. Fix 6 (prototype `PLAN.md`) - bookkeeping

## Verification

After all fixes:

- `npm run typecheck` should pass with 0 errors (both backend mypy and frontend tsc)
- `npm run test:unit:frontend` should pass (all Phase 7 frontend tests green)
- `npm run lint` should pass (pre-commit hooks green)
- `npm run migration-check` should remain green (no schema changes)
