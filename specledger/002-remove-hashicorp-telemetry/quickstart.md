# Quickstart: Verifying the Sentry Analytics Migration

**Feature**: `002-remove-hashicorp-telemetry` | **Date**: 2026-06-08 | **Synced**: 2026-09-09 (review round 2)

Per constitution VIII, every step below MUST be translatable into an integration/unit test scenario. Each maps to acceptance scenarios in spec.md.

## Journey 1: No HashiCorp egress (US1 → SC-001)

```bash
# Run any CLI command and assert no outbound call to checkpoint-api.hashicorp.com
cdktn synth
```
**Expected**: command succeeds; zero HTTP requests to `checkpoint-api.hashicorp.com` (or any HashiCorp host).
**Test (2026-09-09)**: the delivery oracle (real client + capturing transport) shows where the data *does* go, and the CI bundle E2E (Journey 6) asserts against a local sink that the bundle talks to the configured DSN and nothing else, plus a free `grep` of the built bundle for the endpoint. The two dedicated egress tests that used to stand here — the nock canary (`cli-core/src/test/no-hashicorp-runtime-egress.test.ts`) and the static source scan (`cdktn-cli/src/test/no-hashicorp-egress.test.ts`) — were **removed**: neither asserted anything the build and the sink assertions do not. [maps US1 scenarios 1-3]

## Journey 2: Usage metrics emitted via Sentry when opted in (US2 → SC-002)

```jsonc
// cdktf.json
{ "sendUsageTelemetry": true }
```
```bash
SENTRY_DSN=<dsn> cdktn synth   # CHECKPOINT_DISABLE unset
```
**Expected**: a `cli.command.invoked` metric and a `cli.synth.duration` metric, each carrying the full base attribute set (`command`, `ci`, `os`, `arch`, `binary`, `binary_version`, `target_terraform`, `target_opentofu`, `targets_declared`, `validate_installed_binary`, `language`), plus one `cli.stack` per synthesized stack with `cli.stack.override` / `cli.stack.provider` items — all **flushed before exit**.
**Test (unit, real client + capturing transport)**: init a real v10 client with a `createTransport` capturing transport; assert the **exact sorted attribute key set** of `cli.command.invoked` in one place (so adding an attribute fails deliberately), assert the per-stack items and their attributes, assert `sentry.release` is stamped, and assert `await Sentry.flush(2000) === true`. [maps US2 scenarios 1,4; FR-014/FR-019/FR-020; Decision 3-4]
**Test (E2E, optional)**: build bundle with `SENTRY_DSN=http://key@localhost:PORT/1`, spawn via `TestDriver` with `CHECKPOINT_DISABLE` unset, run `cdktn synth`, assert a local envelope-recording server received a `trace_metric` item.

## Journey 3: Usage metrics suppressed (US2 → SC-003)

```bash
# (a) explicit opt-out
echo '{ "sendUsageTelemetry": false }' >> cdktf.json && SENTRY_DSN=<dsn> cdktn synth
# (b) env override
SENTRY_DSN=<dsn> CHECKPOINT_DISABLE=1 cdktn synth   # even with sendUsageTelemetry:true
```
**Expected**: no usage metrics emitted in either case.
**Test (unit)**: assert `Sentry.metrics.count` NOT called when `sendUsageTelemetry:false`, and NOT called when `CHECKPOINT_DISABLE` set regardless of flag. [maps US2 scenarios 2,3; FR-006]

## Journey 4: Crash reporting still works, independent of usage telemetry (US3 → SC-004)

```bash
# crash reporting on, usage telemetry off
echo '{ "sendCrashReports": true, "sendUsageTelemetry": false }' > cdktf.json
SENTRY_DSN=<dsn> cdktn <command-that-throws-internal-error>
```
**Expected**: the internal error is reported to Sentry (scope has userId + projectId); usage metrics still suppressed.
**Test**: unit — Sentry initialized when only `sendCrashReports` true; `getCurrentScope().setUser/​setTag` invoked; error captured. [maps US3 scenarios 1-3; FR-009/010]

## Journey 5: Silent no-op without DSN (edge case)

```bash
# no SENTRY_DSN (typical local/dev/fork build)
cdktn synth
```
**Expected**: no Sentry init, `sendTelemetry` calls are silent no-ops, no errors, command succeeds.
**Test**: unit — with Sentry uninitialized, `sendTelemetry` does not throw and emits nothing. [maps FR-002 assumptions]

## Journey 6: Bundle E2E — delivery, per-stack metrics and the failure path against the real bundle

```bash
tools/validate-sentry-e2e.sh      # local; the same script CI runs on every build
```
The script starts `tools/sentry-sink.mjs` on a free port, builds a **scratch**
bundle (`packages/cdktn-cli/bundle-e2e/`) with a local-sink DSN baked in by
esbuild — the shipped bundle is never touched — and then exercises four
triggers in throwaway projects with `CHECKPOINT_DISABLE` unset and
`SENTRY_ENVIRONMENT` / `SENTRY_TRACE` / `SENTRY_BAGGAGE` exported as `LEAK-*`
markers:

