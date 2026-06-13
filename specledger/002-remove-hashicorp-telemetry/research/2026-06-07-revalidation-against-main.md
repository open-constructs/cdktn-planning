# Research: Re-validation of the HashiCorp→Sentry plan against current main

**Date**: 2026-06-07
**Context**: The `002-remove-hashicorp-telemetry` branch was stale (~118 commits behind `main`) and was rebased onto current `main`. The original spec + research (all dated 2026-03-20) were pure planning with no code changes, so every code claim needed re-validation against the drifted codebase before resuming. A separately-merged ESM/import-extension feature was also checked for impact.
**Method**: Three parallel read-only Explore agents (commons telemetry/error code; call sites + consent flow; Sentry SDK + config + CI), plus a fourth agent on the ESM feature. Sentry metrics API additionally confirmed at runtime against the freshly-installed `node_modules`.

## Question

Does the 2026-03-20 plan still hold against current `main`, and does the merged ESM/import-extension feature impact it?

## Headline

**The plan holds.** The highest-risk claim — that `@sentry/node` still exposes the metrics API the entire approach depends on — survived the drift. Three concrete refinements are needed (below); none invalidate any user story or success criterion.

## Findings

### Finding 1: Sentry SDK still 7.120.4 — metrics API confirmed at runtime (CONFIRMED)

- `@sentry/node` is pinned at `7.120.4` in all three packages (`commons`, `cli-core`, `cdktn-cli`), matching `yarn.lock` and the freshly-installed `node_modules` (`@sentry/node` and `@sentry/core` both `7.120.4`). No v8 jump — the v8 removal of the client-side metrics API has NOT happened here.
- Runtime probe of the installed module (`node -e "require('@sentry/node')"`) returned `Sentry.metrics` keys: `increment, distribution, set, gauge, MetricsAggregator, metricsAggregatorIntegration`. All callable. This upgrades the original "verified via type defs" claim to empirically confirmed against installed code.
- **API-shape drift**: the metrics aggregator integration is `Sentry.metrics.metricsAggregatorIntegration()` — a member of the `metrics` object — NOT a top-level `Sentry.metricsAggregatorIntegration()`. Runtime confirmed: top-level is `undefined`, `metrics.metricsAggregatorIntegration` is a `function`. The whole metrics API carries an `@experimental` JSDoc tag.

### Finding 2: commons telemetry/error code intact (CONFIRMED, minor drift)

- `packages/@cdktn/commons/src/checkpoint.ts` exists with both responsibilities: HashiCorp telemetry (`sendTelemetry` @78, `ReportRequest` @152, `ReportParams` @28, `post` @43) and ID utilities to keep (`getUserId` @139, `getProjectId` @135, `getId` @98, `homeDir` @19).
- **`BASE_URL` is split**: the constant (`checkpoint.ts:13`) holds only `https://checkpoint-api.hashicorp.com/v1/`; the `telemetry/<product>` suffix is appended at the call site (`checkpoint.ts:196`, product = `"cdktn"`). Final URL unchanged, but a literal search for the full URL as a constant will miss.
- **Extra runtime gate**: `ReportRequest` early-returns on `process.env.CHECKPOINT_DISABLE` (`checkpoint.ts:155`) — an additional gate the original research attributed only to `environment.ts`. `environment.ts:14` still exports the `CHECKPOINT_DISABLE` constant.
- `errors.ts` still has the fire-and-forget `report()` (@8, called un-awaited from `reportPrefixedError` @31) → `ReportRequest`. `Errors.Internal/External/Usage` + Sentry `setScope` (`configureScope`/`setTransactionName`) preserved. Call-site counts essentially exact: 45 Usage / 20 Internal / 16 External = 81 (plan said ~80).
- `index.ts` re-exports checkpoint via wildcard `export * from "./checkpoint"` (@4).
- Deps present: `uuid@9.0.1`, `ci-info@3.9.0`, `@sentry/node@7.120.4`.

### Finding 3: call sites + consent flow intact (CONFIRMED, line drift)

- Still exactly 7 `sendTelemetry` call sites across 5 files; commands/payloads unchanged. Three line numbers drifted: `cdktf-project.ts` 648→647, `init.ts` 285→287, `get.tsx` 58→63. (`watch.ts:184`, `synth-stack.ts:279/294`, `handlers.ts:169` unchanged.)
- `error-reporting.ts`: `Sentry.init` with `beforeSend` + session tracking (@84), `configureScope` setting `setUser({id: getUserId()})` + `setTag("projectId", getProjectId())` (@120-125), consent gate `shouldReportCrash` reading `sendCrashReports` from `cdktf.json` (@23-32) + CI detection + `SENTRY_DSN`. `initializErrorReporting` (note: misspelled) called from 9 handlers in `handlers.ts`. `captureException` (@133) confirmed dead code — not re-exported, zero importers.
- `checkpoint.test.ts` is HashiCorp-only (`nock` against `checkpoint-api.hashicorp.com`, `CHECKPOINT_DISABLE`) — safe to delete.
- Integration disable mechanism confirmed: `--enable-crash-reporting=false` (`test-helper.ts:226`, flag defined `init.ts:48`).

