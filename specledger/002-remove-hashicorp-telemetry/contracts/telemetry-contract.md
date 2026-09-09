# Contract: Usage Telemetry & Consent

**Feature**: `002-remove-hashicorp-telemetry` | **Date**: 2026-06-08 | **Synced**: 2026-09-09 (review round 2 — C1 payload allow-list and metric catalogue, C2 single reader, C5 single flush helper + failure path, C6 removals)

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
- MUST be a **silent no-op** when usage telemetry is off or Sentry is not initialized (no throw, no I/O). [FR-002, SC-002/003]
- MUST NOT make any HTTP request to any HashiCorp endpoint. [FR-001, SC-001]
- Signature preserved from the old `(command, payload)` to minimize call-site churn. [FR-004]

**Base attributes** — computed once per call and carried by every metric this
function emits (`cli.error` excepted, see below): `command`, `ci` (the CI
provider name, else `false`), `os`, `arch`, `binary`, `binary_version` (only for
a recognised product), `target_terraform` / `target_opentofu` (declared ranges,
else the CLI defaults), `targets_declared`, `validate_installed_binary`, and
`language` when the payload's language is one of `LANGUAGES`. [FR-019, FR-021]

**Payload → attribute allow-list** — nothing else from the payload reaches a
metric. Every entry names the attribute *and* its expected type or value set;
a value of the wrong type or outside the set is dropped, not coerced:

| command | payload key | attribute | accepted |
|---|---|---|---|
| synth | `synthOrigin` | `synth_origin` | the known synth origins |
| init | `template` | `template` | string, already reduced to a built-in name or `remote` |
| init | `isRemote` | `is_remote` | boolean |
| convert | `numberOfModules` / `numberOfProviders` / `convertedLines` | `module_count` / `provider_count` / `converted_lines` | number |
| watch | `event` | `event` | the known watch events |

Arrays and objects are never serialized into attributes; the structured payload
keys (`targets`, `addedProviders`, `stackMetadata`, `requiredProviders`,
`failedStackCount`, `totalTime`, `error`/`errorType`) are consumed by the
handlers below and reduced to counts. [FR-021]

**Metrics emitted** — the catalogue is normative (FR-014):

| Metric | When | Attributes beyond the base set |
|---|---|---|
| `cli.command.invoked` | every successful command run | the allow-listed scalars above |
| `cli.command.error` | `payload.error` is set; returns without emitting anything else | `error_type` (validated against `COMMAND_ERROR_TYPES`, else `unexpected`) |
| `cli.synth.duration` | `payload.totalTime` is a number; distribution, unit millisecond | — |
| `cli.stack` | one per entry of `payload.stackMetadata` | `backend`, `cloud`, `override_count`, `import_count`, `moved_count`, `library_version` (release only) |
| `cli.stack.override` | one per key of that stack's `overrides` | `resource_type`, `override_count` |
| `cli.stack.provider` | one per entry of that stack's `required_providers` | `provider`, `binding`, `version_constraint` (when declared) |
| `cli.stack.failed` | `payload.failedStackCount > 0`; counted by that number | — |
| `cli.get.provider` / `cli.get.module` | one per `get` target, by type | `provider` / `module` (totals land on the command metric as `provider_count` / `module_count`) |
| `cli.init.provider` | one per `payload.addedProviders` entry | `provider` (total as `provider_count`) |

- A malformed entry inside a structured payload key MUST NOT prevent the run's
  command metric: entries are validated one by one, because a throw here is
  swallowed by `sendTelemetry`'s catch and would drop the whole run. [FR-021]
- Names, ids, addresses, paths and messages MUST NOT reach any attribute; the
  reduction happens here, not at the call sites (`SynthStack.telemetryPayload`
  is deliberately not the privacy boundary). [FR-020]

## C1b: `sendErrorTelemetry` (Errors factories)

```ts
// packages/@cdktn/commons/src/telemetry.ts
export function sendErrorTelemetry(type: string, command: string): void;
```

**Contract**:
- Called by every `Errors.Internal/External/Usage` factory, replacing the removed
  HashiCorp `report()`. [FR-012]
- Emits `cli.error` count 1 with attributes `{ type, command }` and **nothing
  else** — no base set, no message, no context values.
- `command` is the scope read **at call time** (`Errors.getScope()`), not bound
  when the factory is created.
