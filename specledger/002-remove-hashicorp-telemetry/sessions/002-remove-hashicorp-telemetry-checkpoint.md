# Session Log: 002-remove-hashicorp-telemetry

## Divergence Review: 2026-06-10 12:01

**Scope**: Full checkpoint over the 6 implementation commits `e5eed19f6..3f39a1044` (artifact reconcile, sherif fix, Phase A SDK upgrade, Phase B HashiCorp removal, Phase C usage analytics + consent, Phase D e2e validation tooling). Working tree clean.

### Divergences

| # | Severity | Type | Category | Artifact | Description |
|---|----------|------|----------|----------|-------------|
| 1 | CRITICAL | oversight | Failing check | FR-013 / SC-005 | `pnpm nx lint @cdktn/cli-core` FAILS on the **new** `src/test/error-reporting.test.ts:40-41` — stale `eslint-disable @typescript-eslint/no-var-requires` directive + forbidden `require("ci-info")` (`no-require-imports`), with `--max-warnings=0`. Introduced by this branch (Phase C). |
| 2 | MEDIUM | oversight | Requirement partially implemented / dead code | spec.md FR-005, research.md Decision 5, contracts C2, data-model.md Entity 1 | The validated `CdktfConfig.sendUsageTelemetry` getter (`cli-core/src/lib/cdktf-config.ts:90-114`) exists but has **zero runtime consumers and zero direct tests** — the actual consent gating reads `cdktf.json` via a new loose raw-JSON reader (`commons/src/telemetry.ts:18 getUsageTelemetryConsent`), the exact pattern FR-005 said to avoid. Consequence: the getter's validation (`Errors.External` on non-boolean) is unreachable; the live path silently coerces a malformed value (e.g. `"yes"`) to `false`. The architectural reason (commons cannot import cli-core; init runs pre-project-validation and must work outside projects, Decision 8) is real but undocumented, and the getter is dead code as shipped. |
| 3 | MEDIUM | oversight | Test-layer drift | quickstart.md Journey 1, research/2026-06-08-v10-e2e-validation.md (L2) | Planned no-egress oracle was an **integration test with `nock.disableNetConnect()`** asserting no runtime connection attempt to HashiCorp. Implemented instead as a static scan (`cdktn-cli/src/test/no-hashicorp-egress.test.ts`: workspace-source grep + built-bundle grep). Defensible (the transport code is deleted entirely; bundle E2E sink shows only-Sentry egress) but quickstart/research were reconciled in e5eed19f6 and still specify nock — either implement L2 or update the artifacts. |
| 4 | MEDIUM | conscious | Missing user-facing doc | spec.md Edge Cases (line 109, "MUST be called out in user-facing migration/release notes") | The revived crash-consent prompt (previously dead code — absent key coerced to `false`) is documented only in the spec, research Decision 8, and the body of commit `daa2c8b72`. No user-facing migration/release note or docs change exists in the branch. release-please builds changelog entries from commit subjects, so the body note will not surface to users automatically. |
| 5 | LOW | conscious | Architecture change | spec.md FR-008, research.md Decision 8 | Runtime prompt gate is inlined in `cli-core/src/lib/error-reporting.ts:90-94` (`stdout.isTTY && !ciInfo.isCI && !process.env.CI && existsSync(cdktf.json)`) instead of reusing `isInteractiveTerminal()` — that helper lives in `cdktn-cli` and cannot be imported by `cli-core`. Semantics are a strict superset (adds `ciInfo.isCI` + the Decision-8 no-project rule). `cdktn init` does reuse the helper (`helper/init.ts:183`). |
| 6 | LOW | conscious | Contract signature drift | contracts C1 | Contract declares `sendTelemetry(...): void`; implemented as `async (...): Promise<void>` (commons/src/telemetry.ts:92), awaited at all 7 call sites — matches the legacy async signature, minimizing churn per FR-004. Contract text not updated. |
| 7 | LOW | conscious | File location drift | plan.md Project Structure | `telemetry.test.ts` planned at `cli-core/src/test/`; lives at `commons/src/telemetry.test.ts`, co-located with the wrapper it tests. Consent-gating tests landed in `cli-core/src/test/error-reporting.test.ts` instead. |
| 8 | LOW | oversight | Dead payload / wasted work | data-model.md Entity 3 | `synth-stack.ts:289-300` still computes `stackMetadata` (JSON.parse of every stack) and `requiredProviders` and passes them to `sendTelemetry`, which silently drops everything except `command`/`language`/`ci`/`totalTime`. Dropping the fields is per FR-002's reduced collection scope, but the call site burns work building payload that is discarded and misleads readers about what is collected. |

### DoD per User Story

