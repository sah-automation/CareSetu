# CareSetu Phase 0 spike report - cost model & go/no-go

Generated 2026-08-10T09:07:52Z from the recorded run JSONs in `D:/Dev/Projects/CareSetu/phase0/runs` - costs and bar results are read from the recorded runs, never eyeballed or re-scored.

## Go/no-go verdict (mechanical)

- **Verdict:** NO-GO: text-first intake fallback
- **Selected provider:** gemini (gemini-2.5-flash)
- **Rule applied:** gemini (gemini-2.5-flash): transcription floor fails; text-first intake with voice as an upload-for-doctor artifact is the pre-decided fallback

## Per-provider model

| provider (model)          | run                   | clips | WER bar | median/p90 WER | struct F1 | AMB-006 calib | per-intake INR | per-call INR | in/out tokens | in/out tok/call | calls | AI calls/mo | rx-draft INR (est) | monthly INR | headroom |
| ------------------------- | --------------------- | ----: | ------: | -------------: | --------: | ------------: | -------------: | -----------: | ------------: | --------------: | ----: | ----------: | -----------------: | ----------: | -------: |
| gemini (gemini-2.5-flash) | 20260809T144551Z.json | 12/43 |    FAIL |  0.181 / 0.429 |   no data |       no data |         0.0243 |       0.0243 |        528/54 |          528/54 |     1 |         400 |            no data |     no data |  no data |

## Constraint verification (KPI-001 volume: ~200 intakes + ~200 rx-drafts/month, ~600 AI calls at 2 calls/intake)

### gemini (gemini-2.5-flash)

- per-intake ceiling: PASS (0.0243 INR <= 2.00 INR; recorded mean over billed clips)
- rx-draft ceiling: unverified (no structuring-class usage recorded to estimate from)
- AI slice: unverified (rx-draft cost has no recorded basis)
- Headroom: unverified (rx-draft cost has no recorded basis)

## Provider selection

- Selected **gemini (gemini-2.5-flash)** - first recorded provider in shortlist order; its transcription leg fails the floor.

## AMB-006 threshold

- **Threshold:** 0.70 (pinned constant; validated by calibration on the recorded run).
- **Validated:** unverified - no calibration section in the recorded run (never a vacuous pass).

## Caveats

Per-intake costs and tokens are the recorded means over billed clips (both legs where the run recorded them); failed clips are not billed and are excluded. Per-call figures are the per-intake means divided by the run's recorded calls per intake; the AI calls/month count is KPI-001 volume at that call rate (200 intakes + 200 rx-drafts, one call per rx-draft).
The rx-draft call is not measured by the spike corpus; its per-call cost is estimated from the recorded structuring-class call. Where no structuring usage is recorded, the rx-draft ceiling and the AI-slice/headroom checks are reported unverified, never fabricated.
