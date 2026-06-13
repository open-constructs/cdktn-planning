# Research: @sentry/node v10 — metrics delivery vs `tracesSampleRate`

**Date**: 2026-06-10
**Context**: The rebased spec (002) pins `tracesSampleRate: 0` on the premise that v10 ships custom metrics independently of trace sampling (research Decision 9, contracts C4, FR-015). That premise was flagged "MUST confirm" because dropping usage metrics via sampling would silently defeat US2/SC-002. This spike resolves it empirically against the real SDK.
**Time-box**: ~20 min (live SDK probe in a throwaway dir)
**Confidence**: **High** — direct observation against `@sentry/node@10.57.0` (within the planned `^10.56`), capturing the actual envelope that reaches the transport.

## Question

Does `@sentry/node` v10 deliver `Sentry.metrics.*` metrics when `tracesSampleRate: 0`? And is `enableLogs: true` required for metrics to ship?

## Method

Throwaway dir (`/var/tmp/sentry-v10-spike`), `npm i @sentry/node@^10.56` → resolved **10.57.0**. Real `Sentry.init()` with a **capturing `transport`** (records every envelope item `type`), emit `Sentry.metrics.count(...)` / `.distribution(...)`, `await Sentry.flush(2000)`, inspect captured items. Swept `tracesSampleRate` ∈ {0, 1, unset} × `enableLogs` ∈ {on, off} and `_experiments.enableMetrics`.

## Findings

### Finding 1: Metrics ARE delivered at `tracesSampleRate: 0` (premise CONFIRMED)

Every configuration produced exactly one `trace_metric` envelope item that reached the transport, with `flush() === true`:

| Config | `trace_metric` delivered? |
|--------|---------------------------|
| `tracesSampleRate: 0` + `enableLogs: true` | ✅ |
| `tracesSampleRate: 0`, **no** `enableLogs` | ✅ |
| `tracesSampleRate: 1` + `enableLogs: true` | ✅ |
| `tracesSampleRate` unset + `enableLogs: true` | ✅ |
| `tracesSampleRate: 0` + `_experiments.enableMetrics` | ✅ |

Metric delivery is **independent of `tracesSampleRate`**. (A `trace_id` is auto-attached to the metric for correlation, but delivery is not gated by whether that trace is sampled.) **`tracesSampleRate: 0` is safe.**

### Finding 2: `enableLogs` is NOT required for metrics

Config "B" (`tracesSampleRate: 0`, no `enableLogs`) delivered the metric. `enableLogs` governs the separate `Sentry.logger.*` **structured-logs** product, not metrics. **This corrects the spec/contract wording** (FR-003, C4, data-model), which implied metrics need `enableLogs: true`. Metrics work without it; keep `enableLogs` only if structured logs are also wanted.

### Finding 3: API surface + envelope shape (makes the test oracle concrete)

- `Sentry.metrics` exposes `count`, `distribution`, `gauge` (matches FR-014 `Sentry.metrics.count`).
- Envelope item type is **`trace_metric`** (payload `version: 2`, with a batched `items[]` array — multiple metrics in one envelope item).
- `count("cli.command.invoked", 1, {attributes})` → `{ name: "cli.command.invoked", type: "counter", value: 1, attributes: {...} }`.
- `distribution("cli.synth.duration", 1234, { unit: "millisecond", attributes })` → `{ type: "distribution", unit: "millisecond", value: 1234 }`.
- Custom attributes (`command`, `language`, `ci`) survive as `{ value, type }` pairs. SDK auto-adds `sentry.sdk.name/version`, `sentry.timestamp.sequence`.

**Delivery oracle for the unit test**: assert a captured `trace_metric` envelope whose `payload.items[].name === "cli.command.invoked"` carries the expected attributes, AND `await Sentry.flush(2000) === true`.

### Finding 4: ⚠️ v10 auto-attaches `server.address` = machine hostname (NEW PII)

Every metric carries `server.address: "<hostname>"` by default. The **legacy HashiCorp telemetry never sent the hostname** (it sent `os`, `arch`, `userId` [non-CI], `projectId`) — so v10 metrics would introduce a *new* personally-identifiable data point into a **privacy-motivated** migration. It is suppressible via the `serverName` init option:

| `serverName` | resulting `server.address` |
|---|---|
| (unset) | `"podmaster"` (real hostname) |
| `""` | `"podmaster"` (empty ignored → falls back) |
| `"redacted"` | `"redacted"` |

**Mitigation**: set `serverName` to a fixed non-hostname constant (e.g. `"cdktn-cli"` or the release string) in `Sentry.init()`. Note this also affects error events' server name; confirm that's acceptable for crash reports (it likely is — the existing error pipeline does not rely on hostname).

## Decisions

- **Decision A**: Keep `tracesSampleRate: 0`. Confirmed metrics deliver regardless of sampling; FR-015 is satisfied with no positive sample rate (zero trace-quota cost). Decision 9 / C4's "MUST confirm" is now **resolved CONFIRMED**.
- **Decision B**: `enableLogs` is **not** required for metrics. Drop the metrics⇄`enableLogs` coupling from FR-003/C4/data-model; only keep `enableLogs: true` if structured logs are independently desired (not a requirement of this feature → omit per YAGNI).
- **Decision C**: Set `serverName` to a fixed constant in `Sentry.init()` to suppress the hostname (`server.address`) from metrics, keeping the privacy posture at least as tight as the legacy HashiCorp transport.

## Recommendations

1. Update **research Decision 9** and **contracts C4** to "CONFIRMED at 10.57.0: metrics deliver at `tracesSampleRate: 0`; `enableLogs` not required for metrics."
2. Update **FR-003** to stop mandating `enableLogs: true` for metrics (make it optional/omit), and add a requirement (or fold into FR-002/FR-014) to set `serverName` to a fixed constant so the hostname is not exfiltrated.
3. Make the **C5 delivery oracle** concrete per Finding 3 (`trace_metric` → `payload.items[].name`).
4. Reproduce: `/var/tmp/sentry-v10-spike/probe3.mjs` (payload capture) and `probe4.mjs` (serverName sweep).

## References

- `@sentry/node@10.57.0` (installed `npm i @sentry/node@^10.56`); `Sentry.metrics = { count, distribution, gauge }`.
- Probe scripts: `/var/tmp/sentry-v10-spike/probe2.mjs` (config sweep), `probe3.mjs` (payload), `probe4.mjs` (serverName).
- Related: [v10 e2e validation](2026-06-08-v10-e2e-validation.md), [transport viability](2026-06-08-sentry-metrics-transport-viability.md).
