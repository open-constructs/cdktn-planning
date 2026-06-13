# Research: Build & release Sentry config injection (the known-working error path)

**Date**: 2026-06-07
**Context**: The HashiCorp→Sentry telemetry migration routes new usage metrics through the project's existing Sentry. Before planning, we need to understand exactly how Sentry is configured/injected by the build and release pipelines — because that path is already proven for error reporting, and usage metrics will ride the same `Sentry.init()` and the same baked-in DSN. The goal is to confirm what already works and what (if anything) the metrics migration must add at the CI/build layer.
**Time-box**: 30 minutes

## Question

How do `.github/workflows` and the build scripts inject Sentry configuration into the shipped CLI, and what does the metrics migration need to change (if anything) at the build/release layer?

## Findings

### Finding 1: The DSN is baked into the bundle at build time, not read from the user's env (CONFIDENCE: high)

The Sentry DSN is a **build-time secret inlined into the bundle**, not something the end user supplies at runtime.

- esbuild `define` replaces the token with a string literal at build time:
  `packages/cdktn-cli/build.ts:96-97` → `"process.env.SENTRY_DSN": JSON.stringify(process.env.SENTRY_DSN || "")`
- The runtime reads that now-inlined value: `error-reporting.ts:77` (`if (!process.env.SENTRY_DSN) ... disabled`) and `:86` (`dsn: process.env.SENTRY_DSN`).
- CI supplies the secret as an env var to the `yarn build && yarn package` step:
  - `build.yml:68` → `SENTRY_DSN: ${{ secrets.SENTRY_DSN }}`
  - `release.yml:72` (stable) and `release.yml:157` (next) → same
  - `integration.yml:82` → same
- Consequence: **local/dev/fork builds without the secret ship an empty DSN, so Sentry is silently disabled** (`error-reporting.ts:77-79`). Only official CI builds emit anything. This is the existing privacy/behaviour contract and metrics inherit it for free.

### Finding 2: The runtime `Sentry.init()` is the single wiring point — and currently has NO `integrations` array (CONFIDENCE: high)

`packages/@cdktn/cli-core/src/lib/error-reporting.ts:84-118` is the only `Sentry.init()` in the codebase. Current config:

```ts
Sentry.init({
  autoSessionTracking: true,
  dsn: process.env.SENTRY_DSN,
  release: `cdktn-cli-${DISPLAY_VERSION}`,
  async beforeSend(event, hint) { /* drops "Usage Error" messages */ },
});
```

- There is **no `integrations: [...]`** array today (grep confirmed). So enabling metrics is a clean, additive one-liner here:
  `integrations: [Sentry.metrics.metricsAggregatorIntegration()]` (note the `.metrics.` member form per the 2026-06-07 re-validation note).
- Gated by `initializErrorReporting()` (`:56`), which is consent-gated (`shouldReportCrash()` reading `sendCrashReports`), CI-aware (`:60,65-67`), and DSN-gated (`:77`). Usage metrics under the same init automatically inherit all three gates.

### Finding 3: The release name `cdktn-cli-<version>` is the contract binding runtime → release pipeline (CONFIDENCE: high)

The runtime tags every event with `release: cdktn-cli-${DISPLAY_VERSION}` (`error-reporting.ts:87`). The release workflow creates/uploads/finalizes a Sentry **release of the exact same name**:

- `SENTRY_ORG: cdktn`, `SENTRY_PROJECT: cdktn` (`release.yml:10-11`).
- Create release: `sentry-cli releases new cdktn-cli-<version>` (`release.yml:61`, and `:148` for the `next` channel).
- Upload sourcemaps + associate commits to that release: `release.yml:76-77` (`upload-sourcemaps ./packages/cdktn-cli/bundle`, `set-commits --auto`), `:161-162` for `next`.
- Finalize: dedicated jobs `release_sentry` / `release_sentry_next` (`release.yml:361,418`) run `sentry-cli releases finalize cdktn-cli-<version>` (`:395,451`).
- Auth: `SENTRY_AUTH_TOKEN: ${{ secrets.SENTRY_TOKEN }}` (note the secret is named **`SENTRY_TOKEN`**, mapped onto the `SENTRY_AUTH_TOKEN` env the CLI expects).
- Release skip logic: `sentry-cli releases list | grep 'cdktn-cli-<version> '` decides released/unreleased (`release.yml:54,141`).

Implication: usage **metrics will be auto-associated with the same `cdktn-cli-<version>` release** (and with sessions via `autoSessionTracking`). This directly serves the spec's "version adoption tracking" goal at **zero additional CI cost** — sourcemaps/commit-association are error-specific and irrelevant to metrics, but the release object metrics attach to is already created and finalized.

### Finding 4: ⚠️ Flush-on-exit only happens on the ERROR path — the happy path does NOT flush (CONFIDENCE: high)

This is the most important finding for the metrics migration, and it is **not** addressed in the original (2026-03-20) research.