| User Story | Title | DoD status | Risk |
|------------|-------|-----------|------|
| US1 | No data to HashiCorp | Transport deleted (`checkpoint.ts` gone); static source + bundle scans pass. **Runtime nock-based egress assertion not implemented** (divergence #3) | LOW — no transport code exists to make the call |
| US2 | Usage analytics via Sentry v10 metrics | Real-client capturing-transport delivery tests pass (`trace_metric` envelope + `flush()===true`); `cli.command.invoked`/`.error`/`cli.synth.duration` per FR-014; hostname-scrub test present; bounded `beforeExit` flush in `cdktn.ts:52-59` | — |
| US3 | Sentry error reporting preserved | v10 init pins `release`/`tracesSampleRate: 0`/`serverName: "cdktn-cli"` (asserted in tests); `getCurrentScope()` migration done; beforeSend usage-only gate tested. **One-time manual SaaS dashboard + release sourcemap symbolication check (Decision 7 / plan Phase D) not evidenced** | MEDIUM — symbolication regression would only surface at release |
| US4 | Checkpoint cleanup | Complete: no `ReportRequest`/`ReportParams`/`post`/`BASE_URL`/`report()`/`checkpoint.test.ts`; only reference to the endpoint is the egress test asserting its absence; `identity.ts` holds the kept utils | — |
| US5 | Consent on upgrade & non-interactive defaults | Per-flag tri-state prompts (upgrade path prompts ONCE for usage only — tested); FR-016/FR-017 precedence tested incl. `CHECKPOINT_DISABLE`, no-project, CI; `cdktn init` asks both flags, `--enable-usage-telemetry` added, 6 templates render the flag (string-boolean coercion handled both readers) | — |

Quickstart coverage: J1→`no-hashicorp-egress.test.ts` (static, see #3); J2/J3/J5→`commons/src/telemetry.test.ts`; J4/J7→`cli-core/src/test/error-reporting.test.ts`; J6→`tools/sentry-sink.mjs` + `tools/validate-sentry-e2e.sh` + gated `sentry-bundle-e2e.test.ts` (skips unless `CDKTN_SENTRY_E2E` set — not exercised in this checkpoint run).

### Issues Encountered & Resolutions

- sherif could not even parse the workspace before this branch (`"private": "true"` in `tools/generate-function-bindings/package.json`) → fixed in `4e1142243`; the 20 issues it now reports (14 errors: cross-package version mismatches, unordered deps) are pre-existing hygiene debt **surfaced**, not introduced, by this branch (verified by running sherif at the pre-fix commit — it crashes there).
- `end2end-tests:lint` fails with 836 prettier errors in `test/edge-provider-bindings/providers/edge/**` (generated bindings, last touched in the rename commit on main) — pre-existing, untouched by this feature.

### Items Requiring Action Before Merge

1. [CRITICAL] Fix `cli-core` lint failure in `src/test/error-reporting.test.ts:40-41` (replace the `require("ci-info")` + stale disable with a typed import or the correct disable directive) — CI lint gate will fail.
2. [MEDIUM] Resolve the `CdktfConfig.sendUsageTelemetry` getter drift: either route a runtime consumer through it / add a getter unit test and document why the gating path must use the loose reader (commons↔cli-core layering, pre-project init), or remove it (YAGNI). As-is it is unvalidated dead code contradicting FR-005's stated rationale.
3. [MEDIUM] Reconcile quickstart J1 / research L2 with the implemented static-scan no-egress test, or add the nock runtime variant.
4. [MEDIUM] Add the revived-crash-prompt callout to user-facing release/migration notes (spec line 109 is a MUST); the commit-body note will not reach the changelog via release-please.
5. [LOW] Trim the dropped `stackMetadata`/`requiredProviders` payload computation in `synth-stack.ts`, and sync contract C1's signature (`Promise<void>`).
6. [PRE-EXISTING, optional] `end2end-tests` prettier debt and the 14 sherif errors — separate chore PRs.

### Tests & Checks

- Status: **FAIL** (lint; unit tests pass)
- Commands run:
  - `TMPDIR=/var/tmp pnpm test` — PASS (9 projects; dist-dependent suites auto-skip; `CDKTN_SENTRY_E2E`-gated bundle suite skips by design)
  - `pnpm lint:workspace` — FAIL: `@cdktn/cli-core` (introduced, see #1), `end2end-tests` (pre-existing)
  - `npx sherif` — 20 issues (pre-existing; tool was unrunnable before `4e1142243`)
  - Integration tests (SC-006) — NOT RUN (require `pnpm package`; out of scope for this checkpoint)
- Failures: see divergence #1 and Issues above.

### Uncommitted Changes

- None (working tree clean at `3f39a1044`).

---