| Trigger | Proves |
|---|---|
| `cdktn convert` from stdin | the success-path flush (an empty sink means it is missing or broken) |
| `cdktn synth --app "node -e 'process.exit(1)'"` | the error path: `cli.command.error` with `error_type` |
| `cdktn synth` over a hand-written stack (secret stack name, imported id, private-registry provider, local provider path) | `cli.stack`, `cli.stack.override`, `cli.stack.provider` with `binding` / `library_version` / counts, and the reductions |
| `cdktn output --skip-synth` over a corrupt `cdk.tf.json` | the entrypoint failure path: a crash event, an `unexpected` `cli.command.error`, the debug-information block, and no orphaned rejection |

**Expected**: the sink records the metric items above and a crash `event`;
`sentry.environment` is the constant `production`; none of the `LEAK-*` markers,
the stack name, the resource id, the private-registry host/org or the local
provider path appears in the raw envelope bytes; and the bundle contains zero
references to `checkpoint-api.hashicorp.com` (free, not the point).
**Test**: the script itself, as a step in the `build-and-package` job — it runs
on **every build**, not behind a gate. [maps US2 delivery, SC-002/005/007/009/010]

## Journey 7: Consent prompt & upgrade defaults (US5 → SC-008, FR-008/FR-016/FR-017)

```bash
# (a) existing project, interactive terminal: crash already set, usage unset → prompt ONCE for usage
printf '{ "language":"typescript", "sendCrashReports":true }' > cdktf.json
SENTRY_DSN=<dsn> cdktn synth            # TTY, not CI → usage-telemetry prompt shown; persisted to cdktf.json
# (b) non-interactive (piped) OR CI, usage unset → NO prompt, usage telemetry defaults ON (legacy-preserving)
SENTRY_DSN=<dsn> cdktn synth < /dev/null    # no TTY → no prompt; metric emitted (CHECKPOINT_DISABLE unset)
```
**Expected**: (a) the user is prompted once for usage telemetry (and `sendCrashReports` is NOT re-asked), the decision is written to `cdktf.json`; (b) no prompt is shown and a `cli.command.invoked` metric is still emitted (default-on), routed to the project's Sentry.
**Test (unit)**: mock `isInteractiveTerminal()` / `process.stdout.isTTY` / `process.env.CI` and the inquirer `confirm`:
- interactive + `sendUsageTelemetry` unset → `confirm` called once; `persist…` writes the answer; `sendCrashReports` not re-prompted. [US5 scenario 1; FR-008]
- non-interactive (no TTY) or CI + unset → `confirm` NOT called; effective usage telemetry = enabled → `Sentry.metrics.count` emitted when DSN set & `CHECKPOINT_DISABLE` unset. [US5 scenario 2; FR-016]
- `CHECKPOINT_DISABLE` set or `sendUsageTelemetry:false` → no prompt, no emission. [US5 scenario 3; FR-017]
- `cdktn init` (interactive, both unset) → both flags prompted (presentation MAY be consolidated) and persisted. [US5 scenario 4]

## Journey 8: One failure path, one flush (FR-022, absorbed #378 — fixes #360/#361)

```bash
# unexpected internal error: corrupt synthesized stack read with --skip-synth
cdktn output --skip-synth
# usage error: an unknown option / invalid choice reaching yargs' .fail
cdktn synth --nope
```
**Expected**: the message (and, for an unexpected error, the stack and the
"Debug Information:" block) is printed **once**; exactly one
`cli.command.error` is emitted, with `error_type` matching the class of the
thrown value; the metric is emitted **before** the bounded flush; the process
exits 1 exactly once; and no `ERR_UNHANDLED_REJECTION` or
`PromiseRejectionHandledWarning` is printed.
**Test**: unit tests over `runCli`/`reportFailure` with injected deps (print /
capture / metric / flush order, one exit, synchronous `.fail`, a synchronous
handler throw that bypasses `.fail`), plus the E2E crash trigger in Journey 6.
[maps FR-022; regression guards for #360/#361]

> Release sourcemap sanity (Decision 7): `SENTRY_DSN=<dsn> pnpm build && pnpm package`; a deliberately-triggered error in a release build must show un-minified frames in Sentry — if not, switch release.yml to `sentry-cli sourcemaps inject`+`upload` (keep sentry-cli 2.58.4). One-time manual dashboard check.

---

### Coverage matrix

| Journey | User Story | Success Criteria | Test layer |
|---------|-----------|------------------|-----------|
| 1 | US1 | SC-001 | unit (delivery oracle) + bundle E2E |
| 2 | US2 | SC-002, SC-005 | unit (emission + flush) |
| 3 | US2 | SC-003 | unit (gating) |
| 4 | US3 | SC-004 | unit |
| 5 | — (edge) | — | unit |
| 6 | US2/US3/build | SC-002/005/006/007/009/010 | bundle E2E script, run on every CI build |
| 7 | US5 | SC-008 | unit (prompt + non-interactive default gating) |
| 8 | US3 (FR-022) | SC-005 | unit (runCli/reportFailure) + Journey 6 crash trigger |