- Usage-gated and silent on failure, like every other metric. Counts constructed
  errors, including handled `Usage` errors; `cli.command.error` counts failed
  runs. The two do not double-count. [FR-012, FR-014]

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
// packages/@cdktn/commons/src/telemetry.ts — the ONE reader
export function getUsageTelemetryConsent(projectPath?: string): boolean | undefined;
```

**Contract**:
- `sendUsageTelemetry` independent of `sendCrashReports`. [FR-005, OS-002]
- The reader returns the raw `boolean | undefined`; it MUST NOT invent a default. The **consent-gating step** (`isUsageTelemetryEnabled`) resolves the effective value (FR-017 precedence). [FR-005]
- **One reader (revised 2026-09-09)**: the forgiving raw reader in commons is the only reader. It never throws (telemetry must work outside a project), treats a malformed value as "not explicitly false", and accepts the strings `"true"`/`"false"` because init templates render booleans as strings. The typed `CdktfConfig.sendUsageTelemetry` getter this contract previously required — the "two readers by design" clause — is **removed**: zero production callers, and it parsed the same field differently from the reader that gates emission. `ConfigBase` keeps the field declaration. [FR-005]
- The decision, the project's target attributes and the project path are captured at command start (`initializErrorReporting`), because `convert` chdirs into a throwaway project and `init` reports for the project it just created. [FR-019]
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

```ts
// packages/@cdktn/commons/src/telemetry.ts — the ONE flush
export async function flushTelemetry(timeoutMs?: number): Promise<void>; // default 4000
```

**Contract**:
- Every exit path that may have emitted metrics MUST `await flushTelemetry()` before the process exits: the entrypoint success path, the entrypoint failure reporter, and the two synth paths that print and `process.exit(1)` themselves. [Decision 3, FR-022]
- `flushTelemetry` is the **only** caller of `Sentry.flush`/`Sentry.close` in the workspace; no other module imports them. [FR-022 — revised 2026-09-09]
- The flush MUST be bounded (≤ 4000 ms) and MUST swallow its own failure, so telemetry can never hang or mask a command. [Performance constraint]
- **Failure path** (absorbing PR #378, fixes #360/#361): the yargs `.fail()` handler stays synchronous and only records the failure; the recorded failure is then handled once by an awaited `reportFailure`, which prints (one line for `Usage`/`External`, message + stack + debug information otherwise), captures everything but `Usage`, emits the `cli.command.error` metric, and only then flushes — followed by a single `process.exit`. A synchronous handler throw that bypasses `.fail()` is caught by the same path. [FR-022]
- TEST (delivery oracle): use a **real v10 client + capturing custom `transport`** (`createTransport` from `@sentry/core`) and assert (a) a `trace_metric` envelope item with the expected name/attributes reached the transport AND (b) `await Sentry.flush(2000) === true` before exit. A pure `@sentry/node` jest mock proves only that the API was *called*, not that the metric survives to exit — reserve mocking for testing the `sendTelemetry` wrapper's gating in isolation. [Decision 4, FR-013; see research/2026-06-08-v10-e2e-validation.md]

## C6: Removal contract (no dead HashiCorp code)

**Contract** — after implementation, these MUST NOT exist as active code: [FR-011, FR-012, SC-007]
- `ReportRequest`, `ReportParams`, `post()`, `BASE_URL` (checkpoint.ts)
- `report()` (errors.ts)
- `checkpoint.test.ts` (it asserted `expect(scope.isDone)` — a function reference, always truthy — so nothing was lost with it)
- `CdktfConfig.sendUsageTelemetry` and its tests (removed 2026-09-09; see C2) [FR-005]
- The static source-scan egress test and the nock canary egress test (removed 2026-09-09: neither asserted anything the build and the E2E sink assertions do not) [SC-001]
- The jest wrapper around the bundle E2E (it could only ever skip; the script runs in CI on every build instead) [SC-009]
- Any reference to `checkpoint-api.hashicorp.com` (copyright headers acceptable). [FR-001]
- `Errors.Internal/External/Usage` + Sentry scope integration MUST remain. [FR-012]
- `getUserId`/`getProjectId`/`getId`/`homeDir`, `uuid`, `ci-info` MUST remain. [FR-010, assumptions]
