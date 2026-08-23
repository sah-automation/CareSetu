# Brief - REFAC-2 Create domain/shared.py and OtpSender port

**Ticket:** #167 · **Parent:** ADR-0006 · **Refreshed:** 2026-08-19
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Create `domain/shared.py` with shared internal helpers used by both IdentityFacade and OtpFacade. Define the `OtpSender` port that decouples sub-facades from the SMS adapter. Wire the `SmsDeliveryQueue` behind the port in the coordinator.

Acceptance criteria:

- `modules/iam/domain/shared.py` exists with: `IdentityGuardState`, `_lock_identity_row`, `_invalidate_pending_challenges`, `_issue_challenge`
- `OtpSender` port type defined (Callable[[str, str], Awaitable[None]])
- `IamFacade.__init__` creates `SmsDeliveryQueue` and exposes `OtpSender` callable
- `IamFacade.emit_access_denied` still works (stays on coordinator)
- All unit tests pass
- Typecheck clean
- Boundary checker passes

## Read-list (in order)

1. `docs/adr/0006-iam-facade-split.md` - the ADR governing this refactoring (~1.5K tokens)
2. `modules/iam/facade.py` lines 181-230 - `IdentityGuardState` dataclass and `_lock_identity_row` (~0.5K tokens)
3. `modules/iam/facade.py` lines 911-970 - `_invalidate_pending_challenges` and `_issue_challenge` (~0.6K tokens)
4. `modules/iam/facade.py` lines 235-252 - `IamFacade.__init__` constructor (~0.3K tokens)
5. `modules/iam/facade.py` lines 683-713 - `_emit_delivery_failed` callback (stays on coordinator) (~0.3K tokens)
6. `modules/iam/adapters/sms.py` - `SmsAdapter` protocol, `SmsDeliveryQueue`, `SmsSendRequest`, `SmsTemplateParams` (~1.2K tokens)
7. `modules/iam/schema/models.py` - `iam_identities`, `iam_otp_challenges` tables (~0.5K tokens)
8. `modules/iam/outbox.py` - `IAM_OUTBOX_TABLE` constant (~0.1K tokens)
9. `modules/iam/domain/events.py` - `otp_failed_envelope` (used by `_emit_delivery_failed`) (~0.3K tokens)

Total: ~5.3K tokens

## Do NOT read

- `modules/iam/domain/jwt.py`, `domain/refresh.py` - not touched
- `modules/iam/domain/otp.py`, `domain/lockout.py`, `domain/verify.py`, `domain/resend.py` - not touched
- `app/main.py` - not touched
- Any test files (run them for verification only)
- Other modules, frontend

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (654 passed)
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (all 654 pass)
- `npm run typecheck` (clean)
- `npm run lint` (boundary checker passes)
- `wc -l apps/backend/modules/iam/domain/shared.py` (new file exists)

## Handoff notes

- REFAC-1 must be complete first. After REFAC-1, `SessionFacade` exists in `session_facade.py` and the coordinator delegates to it.
- `IdentityGuardState` and `_lock_identity_row` are currently module-level in `facade.py`. Move them to `domain/shared.py`. Update all imports in `facade.py` to use the new location.
- `_invalidate_pending_challenges` and `_issue_challenge` are currently methods on `IamFacade`. Move them to module-level functions in `domain/shared.py` that take `connection` and other params explicitly (they are already static-like - they don't use `self` except for `self._engine` which is passed as `connection`).
- The `OtpSender` port is `Callable[[str, str], Awaitable[None]]` - takes `(phone_e164, otp)` and returns nothing. The coordinator wires `self.delivery_queue.enqueue` behind this port. The `SmsDeliveryQueue` and `SmsSendRequest`/`SmsTemplateParams` stay as imports in `facade.py` - they are coordinator-internal.
- `_emit_delivery_failed` stays on the coordinator as a method. It writes to the outbox, which the coordinator owns.
- After this ticket, `facade.py` still contains all the identity and OTP logic. Only the shared helpers and the port are extracted. The actual sub-facade extraction happens in REFAC-3 and REFAC-4.