### Finding 4: config consent flag pattern — two patterns exist (CONFIRMED + IMPORTANT)

- `sendCrashReports` is NOT typed on `Config`/`ConfigBase`. It is accessed **loosely** off raw parsed JSON in `error-reporting.ts:23-25` (read) and `:41` (write). The typed `Config`/`ConfigBase` (`config.ts:272-286`) does not contain it.
- `sendUsageTelemetry` does not exist anywhere yet — the plan's addition is still net-new.
- Build-time `SENTRY_DSN` injection confirmed: esbuild `define` in `packages/cdktn-cli/build.ts:96-97`.

### Finding 5: ESM / import-extension feature — landed, no conflict, sets the config precedent (CONFIRMED)

- The "ESM support" feature landed as **configurable import extensions** (PR #151, `324a264c1`; follow-up `3c2f1d870`). It is live, wired, and test-covered: the generator appends a configurable suffix to emitted relative import/export specifiers (`provider-generator.ts:106,265,309`; `struct-emitter.ts:177,202`), defaulting to `""` (CommonJS).
- **It is surfaced via `cdktf.json` using the TYPED pattern**: `languageOptions.importExtension` is a strongly-typed, language-discriminated field (`config.ts:33-40,286-308`), read through a validated getter `CdktfConfig.languageOptions` (`cdktf-config.ts:77-88`), threaded to the generator via `get.ts:104` → `constructs-maker.ts:286`.
- **No file overlap** with the telemetry plan: ESM touched `config.ts` (additively), `cdktf-config.ts`, `get.ts`, and the provider-generator — none of `checkpoint.ts`, `errors.ts`, `environment.ts`, `error-reporting.ts`, `index.ts`, or any `sendTelemetry` call site. `ConfigBase` (`config.ts:272-279`) is untouched and clean for a new field.

### Finding 6: CI `CHECKPOINT_DISABLE` count drifted 14 → 13 (DRIFTED)

- Current: 13 occurrences across 6 files — `build.yml` (1), `examples.yml` (2), `integration.yml` (3), `provider-integration.yml` (3), `release.yml` (2), `registry-docs-pr-based.yml` (2).
- Gone vs. the original list: `pr-depcheck.yml` and `release_next.yml` no longer exist; `unit.yml` no longer carries the var. Only affects the out-of-scope cleanup note (OS-001).

## Decisions

- **D1**: Plan is viable on the currently-pinned SDK. Proceed; no SDK upgrade.
- **D2**: In `Sentry.init()`, reference the integration as `Sentry.metrics.metricsAggregatorIntegration()` (member of `metrics`), not a top-level export. Note the `@experimental` status as a low risk.
- **D3 (revises 2026-03-20 advice)**: Add `sendUsageTelemetry` using the **typed** config pattern set by `importExtension` — a field on `ConfigBase` (`config.ts:272-279`, language-agnostic, NOT inside the language-discriminated union) plus a validated `CdktfConfig` getter — rather than copying the legacy loose raw-JSON access used by `sendCrashReports`. `importExtension`/`languageOptions` is the precedent to follow.
- **D4**: Treat the original `file:line` references as approximate. Re-pin during implementation: 7 call sites (3 drifted), split `BASE_URL`, the extra `CHECKPOINT_DISABLE` gate in `ReportRequest`, and the 13-occurrence/6-file CI reality.

## Recommendations

1. Patch spec FR-003 / assumptions wording to `Sentry.metrics.metricsAggregatorIntegration()`.
2. Patch spec FR-005 to specify the typed `ConfigBase` + `CdktfConfig` getter approach (per `importExtension`).
3. Patch spec CI count `14 → 13` (edge cases, OS-001, assumptions).
4. Proceed to `/specledger.plan` from the validated spec.

## References

- Prior research: `research/2026-03-20-checkpoint-usage-analysis.md`, `research/2026-03-20-sentry-usage-and-checkpoint-migration.md`, `research/2026-03-20-testing-strategy-and-sentry-sdk-validation.md`
- Sentry metrics: `node_modules/@sentry/core/types/metrics/exports.d.ts`
- ESM feature: PR #151 (`324a264c1`), `packages/@cdktn/provider-generator/src/get/generator/provider-generator.ts`, `packages/@cdktn/commons/src/config.ts:33-40,286-308`, `packages/@cdktn/cli-core/src/lib/cdktf-config.ts:77-88`
- Issue: https://github.com/open-constructs/cdk-terrain/issues/48
