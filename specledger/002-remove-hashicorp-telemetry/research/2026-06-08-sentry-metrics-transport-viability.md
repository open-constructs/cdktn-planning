# Research: Is the Sentry metrics transport in the spec still viable?

**Date**: 2026-06-08
**Context**: The spec (FR-002/FR-003) and all three 2026-03-20 research spikes assume usage analytics can be routed through `@sentry/node@7.120.4`'s custom-metrics aggregator (`Sentry.metrics.increment()` + `Sentry.metrics.metricsAggregatorIntegration()`). The 2026-06-07 re-validation confirmed those SDK *methods* exist and are callable at runtime — but it did NOT confirm the Sentry *server* still ingests them. Two screenshots of the project's Sentry SaaS settings prompted a deeper check.
**Time-box**: 45 minutes

## Question

Does `@sentry/node@7.120.4`'s `Sentry.metrics.*` aggregator still deliver data to current Sentry SaaS, and if not, what transport should carry usage analytics (US2) instead?

## How this was verified (three independent lines of evidence)

1. **Sentry's own documentation / help center** (web):
   - Help center article "Metrics Beta Ended on October 7th" (sentry.zendesk.com) — the custom **Metrics Beta ended October 7, 2024**. Sentry's stated replacement: *"we now have replacements for both the metric alerts, and the aggregations and visualizations of our previous metrics experience"* and a *"span based metrics solution that lets you freely aggregate any attribute you attach to spans without cardinality concerns"* (i.e. **Trace Explorer / span-based metrics**).
   - Sentry developer docs page "Metrics (deprecated)" (develop.sentry.dev/sdk/telemetry/metrics) — the original custom-metrics SDK telemetry is marked deprecated; the metrics API was removed from the SDKs (corroborated across getsentry SDK issues for dotnet #3597, dart #2277).
   - **Confidence: High.** Multiple first-party Sentry sources agree the legacy custom-metrics product (the one 7.120.4 targets) was sunset, with span-based metrics as the successor.

2. **The project's own Sentry SaaS settings** (two screenshots, 2026-06-07/08):
   - Loader Script on **SDK 10.x**: a distinct **"Enable Logs and Metrics"** toggle exists and is **OFF**.
   - Loader Script switched to **SDK 7.x**: the same **"Enable Logs and Metrics"** row is **grayed out** with the label **"Only available in SDK version 10.x and above."**
   - This is direct, project-specific confirmation that the *new* (EAP/span-tracemetrics) Logs & Metrics product is **categorically unavailable on the 7.x SDK line** — independent of the web evidence about the *old* product's sunset.
   - **Caveat (honest reading):** this panel is the **JavaScript Loader Script** (browser SDK via `js-de.sentry-cdn.com`), which does NOT govern the Node CLI — the CLI bundles its own `@sentry/node` and configures `Sentry.init()` in code (`error-reporting.ts:84`). So these toggles are *browser-loader defaults*, not the Node transport switch. What the panel authoritatively tells us is org/product-level facts: (a) the org/project is EU-region, (b) the account's SDK guidance is 10.x, (c) the new Logs/Metrics product is gated to SDK ≥10.x. It does not, by itself, prove the Node 7.x legacy aggregator endpoint is dead — line 1 (web) establishes that.

3. **Runtime probe of the installed module** (2026-06-07, prior note): `node -e "require('@sentry/node')"` showed `Sentry.metrics` exposes `increment/distribution/set/gauge/metricsAggregatorIntegration` — all callable. This is what made the earlier "plan holds" conclusion *look* safe: the methods are present. The gap was that **method presence ≠ server ingestion.** Lines 1–2 close that gap: the methods serialize to an ingestion path the server no longer honors.

**Combined conclusion:** On the currently-pinned `@sentry/node@7.120.4`, there is **no working metrics path** — the legacy aggregator is sunset server-side (line 1), and the new product requires SDK ≥10.x (line 2). The SDK calls would be **silent no-ops** end-to-end: no error thrown client-side, no data stored server-side.

## Findings

### Finding 1: The spec's assumed transport is server-side dead (CONFIDENCE: high)

`Sentry.metrics.increment()` / `metricsAggregatorIntegration()` in 7.120.4 target the Metrics Beta ingestion that ended 2024-10-07. They will not appear in Sentry. FR-002/FR-003 as written are **INVALIDATED** at the transport level (the SDK-availability and consent reasoning around them still holds; only the *mechanism* is dead).

### Finding 2: The new Logs/Metrics product needs SDK ≥10.x (CONFIDENCE: high)

Confirmed directly against this project's settings (screenshot: grayed-out row, "Only available in SDK version 10.x and above"). The CLI is pinned at 7.120.4 across `commons`, `cli-core`, `cdktn-cli`. Using the new metrics requires a major SDK upgrade (7→8→9→10), which carries breaking changes (v8 removed `Sentry.configureScope` — used at `error-reporting.ts:120` and `errors.ts:56` — and reworked `init`/integrations). This collides with constitution principle III (Minimal Viable Change, PRs <30 min) and risks the *known-working* error pipeline.

### Finding 3: Sentry's official replacement — span-based metrics — works on 7.x (CONFIDENCE: high)

Sentry directs former metrics users to **spans/Trace Explorer**. `@sentry/node@7.120.4` already exports the tracing API (`startTransaction`, `startSpan`, `startInactiveSpan`, `startSpanManual` — confirmed in `node_modules/@sentry/node/types/index.d.ts`). A usage event becomes a transaction/span tagged with `command`, `language`, `ci`, with duration as the span/transaction duration. Tags/attributes on spans are queryable/aggregatable in Trace Explorer — covering the spec's analytics goals (command adoption, language usage, synth timing, CI vs interactive).

### Finding 4: SaaS settings — sufficient for spans, NOT for metrics (CONFIDENCE: high — this answers the user's settings question)

- **For spans/tracing (Option A):** the project already has **Performance Monitoring enabled** (`tracesSampleRate: 1.0`, per both screenshots). The Node SDK needs `tracesSampleRate` set in `Sentry.init()` (the loader default doesn't apply to Node) — a code change, not a SaaS change. **No Sentry SaaS settings change required.** Spans ingest under the existing plan.
- **For new metrics (Option B):** requires enabling the **"Logs and Metrics"** product (currently OFF) **and** SDK ≥10.x. Both a SaaS change and a code upgrade.
- **For legacy 7.x metrics:** no setting can revive it — the product is gone.
- One org-side item still worth a maintainer confirmation: that the `cdktn/cdktn` project's plan/quota accommodates one transaction per CLI command at `tracesSampleRate: 1.0` (or pick a sample rate). Spans count toward the performance-units quota.

### Finding 5: The flush-on-exit risk is transport-independent (CONFIDENCE: high)

Per the 2026-06-07 build/release spike, `Sentry.close(4000)` runs only on the error path (`cdktn.ts:184`); the happy path never flushes. A span/transaction must be `.finish()`-ed AND the client flushed before `process.exit`, exactly like metrics would. So the **bounded flush-on-normal-exit requirement holds regardless of which transport is chosen** — it is, if anything, more clearly necessary for spans (a transaction not flushed is simply lost).

## DECISION (2026-06-08): Option B — upgrade `@sentry/node` to v10 + new Logs/Metrics

The maintainer chose to **upgrade the SDK to v10 and adopt the new (EAP) Logs & Metrics product**, rather than the spans-on-7.x option. The following supplements the original decision matrix below.

### Loader-script exploration (confirms the v10 product + version train)

Fetched the project's live loader script `https://js-de.sentry-cdn.com/5a76d29d61ea79fd3ee038f276a6be21.min.js`. With Logs & Metrics enabled it lazy-loads:

```
https://browser.sentry-cdn.com/10.56.0/bundle.tracing.replay.logs.metrics.min.js
default config: { tracesSampleRate: 1, replaysSessionSampleRate: 0.1, replaysOnErrorSampleRate: 1, enableLogs: true }
```

- **Current Sentry SDK train = 10.56.0** → the `@sentry/node` upgrade target is `^10.56`.
- The bundle variant `tracing.replay.logs.metrics` and `enableLogs: true` confirm logs+metrics are first-class in v10.
- Caveat (unchanged): this is the **browser** bundle (`browser.sentry-cdn.com`) / loader, which does NOT drive the Node CLI. The CLI uses the separate `@sentry/node` package — same version train, different package. It validates the version + product availability, not the Node wiring (that's code in `error-reporting.ts`).

### New v10 Node API (what the migration must adopt)

- **Init**: `Sentry.init({ dsn, tracesSampleRate: <n>, enableLogs: true, /* metrics on by default in v10 */ })`. `enableLogs` is now a top-level option in 10.x (was `_experiments.enableLogs` earlier).
- **Metrics**: `Sentry.metrics.count("cli.command.invoked", 1, { attributes: { command, language, ci } })` — the new trace/EAP metrics API (distinct from the deprecated 7.x `metrics.increment`). Emitting inside a span auto-tags the metric with trace/span IDs.
- **Logs** (optional): `Sentry.logger.info(...)` gated by `enableLogs: true`.

### v7→v10 migration blast radius in THIS codebase (CONFIDENCE: high)

Mapped every `Sentry.*` symbol used in `src` (grep): `addBreadcrumb` ×6 (`logging.ts`), `configureScope` ×2 (`error-reporting.ts:120`, `errors.ts:56`), `setContext` ×1, `init` ×1, `close` ×1, `captureException` ×1. Only **4 files** import `@sentry/node`: `cdktn.ts`, `error-reporting.ts`, `errors.ts`, `logging.ts`.

| Current API | v8+ status | Action |
|---|---|---|
| `Sentry.configureScope((s)=>s.setUser/​setTag)` (`error-reporting.ts:120-125`) | **REMOVED in v8** | → `Sentry.getCurrentScope().setUser({id}); .setTag("projectId", …)` |
| `Sentry.configureScope((s)=>s.setTransactionName(scope))` (`errors.ts:56`) | **REMOVED in v8** | → `Sentry.getCurrentScope().setTransactionName(scope)` (verify method name on v10 scope) |
| `Sentry.init({ autoSessionTracking: true, … })` (`error-reporting.ts:84-87`) | options restructured; `autoSessionTracking` deprecated in v8 | rebuild init: drop/replace `autoSessionTracking`, add `tracesSampleRate` + `enableLogs`; keep `dsn`, `release`, `beforeSend` |
| `Sentry.addBreadcrumb` ×6 (`logging.ts`) | unchanged | none |
| `Sentry.setContext` / `Sentry.captureException` / `Sentry.close` | unchanged | none |
| `startTransaction` / class integrations (`new X()`) | removed/changed in v8 | **not used here** → no breakage |
| Node engine | v8 ≥14.18, v9/v10 ≥18 | repo on Node 20.20 + build target `node22` → **fine** |

Net: the breaking surface is **small and concentrated** — 2 `configureScope` rewrites + 1 `init` rebuild, across 2 files. The 6 `addBreadcrumb` calls and the rest are unaffected. The risk is not breadth but that the upgrade touches the **known-working error pipeline**, so it warrants its own commit/PR step and a regression check on error reporting.

### SaaS settings (answers the user's question, under Option B)

- Enable the **"Logs and Metrics"** product on the `cdktn/cdktn` project (currently OFF) — required for v10 metrics/logs ingestion.
- Keep Performance Monitoring on; set a deliberate `tracesSampleRate` in the Node `init` (loader default of `1.0` is browser-only).
- Confirm plan/quota for the new metrics + any spans.

### `sentry-cli` is an independent, fragile axis — do NOT bump it during the SDK upgrade

`sentry-cli` (release tooling) is a **separate dependency** from `@sentry/node` (runtime SDK) and must be treated independently during the v10 migration:

- The release jobs run inside the `terraconstructs/jsii-terraform` container (`release.yml:29-30`), which bakes **`@sentry/cli@2.58.4`** via `Dockerfile:19` (`npm install -g @sentry/cli@2.58.4 --unsafe-perm`).
- `mise.toml:18` has a **commented-out** `# "ubi:getsentry/sentry-cli" = "3.1.0"` — i.e. a 3.x pin was attempted and backed out. Per the maintainer: **without the 2.58.4 pin the GitHub release workflows stopped working.** So 2.58.4 is the known-good version and 3.1.0 is known-bad.
- **Constraint for this migration: keep `sentry-cli` pinned at 2.58.4. Do NOT couple an SDK bump to a sentry-cli bump** — they are orthogonal and the CLI axis is already known-fragile. Any sentry-cli change is out of scope here.

**Sourcemap implication of the SDK bump (must verify):** Sentry v8+ resolves minified stack traces via **Debug IDs**. The release pipeline currently uses the legacy form `sentry-cli releases files cdktn-cli-<v> upload-sourcemaps ./packages/cdktn-cli/bundle` (`release.yml:76,161`), which relies on release+dist matching rather than debug IDs. Under v10 this *may* still work but is not the recommended path; the modern flow is `sentry-cli sourcemaps inject <dir>` then `sentry-cli sourcemaps upload --release=cdktn-cli-<v> <dir>`. **sentry-cli 2.58.4 already supports `sourcemaps inject`/`upload`** (debug IDs landed ~2.17), so the workflow can be modernized **without** bumping sentry-cli if v10 stack traces come back un-symbolicated. Action: after the SDK bump, verify a release sourcemap resolves in Sentry; only switch the command form if needed, keeping 2.58.4. (esbuild already emits sourcemaps — `build.ts:63` `sourcemap: true`.)

### Sequencing recommendation (constitution III — Minimal Viable Change)

Split into reviewable steps: **(1)** SDK 7→10 upgrade + error-pipeline migration (configureScope→getCurrentScope, init rebuild) as an isolated change that keeps error reporting green; **(2)** HashiCorp removal (US1/US4); **(3)** usage analytics via v10 metrics + bounded flush-on-exit (US2); each with tests. This keeps the SDK bump from being entangled with telemetry logic in one giant PR.

## Decisions

- **D1**: The spec's metrics transport (7.x aggregator) is not viable. US2 must use a different mechanism. US1/US3/US4 (remove HashiCorp, keep Sentry errors) are unaffected.
- **D2 (recommended pending user confirmation)**: Carry usage analytics as **Sentry spans/transactions on the existing 7.120.4 SDK** (Option A). Rationale: no SDK upgrade, no SaaS change (Performance Monitoring already on), smallest PR, doesn't touch the working error pipeline, and is Sentry's own sanctioned replacement for the sunset metrics. Aligns with YAGNI/KISS/Minimal-Viable-Change.
- **D3 (alternative)**: Upgrade `@sentry/node` to v10 and use the new Logs/Metrics API (Option B) — only if maintainers want first-class metric counters/dashboards and accept a larger, partly-breaking change plus enabling the SaaS toggle.
- **D4 (alternative)**: Ship privacy fix only; defer analytics to a follow-up spec (Option C).
- **D5**: Whichever transport, keep the **bounded flush-on-normal-exit** and the **success-path delivery unit test** requirements (transport-independent).

## Recommendations

1. Decide D2 vs D3 vs D4 with the user (the transport choice rewrites FR-002/FR-003 and the call-site conversions in the spec).
2. If Option A: update spec FR-002/FR-003 to "emit a Sentry transaction/span per command" and set `tracesSampleRate` in `Sentry.init()`; update the 7-call-site conversion table from `metrics.increment` to span emission.
3. Confirm with a maintainer the Sentry plan's performance-units quota / desired `tracesSampleRate`.
4. Carry forward the flush-on-exit + success-path-delivery-test requirements into plan.md tasks.

## References

- Sentry help center — Metrics Beta ended Oct 7, 2024 / span-based replacement: https://sentry.zendesk.com/hc/en-us/articles/26369339769883-Metrics-Beta-Ended-on-October-7th
- Sentry develop docs — Metrics (deprecated): https://develop.sentry.dev/sdk/telemetry/metrics/
- Sentry product — Application Metrics (new): https://docs.sentry.io/product/explore/metrics/
- Sentry v8→v9 Node migration (breaking changes context): https://docs.sentry.io/platforms/javascript/guides/node/migration/v8-to-v9/
- getsentry SDK metrics-removal issues: getsentry/sentry-dotnet#3597, getsentry/sentry-dart#2277
- Project SaaS settings screenshots (2026-06-07/08): Loader Script SDK 10.x ("Logs and Metrics" OFF) and SDK 7.x ("Logs and Metrics" grayed, "Only available in SDK 10.x and above")
- Installed SDK tracing API: `node_modules/@sentry/node/types/index.d.ts` (`startTransaction`, `startSpan`, …)
- Runtime init / flush: `packages/@cdktn/cli-core/src/lib/error-reporting.ts:84`, `packages/cdktn-cli/src/bin/cdktn.ts:184`
- Related notes: `research/2026-06-07-revalidation-against-main.md`, `research/2026-06-07-build-release-sentry-injection.md`
