# Research: Sentry usage and whether checkpoint functionality should move to Sentry

**Date**: 2026-03-20
**Context**: Before removing HashiCorp checkpoint telemetry, need to understand the full Sentry integration and whether any checkpoint data should be preserved via Sentry instead.
**Time-box**: 30 minutes

> **⚠️ Reconciled with finalized spec — 2026-06-08.** The core conclusion (route analytics through Sentry, drop the redundant `report()` path, preserve `getUserId`/`getProjectId`) still holds. Two things changed: (1) the **transport** — the 7.x custom-metrics API this note pointed at was **sunset server-side (2024-10-07)**, so the decision is to **upgrade `@sentry/node` 7→^10.56 and use the new v10 metrics API** (`Sentry.metrics.count`); (2) the `sendCrashReports` **rename was rejected** (spec OS-002) in favor of a separate `sendUsageTelemetry` flag. Corrections marked **`[CORRECTION 2026-06-08]`**. Authoritative: [`spec.md`](../spec.md), [`research.md`](../research.md), [`2026-06-08-sentry-metrics-transport-viability.md`](2026-06-08-sentry-metrics-transport-viability.md).

## Question

What is the full scope of Sentry usage in the codebase, and should any of the data currently sent to HashiCorp's checkpoint API be migrated to Sentry instead of simply deleted?

## Findings

### Finding 1: Sentry provides usage analytics features — not just error tracking

