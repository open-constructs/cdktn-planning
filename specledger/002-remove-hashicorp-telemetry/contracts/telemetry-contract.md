# Contract: Usage Telemetry & Consent

**Feature**: `002-remove-hashicorp-telemetry` | **Date**: 2026-06-08

CLI-internal contracts (no network API surface). Defines the function signatures, config schema, and Sentry init contract the implementation must honor. Each contract clause maps to spec requirements and is the basis for unit tests.

## C1: `sendTelemetry` (new internal wrapper)

```ts
// packages/@cdktn/commons/src/telemetry.ts
export async function sendTelemetry(
  command: string,
  payload: { language?: string; [key: string]: unknown },
): Promise<void>;
// async, matching the legacy checkpoint signature — all 7 call sites
// already `await` it (FR-004 churn minimization)
```

**Contract**:
- MUST emit `Sentry.metrics.count("cli.command.invoked", 1, { attributes: { command, language?, ci } })` (v10 API).
- For synth timing, MUST also emit a duration metric (`cli.synth.duration`).
- MUST be a **silent no-op** when Sentry is not initialized (no throw, no I/O). [FR-002, SC-002/003]
- MUST NOT make any HTTP request to any HashiCorp endpoint. [FR-001, SC-001]
- Signature preserved from the old `(command, payload)` to minimize call-site churn. [FR-004]

## C2: Consent config schema (`cdktf.json`)

```ts
// packages/@cdktn/commons/src/config.ts — ConfigBase (additive)
interface ConfigBase {
  // …existing…
  readonly sendCrashReports?: boolean;     // existing semantics (crash/error)
  readonly sendUsageTelemetry?: boolean;   // NEW — usage analytics only
}
```

```ts
// packages/@cdktn/cli-core/src/lib/cdktf-config.ts — validated getter (per importExtension precedent)
get sendUsageTelemetry(): boolean | undefined;
```

**Contract**:
- `sendUsageTelemetry` independent of `sendCrashReports`. [FR-005, OS-002]
- The getter returns the raw `boolean | undefined`; it MUST NOT invent a default. The **consent-gating step** resolves the effective value (FR-017 precedence). [FR-005, finding-11]
- **Two readers by design (checkpoint finding #2)**: the typed `CdktfConfig.sendUsageTelemetry` getter is the validated surface for project-level consumers (throws `External` on malformed values; covered by `cli-core/src/test/cdktf-config.test.ts`). The consent-gating/emission path uses a forgiving raw reader in commons (`getUsageTelemetryConsent`) because commons cannot import cli-core and gating must work before/without a valid project (no `cdktf.json`, pre-validation init, `convert` outside a project — research Decision 8). A malformed value is treated as "not explicitly false" there, i.e. the legacy default applies.
- Sentry initialized iff `(sendCrashReports || effectiveSendUsageTelemetry) && SENTRY_DSN`. [FR-007]
- **Per-flag prompt**: each unset flag is prompted on first use only in an interactive terminal (`isInteractiveTerminal()` = `stdout.isTTY && !CI`), and persisted; a set flag is not re-prompted. [FR-008]
- **Non-interactive defaults** (no TTY / CI, no prompt): `sendUsageTelemetry` → **enabled** (legacy-preserving), `sendCrashReports` → **disabled**. [FR-016]
- Gating precedence: `CHECKPOINT_DISABLE` off > explicit value > interactive prompt > non-interactive default-on; emission also requires `SENTRY_DSN`. [FR-017]

## C3: `CHECKPOINT_DISABLE` override

**Contract**:
- When set, usage telemetry is suppressed regardless of `sendUsageTelemetry`. [FR-006, SC-003]
- MUST NOT affect `sendCrashReports`/crash reporting. [FR-006, edge cases]
- Retained in `environment.ts`; backward-compatible with the 13 CI workflow locations. [OS-001]

## C4: `Sentry.init` contract (v10)

```ts
Sentry.init({
  dsn: process.env.SENTRY_DSN,
  release: `cdktn-cli-${DISPLAY_VERSION}`,   // preserved — matches release.yml
  tracesSampleRate: 0,                       // NEW — CONFIRMED metrics deliver at 0 (spike 2026-06-10); zero trace quota; FR-015
  serverName: "cdktn-cli",                   // NEW — suppress auto-attached hostname (server.address) from metrics; privacy (FR-018)
  beforeSend,                                // preserved — drops "Usage Error"
});
// NOTE: enableLogs is NOT set — confirmed metrics do not require it (it governs Sentry.logger.* structured logs, omitted per YAGNI).
Sentry.getCurrentScope().setUser({ id: getUserId() });   // was Sentry.configureScope (removed v8)
Sentry.getCurrentScope().setTag("projectId", getProjectId());
```

**Contract**:
- Error/crash reporting behavior unchanged from the user's perspective. [FR-009, SC-004]
- `userId`/`projectId` scope tags preserved. [FR-009, FR-010]
- `release` tag unchanged so existing release/sourcemap pipeline keeps symbolicating. [Decision 7]
- `tracesSampleRate: 0` — **CONFIRMED** (spike: research/2026-06-10-v10-metrics-tracessamplerate-independence.md, `@sentry/node@10.57.0`): a `trace_metric` envelope is delivered with `flush()===true` at sample rate 0, so usage metrics are NOT dropped by trace sampling. `enableLogs` is not required for metrics and is omitted. [FR-015, FR-003, finding-8]
- `serverName: "cdktn-cli"` MUST be set: v10 otherwise auto-attaches `server.address` = the machine hostname to every metric (a data point the legacy HashiCorp transport never sent). [FR-018 — privacy]

## C5: Bounded flush on exit

**Contract**:
- Success path MUST `await Sentry.flush(timeout)` (timeout ≤ 4000ms) before process exit when reporting was active. [Decision 3]
- Flush MUST be bounded so telemetry can never hang the CLI. [Performance constraint]
- Error path retains existing `Sentry.close(4000)` (`cdktn.ts:184`). [unchanged]
- TEST (delivery oracle): use a **real v10 client + capturing custom `transport`** (`createTransport` from `@sentry/core`) and assert (a) a `trace_metric` envelope item with the expected name/attributes reached the transport AND (b) `await Sentry.flush(2000) === true` before exit. A pure `@sentry/node` jest mock proves only that the API was *called*, not that the metric survives to exit — reserve mocking for testing the `sendTelemetry` wrapper's gating in isolation. [Decision 4, FR-013; see research/2026-06-08-v10-e2e-validation.md]

## C6: Removal contract (no dead HashiCorp code)

**Contract** — after implementation, these MUST NOT exist as active code: [FR-011, FR-012, SC-007]
- `ReportRequest`, `ReportParams`, `post()`, `BASE_URL` (checkpoint.ts)
- `report()` (errors.ts)
- `checkpoint.test.ts`
- Any reference to `checkpoint-api.hashicorp.com` (copyright headers acceptable). [FR-001]
- `Errors.Internal/External/Usage` + Sentry scope integration MUST remain. [FR-012]
- `getUserId`/`getProjectId`/`getId`/`homeDir`, `uuid`, `ci-info` MUST remain. [FR-010, assumptions]
