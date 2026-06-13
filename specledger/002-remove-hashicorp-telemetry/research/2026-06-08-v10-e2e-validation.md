# Research: End-to-end / integration validation of the Sentry v10 migration

**Date**: 2026-06-08
**Context**: The plan upgrades `@sentry/node` 7→10 and emits usage analytics via the new v10 metrics API, with a bounded flush on exit. Before implementing, we need a concrete, high-confidence local + CI verification path that proves: (a) zero HashiCorp egress, (b) usage metrics are actually delivered (constructed → serialized → flushed before the short-lived CLI exits), and (c) error reporting still works. Two research agents ran in parallel: one mapped the existing integration harness; one grounded in current Sentry v10 SDK docs for local-testing techniques.
**Time-box**: 45 minutes

## Question

How do we validate the v10 migration end-to-end with high confidence, given a short-lived CLI whose telemetry is the thing most likely to be silently dropped — and what local setup completes that with the existing test infrastructure?

## Findings

### Finding 1: The integration suite runs the REAL built bundle as a child process — nock cannot reach it (CONFIDENCE: high)

- `yarn integration` → `test/run-against-dist` publishes `dist/js/*.tgz` to Verdaccio, installs `cdktn-cli` into a temp staging dir, exports `TEST_PATH_CDKTF_CLI`, then runs jest (`test/run-against-dist:15-86`). Requires `yarn package` first (hard-fails without `dist/js`, `:28-32`).
- `TestDriver` (`test/test-helper.ts:69`) spawns the bare `cdktn` command **out-of-process** (`child_process.spawn(..., { shell: true, env: this.env })`, `:94-131`); the child inherits parent env + `addToEnv`/`setEnv` (`:86-91, 178-180`). `init()` always passes `--enable-crash-reporting=false` (`:224-227`).
- **Consequence**: `nock` (the repo's only HTTP-mock tool, v13.5.6) patches the *in-process* http stack and **cannot intercept the spawned bundle's traffic.** In-process nock tests and bundle E2E tests are therefore different mechanisms.

### Finding 2: `SENTRY_DSN` is esbuild-`define`-baked at BUILD time — runtime env won't redirect the bundle (CONFIDENCE: high)

- `build.ts:97`: `"process.env.SENTRY_DSN": JSON.stringify(process.env.SENTRY_DSN || "")` — the value is string-substituted into the bundle. The runtime guards in `error-reporting.ts:77,86` read the *already-inlined* literal.
- **Consequence**: to test Sentry delivery against the real bundle you must **build the bundle with a local-sink DSN** (`SENTRY_DSN=http://key@localhost:PORT/1 yarn package`); setting `SENTRY_DSN` in the child env at run time does nothing for those inlined reads. `CHECKPOINT_DISABLE` is the opposite — read at runtime (`checkpoint.ts:155`), so it can be flipped via `setEnv`.

### Finding 3: CI always sets `CHECKPOINT_DISABLE=1` for integration jobs (CONFIDENCE: high)

- `integration.yml:37,113,204` (and build/examples/release). The child inherits it, so HashiCorp egress is already suppressed in CI. **A no-egress assertion must explicitly UNSET `CHECKPOINT_DISABLE`** to be load-bearing — otherwise it passes trivially and proves nothing about the removal.

### Finding 4: Existing patterns to mirror (CONFIDENCE: high)

- **No-egress assertion**: `packages/@cdktn/cli-core/src/test/checkpoint.test.ts:35-44` — nock scope on `https://checkpoint-api.hashicorp.com` + `expect(scope.isDone()).toBeFalsy()`. Combine with the deny-all guard from `prebuilt-providers.test.ts:50-56` (`nock.disableNetConnect()` / `enableNetConnect()`).
- **Delivery assertion (current)**: `checkpoint.test.ts:46-54` (`.reply(201)` then assert it fired). ⚠️ Latent bug at `:53` — `scope.isDone` (function ref, always truthy) instead of `scope.isDone()`; do NOT copy the bug.
- This `checkpoint.test.ts` file is slated for deletion (it tests the removed HashiCorp path); its *structure* is the template for the replacement Sentry tests.

### Finding 5: v10 SDK gives a reliable in-process delivery oracle — the capturing custom transport (CONFIDENCE: high)

`Sentry.init({ transport })` accepts a `makeTransport` factory in v10. Using `createTransport` from `@sentry/core`, a test captures the exact serialized envelopes the SDK would ship — no DSN hit:

```ts
import * as Sentry from "@sentry/node";
import { createTransport } from "@sentry/core";

const sent: string[] = [];
Sentry.init({
  dsn: "https://public@example.invalid/1",   // well-formed, never reached
  enableMetrics: true,                        // default true in v10
  enableLogs: true,
  transport: (opts) => createTransport(opts, async (req) => {
    sent.push(String(req.body));              // serialized envelope
    return { statusCode: 200 };
  }),
});
```

- Envelope item **types**: errors=`event`, transactions=`transaction`, **metrics=`trace_metric`**, **logs=`log`**. A test asserts a metric shipped by finding a `trace_metric` item carrying the expected `name`/`value`/`attributes`.
- Alternative lighter spy: `beforeSendMetric: (m) => { seen.push(m); return m; }` (metrics have their own hook + buffer; they do NOT pass through `beforeSend`). Use this to assert "constructed"; use the transport to assert "would have shipped".

### Finding 6: Flush is the load-bearing correctness guarantee for a short-lived CLI (CONFIDENCE: high)

- v10 metrics & logs each have their **own buffer**, flushed on a size/time threshold (~100 items / ~5s). A CLI exits long before that → the metric is constructed but **silently never sent** without an explicit flush.
- `await Sentry.flush(timeout)` drains and resolves `true`/`false` (timed out); `Sentry.close(timeout)` drains then disables. Recommended CLI pattern: `flush()` then `close()` in a `finally`, bounded.
- **The delivery test must assert `await Sentry.flush(2000) === true` AND that a `trace_metric` item reached the transport** — a pure jest mock of `Sentry.metrics.count` proves only that your code called the API, not that it would survive to exit. This refines plan Decision 4 / contract C5.

### Finding 7: v10 metrics specifics / gotchas (CONFIDENCE: high)

- `Sentry.metrics.count/gauge/distribution` is **GA in 10.25.0+** (our 10.56 train) — NOT behind `_experiments`. `enableMetrics` **defaults true**; `enableMetrics:false` or `beforeSendMetric → null` silently drop. First things to check if a test sees nothing.
- `enableLogs` / `beforeSendLog` moved to **top-level** in v10 (were `_experiments` in v8/v9) — ensure init carries no stale `_experiments.enableLogs`.
- Metrics are gated by `enableMetrics`, not `tracesSampleRate`, so they emit even with tracing off — but trace linkage degrades without an active span. For deterministic CI assertions set `tracesSampleRate: 1.0` and optionally wrap emission in a span.

### Finding 8: Local human-in-the-loop options (CONFIDENCE: high; metrics-in-Spotlight-UI: medium)

- **Spotlight**: `Sentry.init({ spotlight: true })` (or `spotlightIntegration({ sidecarUrl: "http://localhost:8969/stream" })` for Node), run `npx @spotlightjs/spotlight` (UI/ingest on :8969). Surfaces errors, traces, logs, profiling; the new `trace_metric` items reach the sidecar even if the UI lags on rendering them.
- **Local mock DSN server**: point DSN at a local HTTP server accepting `POST /api/<project>/envelope/` → 200. Equivalent to the custom transport but heavier (process/port).
- **`debug: true`**: logs what the SDK would send — eyeball aid, not an assertable artifact.

## Decisions

- **D1**: Validation is **layered**: (L1) fast in-process unit tests with a real v10 client + capturing transport; (L2) in-process no-egress nock tests; (L3) one bundle-level E2E delivery+egress test; (L4) manual Spotlight pass. CI runs L1+L2 always; L3 as an opt-in/dedicated job; L4 is one-time human verification.
- **D2**: The **delivery oracle is the capturing custom transport asserting a `trace_metric` envelope + `flush()===true`**, not a jest mock. Mock `@sentry/node` only to unit-test the `sendTelemetry` wrapper's branching/gating in isolation.
- **D3**: The **no-egress test must run with `CHECKPOINT_DISABLE` unset** (Finding 3), asserting nothing reaches `checkpoint-api.hashicorp.com` *because the code path is gone*, not because the kill-switch is on. Fix the `scope.isDone()` bug when porting the pattern.
- **D4**: The **bundle E2E** (L3) requires a purpose-built bundle: `SENTRY_DSN=http://key@localhost:PORT/1 yarn package`, a jest-spawned local envelope-recording server, `TestDriver` with `CHECKPOINT_DISABLE` unset, a deliberately-failing command (triggers `Sentry.close(4000)` at `cdktn.ts:184`) to prove error delivery + a normal command to prove the new exit flush delivers a metric. Document it as the high-confidence E2E but keep it isolated (heavier, needs the special build).

## Recommendations (local verification path — concrete)

1. **L1 — unit (`packages/@cdktn/commons/src/test/telemetry.test.ts`, new)**: real v10 client + `createTransport` capturing transport.
   - `sendTelemetry("synth", { language: "typescript" })` → assert a `trace_metric` envelope with `cli.command.invoked`, attributes `{command:"synth", language:"typescript", ci}`.
   - assert `await Sentry.flush(2000) === true` (delivery-before-exit).
   - gating: with `enableMetrics:false` / Sentry uninitialized → no `trace_metric`; with `CHECKPOINT_DISABLE` set / `sendUsageTelemetry:false` → no emission.
2. **L2 — no-egress unit**: nock `disableNetConnect()` + scope on the HashiCorp host; exercise `Errors.Internal(...)` and command paths with `CHECKPOINT_DISABLE` unset; assert `scope.isDone()` is false. Replaces `checkpoint.test.ts`.
3. **L3 — bundle E2E (dedicated)**: build with local-sink DSN; jest spins a tiny `http` server recording envelope POSTs; `TestDriver(..., { CHECKPOINT_DISABLE: "" })`; run `cdktn synth` (assert a `trace_metric` envelope arrives → proves the exit-flush works in the real bundle) and a failing command (assert an `event` envelope arrives). Also assert zero connections attempted to `checkpoint-api.hashicorp.com` (no nock in child → use the local server as the only allowed sink + inspect that nothing else was dialed, or run behind a recording `HTTPS_PROXY`).
4. **L4 — manual**: local dev build with `spotlight: true` (dev-gated) + `npx @spotlightjs/spotlight`; run real commands; confirm metric/trace/error appear. `debug:true` as fallback. One-time, pre-merge.
5. Fold D2 into plan **contract C5** (prefer capturing-transport over mock for the delivery assertion) and **quickstart J2**.

## References

- Existing harness: `test/test-helper.ts:69,85-131,224-227`; `test/run-against-dist:15-86`; `test/jest.config.js`; `packages/@cdktn/cli-core/src/test/checkpoint.test.ts:16-54`; `prebuilt-providers.test.ts:45-62`; `packages/cdktn-cli/build.ts:96-98`; `packages/cdktn-cli/src/bin/cdktn.ts:184`
- Sentry transports (custom transport / `createTransport`): https://docs.sentry.io/platforms/javascript/configuration/transports/
- Sentry Node metrics (GA 10.25+, `enableMetrics`): https://docs.sentry.io/platforms/javascript/guides/node/metrics/
- Metrics/logs SDK telemetry spec (`trace_metric`/`log` envelope items): https://develop.sentry.dev/sdk/telemetry/metrics/ , https://develop.sentry.dev/sdk/telemetry/logs/
- Flush/close (draining) on short-lived processes: https://docs.sentry.io/platforms/node/configuration/draining/
- Filtering hooks (`beforeSendMetric`/`beforeSendLog`): https://docs.sentry.io/platforms/javascript/configuration/filtering/
- v9→v10 migration (enableLogs/beforeSendLog top-level): https://docs.sentry.io/platforms/javascript/guides/node/migration/v9-to-v10/
- Spotlight local debugging: https://spotlightjs.com/ , https://spotlightjs.com/docs/about/
- Related: `research/2026-06-08-sentry-metrics-transport-viability.md`, `research/2026-06-07-build-release-sentry-injection.md`, `quickstart.md`, `contracts/telemetry-contract.md`