**UPDATE (2026-03-20)**: Sentry now offers [custom metrics](https://docs.sentry.io/product/explore/metrics/) (counters, gauges, distributions) that are trace-connected, meaning every metric event can be linked back to traces, logs, and errors. This is suitable for the kind of usage telemetry currently sent to HashiCorp's checkpoint API.

> **[CORRECTION 2026-06-08]** The metrics product referenced here went through a lifecycle change: the **original custom-metrics beta ended 2024-10-07** (the API `@sentry/node@7.120.4` exposes is a server-side no-op), and the **new** metrics product requires **SDK ≥10.x**. The finalized approach upgrades the SDK to **^10.56** and uses the new `Sentry.metrics.count(name, value, { attributes })` API with `enableMetrics`/`enableLogs`. See [`2026-06-08-sentry-metrics-transport-viability.md`](2026-06-08-sentry-metrics-transport-viability.md).

Key Sentry analytics capabilities:

- **Custom metrics**: Send counters (e.g., `command.invoked`), gauges, and distributions from code
- **Trace-connected**: Every metric links to related traces and errors — richer than what checkpoint provides
- **Span metrics**: Performance data automatically derived from spans ([span metrics docs](https://docs.sentry.io/concepts/key-terms/tracing/span-metrics/))
- **Dashboards**: Built-in exploration and visualization of metrics data
- **SDK support**: Available for JavaScript/Node.js, Python, and all languages cdktn targets

**Note on Sentry Metrics evolution**: Sentry [deprecated their original custom metrics SDK API](https://develop.sentry.dev/sdk/telemetry/metrics/) and rebuilt it on top of their new Event Analytics Platform (EAP), which stores every metric event independently in ClickHouse and connects it to trace IDs. The new approach is span-based metrics. Implementation should target the current (non-deprecated) API.

**Confidence**: High — verified via [Sentry docs](https://docs.sentry.io/product/explore/metrics/) and [Sentry blog](https://blog.sentry.io/the-metrics-product-we-built-worked-but-we-killed-it-and-started-over-anyway/).

### Finding 2: Sentry is a strong fit for migrating checkpoint analytics

The project has Sentry on a **full business plan with OSS support**, which includes metrics features. Migrating usage telemetry to Sentry instead of simply deleting it provides:

| Benefit | Details |
|---------|---------|
| **Feature prioritization** | Know which commands, languages, and providers are actually used |
| **Project evolution** | Data-driven decisions about what to build/deprecate |
| **Single platform** | No new vendor — reuse existing Sentry infrastructure, DSN, and consent flow |
| **User opt-out preserved** | Existing `sendCrashReports` consent in `cdktf.json` already gates Sentry; usage telemetry respects the same opt-out |
| **Trace correlation** | Usage metrics linked to errors — see which commands fail most, not just that they were used |
| **No additional cost** | Already on business plan with analytics features included |

What checkpoint currently tracks (and should be preserved via Sentry):

| Data point | Sentry mechanism | Value |
|------------|-----------------|-------|
| Command invoked (`synth`, `init`, `deploy`, etc.) | Custom metric counter or span | Feature adoption tracking |
| Language used (`typescript`, `python`, etc.) | Metric tag / span attribute | Language support prioritization |
| CLI version | Already set as Sentry release | Version adoption tracking |
| OS / arch | Already captured in Sentry environment context | Platform support decisions |
| CI environment | Metric tag / span attribute | CI vs interactive usage patterns |
| Synth timing | Span duration or distribution metric | Performance monitoring |
| Provider usage | Metric tag | Provider ecosystem priorities |

### Finding 3: Current Sentry integration serves crash/error reporting only

Today, the codebase uses Sentry exclusively for **error reporting and crash diagnostics**:

| Component | File | What it does |
|-----------|------|-------------|
| Initialization | `cli-core/src/lib/error-reporting.ts` | `Sentry.init()` with session tracking, custom `beforeSend` filter |
| User context | `cli-core/src/lib/error-reporting.ts` | Sets `userId` and `projectId` as Sentry scope tags |
| Environment context | `cli-core/src/lib/error-reporting.ts` | Attaches debug info (versions, OS, etc.) |
| Breadcrumbs | `commons/src/logging.ts` | Every log call (`trace`→`fatal`) adds a Sentry breadcrumb |
| Error scope | `commons/src/errors.ts` | `Errors.setScope()` sets Sentry transaction name |
| Flush on exit | `cdktn-cli/src/bin/cdktn.ts` | `Sentry.close(4000)` in error handler |
| Exception capture | `cli-core/src/lib/error-reporting.ts` | `captureException()` wraps `Sentry.captureException()` |

**Confidence**: High — comprehensive search of all `@sentry/node` imports.

### Finding 4: The errors.ts → checkpoint path is a redundant telemetry channel

`errors.ts` has a `report()` function that sends error metadata to HashiCorp's checkpoint API whenever `Errors.Internal/External/Usage()` is called. This is **separate from Sentry** — the same errors go to both:

1. **Sentry** (via breadcrumbs in logging.ts + scope tags + captureException)
2. **HashiCorp checkpoint** (via `report()` → `ReportRequest()` → `post()`)

The HashiCorp path is redundant. Sentry already captures these errors with richer context (stack traces, breadcrumbs, environment info). The `report()` function in errors.ts should be removed — Sentry handles this better.

**Error volume**: ~80 call sites across the codebase use `Errors.Internal/External/Usage`:
- `Errors.Usage()`: ~45 call sites
- `Errors.Internal()`: ~20 call sites
- `Errors.External()`: ~15 call sites

Every one of these currently fires-and-forgets a report to HashiCorp. None depend on the result.

**Confidence**: High.

### Finding 5: Sentry initialization is consent-gated and lazy

- **Opt-in**: Controlled by `sendCrashReports` field in `cdktf.json`
- **Consent prompt**: Users are asked on first CLI use (non-CI only)
- **Lazy**: Initialized per-command in `handlers.ts` (9 command handlers call `initializErrorReporting`)
- **SENTRY_DSN required**: Built into the CLI bundle at build time via esbuild define; if not set, Sentry is disabled
- **CI skip**: No consent prompt in CI environments

Usage telemetry migration to Sentry can reuse this same consent gate — if the user has opted out of crash reports, usage telemetry is also suppressed. This maintains the existing privacy contract.

**Confidence**: High.

### Finding 6: Dependencies are shared but separable

| Dependency | checkpoint.ts | Sentry/errors | Can remove? |
|------------|--------------|---------------|-------------|
| `@sentry/node` | No | Yes (3 packages) | No — Sentry needs it |
| `uuid` | `getId()`, `ReportRequest()` | No direct use, but `getUserId()` uses it | No — `getUserId()` preserved for Sentry |
| `ci-info` | `ReportRequest()` | `error-reporting.ts` | No — Sentry needs it |
| `https` (builtin) | `post()` | No | N/A — builtin |

### Finding 7: captureException is defined but never called externally

The custom `captureException()` function in `error-reporting.ts` is exported but **has zero external callers**. This is dead code that could be cleaned up, but that's outside the scope of the checkpoint removal.

**Confidence**: High — grep found no imports of this function outside its definition file.

## Decisions

- **Decision 1: Migrate checkpoint usage analytics to Sentry.** Sentry's metrics and span-based analytics provide the same (and richer) capabilities as HashiCorp's checkpoint API. The project has a full Sentry business plan with OSS support, so these features are available at no additional cost. Usage data helps the project evolve, prioritize features, and understand adoption patterns. Users can still opt out via the existing `sendCrashReports` consent mechanism.

- **Decision 2: The `report()` function in errors.ts is fully redundant with Sentry.** Every error that goes to HashiCorp via `report()` is already captured by Sentry with richer context. Safe to remove entirely — no need to migrate this path.

- **Decision 3: Replace `sendTelemetry` call sites with Sentry spans/metrics.** The 7 existing `sendTelemetry` call sites should be converted to emit Sentry custom metrics or spans instead of POSTing to HashiCorp. This preserves the analytics data while routing it through infrastructure the project controls.

- **Decision 4: Reuse existing consent flow.** The `sendCrashReports` opt-out in `cdktf.json` already gates all Sentry activity. Usage telemetry sent via Sentry will automatically respect this setting — no new consent mechanism needed.

## Recommendations

1. **Remove HashiCorp-specific code** — delete `ReportRequest`, `ReportParams`, `post()`, `BASE_URL`, and the `report()` function in errors.ts. These are the HashiCorp-specific transport layer.

2. **Replace `sendTelemetry` with Sentry-based telemetry** — convert the 7 call sites to use Sentry custom metrics or spans. Preserve the same data points (command, language, OS, CI, timing) but route through Sentry instead of HashiCorp.

3. **Preserve `getUserId`/`getProjectId`** — relocate to a new module (e.g., `identity.ts`). These are used by both Sentry error reporting and will be used by the new telemetry.

4. **Target Sentry's current (non-deprecated) metrics API** — use span-based metrics, not the deprecated `metrics.incr()` SDK API. Check `@sentry/node` 7.120.4 capabilities or evaluate upgrading to the latest SDK version if needed for metrics support.
   > **[CORRECTION 2026-06-08 — RESOLVED]** This recommendation was prescient. Outcome: 7.120.4 is **not** sufficient (its metrics API targets the sunset beta). Decision taken — **upgrade `@sentry/node` to ^10.56** and use the new v10 metrics API. Migration blast radius is small (2× `configureScope`→`getCurrentScope`, `init` rebuild); see the viability note.

5. **Consider renaming `sendCrashReports` to a broader telemetry consent flag** — since it now gates both crash reports and usage analytics, a name like `sendTelemetry` or `telemetryEnabled` may be clearer. However, this is a breaking config change and should be weighed against backward compatibility (could accept both names).
   > **[CORRECTION 2026-06-08 — REJECTED]** The finalized spec keeps the two consent concerns **independent** and does **not** rename `sendCrashReports` (spec **OS-002**). Instead a new, separate `sendUsageTelemetry` flag is added to `ConfigBase` (typed, per the `importExtension` precedent). `sendCrashReports` continues to gate crash reporting only; Sentry initializes if **either** flag is true (FR-007).

## References

- [Sentry Metrics](https://docs.sentry.io/product/explore/metrics/)
- [Sentry Span Metrics](https://docs.sentry.io/concepts/key-terms/tracing/span-metrics/)
- [Sentry Metrics rebuild blog post](https://blog.sentry.io/the-metrics-product-we-built-worked-but-we-killed-it-and-started-over-anyway/)
- [Sentry Metrics SDK (deprecated)](https://develop.sentry.dev/sdk/telemetry/metrics/)
- Error reporting: `packages/@cdktn/cli-core/src/lib/error-reporting.ts`
- Errors module: `packages/@cdktn/commons/src/errors.ts`
- Logging breadcrumbs: `packages/@cdktn/commons/src/logging.ts`
- CLI entry point: `packages/cdktn-cli/src/bin/cdktn.ts`
- Build config (SENTRY_DSN): `packages/cdktn-cli/build.ts`
- Prior research: `specledger/002-remove-hashicorp-telemetry/research/2026-03-20-checkpoint-usage-analysis.md`