- `Sentry.close(4000)` exists at exactly one place: `packages/cdktn-cli/src/bin/cdktn.ts:184` — inside the yargs **`.fail()` error handler**, immediately before `process.exit(1)` (`:185`). There is no `process.on("exit")`/`beforeExit` flush, and no `Sentry.close()`/`flush()` on the success path (grep found only this one occurrence).
- Sentry's metrics aggregator **buckets metrics into ~10-second intervals and flushes asynchronously**. The CLI is short-lived; most commands succeed and exit in well under 10s.
- Therefore: **`Sentry.metrics.*` calls emitted during a successful command are likely to be dropped** when the process exits before the aggregator flushes. Crash/error reporting works precisely because the error path calls `Sentry.close(4000)` (which flushes); the happy path has no equivalent.
- This is a genuine gap the migration must close. Options:
  1. Add `await Sentry.flush(timeout)` (or `Sentry.close()`) on the normal-exit path — e.g. a shared teardown after command handlers, or a `process.on("beforeExit")` hook. Must be bounded (the error path uses a 4000ms cap) so telemetry never hangs the CLI.
  2. Flush right after emitting the metric in short-lived commands.
  3. Prefer span-based emission tied to the command lifecycle if it integrates with the existing flush, rather than fire-and-forget counter increments.
- Whichever option, it needs a test asserting metrics are actually delivered on a successful run (mock `@sentry/node`, assert flush/close is awaited before exit). The original test strategy (mock `metrics.increment`, assert it was called) would pass even while real metrics are silently dropped — so the test plan needs this extra assertion.

### Finding 5: Integration tests build WITH a DSN but disable reporting at runtime (CONFIDENCE: high)

- `integration.yml:82` bakes `SENTRY_DSN` into the integration build, so the bundle under test has a live DSN.
- But integration runs pass `--enable-crash-reporting=false` (`test-helper.ts:226`), so `shouldReportCrash()` is false and `Sentry.init()` is skipped — no events/metrics emitted.
- Implication: integration tests will **not** exercise the metrics path end-to-end by default. The success-path flush (Finding 4) must be validated by a unit test or a dedicated opt-in integration case, not the standard suite. `CHECKPOINT_DISABLE: "1"` set in these workflows is now redundant once HashiCorp telemetry is removed (already out-of-scope per OS-001).

## Decisions

- **D1**: No CI/secret/workflow changes are required to ship usage metrics. `SENTRY_DSN` is already injected at every build that matters (`build.yml`, `release.yml` stable+next, `integration.yml`), and the `cdktn-cli-<version>` release object that metrics attach to is already created/finalized by the release pipeline. The migration is **code-only**.
- **D2**: Enable metrics at the single existing init site by adding `integrations: [Sentry.metrics.metricsAggregatorIntegration()]` to `error-reporting.ts:84`. No second init, no new config plumbing.
- **D3 (new risk, must be in the plan)**: Add a bounded flush on the **success** exit path. Without it, happy-path usage metrics are dropped because `Sentry.close(4000)` only runs in the error handler (`cdktn.ts:184`). Cap the flush timeout so telemetry can never hang the CLI.
- **D4**: Strengthen the test strategy — assert metrics are *flushed/delivered* before exit, not merely that `metrics.increment` was called. Validate success-path delivery in a unit test (standard integration suite disables reporting).

## Recommendations

1. In the plan's "enable metrics" task, target `error-reporting.ts:84` for the `integrations` array; reference Finding 2.
2. Add an explicit plan task: **bounded flush on normal exit** (`Sentry.flush(timeout)` in shared teardown or `beforeExit`), with the 4000ms error-path cap as precedent. Reference Finding 4.
3. Add a test task asserting the success-path flush awaits before `process.exit` (mock `@sentry/node`).
4. Leave all workflows unchanged; note in the spec that no CI changes are needed (reinforces OS-001 / OS scope). `CHECKPOINT_DISABLE` in CI becomes inert post-removal — still out of scope to delete.
5. Optional: confirm with maintainers that the `cdktn`/`cdktn` Sentry org/project has the metrics/EAP feature enabled for the DSN in use (org-side, not code) before relying on dashboards.

## References

- esbuild DSN define: `packages/cdktn-cli/build.ts:96-97`
- Runtime init: `packages/@cdktn/cli-core/src/lib/error-reporting.ts:56-130` (init `:84`, release tag `:87`, DSN gate `:77`)
- Success/error exit + flush: `packages/cdktn-cli/src/bin/cdktn.ts:184` (`Sentry.close(4000)`, error path only)
- Build CI: `.github/workflows/build.yml:62-69`
- Release CI: `.github/workflows/release.yml:8-11,54,61,72-77,148,157-162,361-397,418-453`
- Integration CI: `.github/workflows/integration.yml:78-82`; integration disable flag `packages/@cdktn/cli-core/test/test-helper.ts:226`
- Related: `research/2026-06-07-revalidation-against-main.md` (metrics API shape, typed config pattern), `spec.md` FR-003/FR-007/OS-001
