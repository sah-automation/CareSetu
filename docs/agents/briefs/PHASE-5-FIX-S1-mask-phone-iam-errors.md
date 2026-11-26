# Brief - 275 Phase-5 review fix: mask phones in IAM error envelopes (S1, security)

**Ticket:** #275 · **Parent:** #243 · **Refreshed:** 2026-09-02
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

`SessionIssuanceError` messages embed the full raw E.164 phone number, surfaced verbatim in the HTTP error envelope via `str(exc)`:

- `modules/iam/session_facade.py:133` - `f"no identity for {phone_e164}; register the phone before issuing a session"`
- `modules/iam/session_facade.py:202` - `f"no identity for {phone_e164}; invite the operator before issuing a session"`
- `modules/iam/mfa_facade.py:80` - `f"no identity for {phone_e164}; invite the operator before MFA"`

These flow into `_session_refused` / `_invalid_phone` / `_sms_failed` handlers in `iam/adapters/routes.py` which return `str(exc)` as the envelope `message`. This leaks a personal identifier (PII) - a violation of security-phii-standards (no PII in messages/logs). This is the review gap S1.

Apply phone masking before the phone enters the exception message or envelope, so a full phone number is never surfaced.

Acceptance criteria (from #275):

- [ ] `mask_phone` (or the equivalent) applied to the phone in the `SessionIssuanceError` messages in `session_facade.py` and `mfa_facade.py`.
- [ ] `_session_refused`, `_invalid_phone`, `_sms_failed` handlers in `iam/adapters/routes.py` return a masked phone (or no phone) in the envelope `message`.
- [ ] Tests assert the error envelope `message` contains a masked phone (e.g. `+91...90`), not the full number.
- [ ] `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`, `npm run typecheck` pass.

## Read-list (in order)

1. `apps/backend/modules/iam/adapters/sms.py` - `mask_phone` (440): the IAM-local masking helper (keeps `+<cc>` + last two digits). Prefer reusing this; it already exists in the module. (~0.4K)
2. `apps/backend/modules/notify/adapters/transport.py` - `mask_phone` (425) - the analogous helper, for reference on a consistent mask shape. Decide which masking function to standardize on. (~0.4K)
3. `apps/backend/modules/iam/session_facade.py` - lines 120-146 and 198-215: the `SessionIssuanceError` raise sites with the raw phone; read the surrounding `_lock_identity_by_phone` / status-gate blocks. Apply masking here so the exception never carries a full number. (~0.8K)
4. `apps/backend/modules/iam/mfa_facade.py` - line 80: the third raise site. (~0.4K)
5. `apps/backend/modules/iam/adapters/routes.py` - `_session_refused` (421-427), `_invalid_phone` (411-414), `_sms_failed` (416-419), and `_error_response` (383-405): the envelope builders that surface `str(exc)`. Ensure masking is applied (belt-and-suspenders even if the message is already masked upstream). (~0.8K)
6. `docs/standards/security-phii-standards.md` + `error-handling-observability.md` - the no-PII-in-messages/logs rules that motivate this. (~0.8K)

## Do NOT read

- partner/audit module internals, `docs/archive/`, frontend.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- IAM session/MFA error tests green (grep `SESSION_REFUSED` / `PHONE_INVALID` / `SessionIssuanceError` tests)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- `mask_phone` already exists twice (iam/sms.py:440 and notify/transport.py:425) with an identical shape (`+<cc>...<last2>`). For this ticket, reuse the IAM one (`iam/adapters/sms.py`) - do not introduce a third copy. A separate future dedup could reconcile the two, but is out of scope here.
- Apply masking at BOTH the raise site (so the exception itself is clean) and, defensively, where the message is surfaced, so no future caller of these exceptions can leak a full number. Follow security-phii-standards: the distinguishing cause (identity id) is sufficient server-side.
- The identity id is the safer thing to surface in the envelope message than a phone - consider including `identity_id` instead of the raw phone.
- Parent for all Phase-5 review-fix briefs is #243. Finding drawn from the code-review S1.
