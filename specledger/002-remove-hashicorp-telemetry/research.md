# Phase 0 Research: Replace HashiCorp Telemetry with Sentry Analytics

**Feature**: `002-remove-hashicorp-telemetry` | **Date**: 2026-06-08

This consolidates the spike research that informs the plan. Detailed spikes live in `research/`; this file records the decisions that resolve every NEEDS CLARIFICATION.

## Prior Work

- **001-cdktn-package-rename** (`SL-6b54af` update Sentry release tag; `SL-3d9d60` add migration telemetry events): Sentry error reporting was preserved through the rename; the `release: cdktn-cli-<version>` tag and DSN bake-in already exist. Migration telemetry events should use the new analytics path delivered here.
- **GitHub Issue #48**: originating issue — cdktn-cli telemetry posts to `checkpoint-api.hashicorp.com`.
- Spikes: `research/2026-03-20-*` (original checkpoint/Sentry/testing analysis), `research/2026-06-07-revalidation-against-main.md` (code re-validation post-rebase), `research/2026-06-07-build-release-sentry-injection.md` (build/release DSN injection + flush-on-exit risk), `research/2026-06-08-sentry-metrics-transport-viability.md` (transport decision + v10 migration scope).

## Key Decisions

### Decision 1: Analytics transport = upgrade `@sentry/node` to v10 + new Logs/Metrics API
- **Decision**: Bump `@sentry/node` `7.120.4 → ^10.56` across `commons`, `cli-core`, `cdktn-cli`, and emit usage analytics via the new metrics API (`Sentry.metrics.count(...)`). (`enableLogs` is NOT enabled — originally assumed required, the 2026-06-10 spike measured that metrics deliver without it; see Decision 9.)
- **Rationale**: The legacy 7.x custom-metrics aggregator the original spec assumed was **sunset server-side on 2024-10-07** (Sentry help center) — `Sentry.metrics.increment()` on 7.120.4 is a silent no-op. The new metrics product requires **SDK ≥10.x** (confirmed against the project's own SaaS settings: the "Logs and Metrics" toggle is grayed out on 7.x — "Only available in SDK version 10.x and above"). The live loader script loads `browser.sentry-cdn.com/10.56.0/bundle.tracing.replay.logs.metrics.min.js` with `enableLogs: true`, pinning the current SDK train at 10.56.0. Maintainer chose first-class metrics over the lighter spans-on-7.x alternative.
- **Alternatives considered**: (A) **Spans/tracing on existing 7.120.4** — no upgrade, no SaaS change, smallest PR; rejected by maintainer in favor of first-class metric counters/dashboards. (C) **Remove HashiCorp only, defer analytics** — smallest/safest but loses US2; rejected.

### Decision 2: Migration is small but touches the known-working error pipeline → phase it
- **Decision**: Sequence as (1) SDK 7→10 upgrade + error-pipeline migration; (2) HashiCorp removal; (3) usage analytics + flush. Each its own commit/PR with tests; error reporting stays green at every step.
- **Rationale**: Only 4 files import `@sentry/node`; the breaking surface is 2× `configureScope` rewrites (`error-reporting.ts:120`, `errors.ts:56` → `Sentry.getCurrentScope()…`) + 1 `init` rebuild (`autoSessionTracking` deprecated; add `tracesSampleRate` + `enableLogs`). `addBreadcrumb`×6, `setContext`, `captureException`, `close` are unchanged; no `startTransaction`/class integrations used. Constitution III (Minimal Viable Change, PR <30 min) demands the SDK bump not be entangled with telemetry logic.
- **Alternatives considered**: one big-bang PR — rejected (un-reviewable, risks the error pipeline).

### Decision 3: Bounded flush on normal exit (transport-independent, REQUIRED)
- **Decision**: Add `await Sentry.flush(<bounded timeout>)` on the success exit path (shared teardown or `process.on("beforeExit")`), capped like the existing 4000ms error-path `Sentry.close(4000)`.
- **Rationale**: `Sentry.close(4000)` runs ONLY in the yargs `.fail()` handler (`cdktn.ts:184`); successful commands never flush. Metrics/spans buffer and flush async, and the CLI is short-lived → happy-path analytics would be dropped without an explicit bounded flush. The cap guarantees telemetry can never hang the CLI.
- **Alternatives considered**: rely on default flush — rejected (drops data on fast commands); unbounded flush — rejected (could hang CLI).

### Decision 4: Strengthen tests to assert delivery, not just emission
- **Decision**: Delivery oracle = **real v10 client + capturing custom `transport`** asserting a `trace_metric` envelope (name + attributes) reached the transport AND the success path **awaits a bounded flush before `process.exit`** (`flush() === true`). `@sentry/node` mocks are reserved for consent-gating tests (telemetry suppressed when Sentry uninitialized / `CHECKPOINT_DISABLE` set / `sendUsageTelemetry:false`) — a mock-only test would pass while real metrics are silently dropped (see contract C5, e2e-validation spike).
- **Rationale**: Integration tests disable reporting via `--enable-crash-reporting=false` (`test-helper.ts:226`), so they never exercise delivery. A test that only checks `metrics.count` was called would pass while real metrics are silently dropped (Decision 3). Constitution VII/VIII (test coverage; quickstart-driven).
- **Alternatives considered**: integration-only validation — rejected (reporting disabled there).

### Decision 5: `sendUsageTelemetry` config via the typed `ConfigBase` pattern
- **Decision**: Add `sendUsageTelemetry?: boolean` to `ConfigBase` (`commons/src/config.ts:272-279`, language-agnostic) with a validated getter on `CdktfConfig` (`cli-core/src/lib/cdktf-config.ts`), following the `importExtension`/`languageOptions` precedent — not the legacy loose raw-JSON access used by `sendCrashReports`.
- **Rationale**: The merged ESM/`importExtension` feature established the typed pattern as the current convention (`research/2026-06-07-revalidation-against-main.md`). Constitution V (Predictable Behavior — typed surface).
- **Alternatives considered**: copy `sendCrashReports`' loose access — rejected (legacy, untyped).

### Decision 6: `getUserId`/`getProjectId` preserved; HashiCorp transport removed
- **Decision**: Keep `getUserId`, `getProjectId`, `getId`, `homeDir`; remove `sendTelemetry`, `ReportRequest`, `ReportParams`, `post`, `BASE_URL` from `checkpoint.ts`, and `report()` from `errors.ts`. Relocate the kept utilities to an identity module. Keep `uuid`/`ci-info` deps (used elsewhere). Delete `checkpoint.test.ts`.
- **Rationale**: `getUserId`/`getProjectId` feed Sentry scope tags (`error-reporting.ts:120-125`); the rest is HashiCorp-only dead weight once analytics moves to Sentry. Confirmed by `research/2026-06-07-revalidation-against-main.md` (81 `Errors.*` sites, fire-and-forget `report()`).
- **Alternatives considered**: keep `checkpoint.ts` as-is and no-op the POST — rejected (YAGNI: dead code).

### Decision 7: Keep `sentry-cli` pinned at 2.58.4 (do not couple to SDK bump)
- **Decision**: Leave `@sentry/cli@2.58.4` (`Dockerfile:19`) untouched; do not re-enable the commented `mise.toml:18` 3.1.0 pin. After the SDK bump, verify release sourcemaps still symbolicate; if v10 Debug-ID handling requires it, switch `release.yml` from `releases files … upload-sourcemaps` to `sourcemaps inject` + `sourcemaps upload` (2.58.4 already supports this) — without bumping the CLI.
- **Rationale**: `sentry-cli` is orthogonal to `@sentry/node`; the maintainer reports 3.1.0 broke the release workflows, so 2.58.4 is known-good. Constitution III (one change at a time).
- **Alternatives considered**: bump sentry-cli alongside SDK — rejected (known-fragile, unrelated axis).

### Decision 8: Consent model — per-flag prompt, aligned surface, legacy-preserving non-interactive defaults
- **Decision**: The new `sendUsageTelemetry` flag exists to **align the usage-telemetry consent surface with the existing `sendCrashReports` flow** now that both flow through Sentry. Consent is **per-flag**: each unset flag is prompted once on first use in an **interactive terminal** (`isInteractiveTerminal()` = `process.stdout.isTTY && !process.env.CI`, `check-environment.ts:151`) and persisted to `cdktf.json` (reusing `askForCrashReportingConsent`/`persistReportCrashReportDecision`). When no prompt can be shown (non-TTY or CI), the **non-interactive defaults differ per flag to preserve each legacy**: `sendUsageTelemetry` → **enabled** (legacy on-by-default usage telemetry, now routed to the project's own Sentry, still gated by `CHECKPOINT_DISABLE`); `sendCrashReports` → **disabled** (legacy opt-in). Gating precedence: `CHECKPOINT_DISABLE` > explicit value > interactive prompt > non-interactive default-on (FR-016/FR-017).
- **Rationale**: A "prompt only when *neither* flag is set" rule (the original FR-008 wording) never fires for the entire existing install base on upgrade (their `sendCrashReports` is already set, `sendUsageTelemetry` is a brand-new field) — so it would silently either drop analytics for all existing users or resume collection without consent. Per-flag prompting + legacy-preserving non-interactive defaults closes that gap and honors "preserve existing behaviour for usage data tracking" while making the consent-surface alignment the *only* UX change. Detection + prompt machinery already exist (no new infra). Constitution V (Predictable Behavior — no silent change to data sharing).
- **Alternatives considered**: silent default-OFF on upgrade — rejected (project goes blind on existing base); silent default-ON with no prompt anywhere — rejected (resumes collection without asking interactive users); keep "neither set" prompt rule — rejected (never fires for upgraders).
- **Code-verification finding (2026-06-10, post-pnpm-rebase)**: the existing runtime crash-consent prompt is **dead code** — `shouldReportCrash()` can never return `undefined` (an absent `sendCrashReports` key falls through to `cdktfJson.sendCrashReports === "true"` → `false`), so the `runConsentPrompt` branch in `initializErrorReporting` is unreachable. Implementing FR-008's per-flag prompting requires restoring the tri-state (absent key → `undefined`), which **revives the crash-reporting prompt** for interactive users whose `cdktf.json` lacks the key. ⚠️ **Migration note (user-facing, for changelog/release notes)**: after this feature, interactive (TTY, non-CI) runs in projects whose `cdktf.json` is missing `sendCrashReports` and/or `sendUsageTelemetry` will be prompted once per missing flag; previously the crash prompt silently never fired (effective `false`). Non-interactive behavior: crash stays default-off; usage defaults on (legacy-preserving, FR-016).
- **No-project case (decided 2026-06-10, maintainer)**: commands that can run outside a project (e.g. `cdktn convert` with no `cdktf.json`) have nowhere to persist consent (`persistReportCrashReportDecision` would throw). Decision: **no prompt; treat as non-interactive** — usage telemetry effective-enabled per the FR-016 legacy default (still gated by `CHECKPOINT_DISABLE` + `SENTRY_DSN`); crash reporting stays off (`shouldReportCrash()` → false without a readable `cdktf.json`). Matches legacy checkpoint behavior, which sent convert telemetry regardless of project presence.

### Decision 9: `tracesSampleRate: 0` — CONFIRMED metrics ship independently of trace sampling
- **Decision**: Set `tracesSampleRate: 0` in `Sentry.init()`. **Empirically confirmed** against `@sentry/node@10.57.0` (spike: [research/2026-06-10-v10-metrics-tracessamplerate-independence.md](research/2026-06-10-v10-metrics-tracessamplerate-independence.md)): a `trace_metric` envelope is delivered with `flush()===true` at `tracesSampleRate: 0` (and at 1, and unset). Metric delivery is **not** gated by trace sampling. Zero trace-quota cost; FR-015 satisfied.
- **Correction (was an assumption, now measured)**: `enableLogs: true` is **NOT** required for metrics — metrics deliver without it. `enableLogs` governs the separate `Sentry.logger.*` structured-logs product. Drop the metrics⇄`enableLogs` coupling; omit `enableLogs` (YAGNI — structured logs are not a requirement of this feature).
- **New privacy finding**: v10 auto-attaches `server.address` = the machine **hostname** to every metric — a data point the legacy HashiCorp transport never sent. Suppress it by setting `serverName` to a fixed constant (e.g. `"cdktn-cli"`) in `Sentry.init()` (confirmed: `serverName:"redacted"` overrides it; `""` falls back to hostname). See Decision C in the spike.
- **Delivery oracle (concrete)**: assert a captured `trace_metric` envelope whose `payload.items[].name === "cli.command.invoked"` carries the expected attributes AND `await Sentry.flush(2000) === true`.

## Resolved unknowns (was NEEDS CLARIFICATION)
- Metrics transport on current SaaS → **v10 metrics API** (D1).
- SaaS settings sufficiency → **enable "Logs and Metrics" product**; set `tracesSampleRate` in Node init; Performance Monitoring already on (D1).
- Delivery on short-lived CLI → **bounded flush on normal exit** (D3).
- Config field shape → **typed `ConfigBase` + `CdktfConfig` getter** (D5).
- Release tooling impact → **keep sentry-cli 2.58.4; verify/modernize sourcemap command if needed** (D7).

## External dependencies note
- `@sentry/node` `^10.56` (major upgrade, 3 packages). Consider `sl deps add` tracking.
- Sentry SaaS (`cdktn/cdktn`, EU region): enable Logs & Metrics product (org-side, maintainer action).
