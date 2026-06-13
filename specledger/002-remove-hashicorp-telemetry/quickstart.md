# Quickstart: Verifying the Sentry Analytics Migration

**Feature**: `002-remove-hashicorp-telemetry` | **Date**: 2026-06-08

Per constitution VIII, every step below MUST be translatable into an integration/unit test scenario. Each maps to acceptance scenarios in spec.md.

## Journey 1: No HashiCorp egress (US1 → SC-001)

```bash
# Run any CLI command and assert no outbound call to checkpoint-api.hashicorp.com
cdktn synth
```
**Expected**: command succeeds; zero HTTP requests to `checkpoint-api.hashicorp.com` (or any HashiCorp host).
**Test (two layers)**: (a) unit, `cli-core/src/test/no-hashicorp-runtime-egress.test.ts` — `nock.disableNetConnect()` + a HashiCorp canary interceptor; exercises sendTelemetry/Errors factories/init+flush with the real `@sentry/node` and asserts the canary is never hit; (b) static, `cdktn-cli/src/test/no-hashicorp-egress.test.ts` — scans every workspace source file and the built bundle for the endpoint. [maps US1 scenarios 1-3]

## Journey 2: Usage metrics emitted via Sentry when opted in (US2 → SC-002)

```jsonc
// cdktf.json
{ "sendUsageTelemetry": true }
```
```bash
SENTRY_DSN=<dsn> cdktn synth   # CHECKPOINT_DISABLE unset
```
**Expected**: a `cli.command.invoked` metric (attributes: command=synth, language, ci) and a `cli.synth.duration` metric are emitted to Sentry, then **flushed before exit**.
**Test (unit, real client + capturing transport)**: init a real v10 client with a `createTransport` capturing transport; assert a `trace_metric` envelope item carries `cli.command.invoked` + attributes `{command:"synth", …}`, and assert `await Sentry.flush(2000) === true` (delivered before exit). [maps US2 scenarios 1,4; Decision 3-4; research/2026-06-08-v10-e2e-validation.md]
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

## Journey 6: Local bundle E2E — delivery + flush against the real bundle (full recipe: [research/2026-06-10-bundle-e2e-validation-recipe.md](research/2026-06-10-bundle-e2e-validation-recipe.md))

```bash
# 1. start a local Sentry sink (records envelope item types: event/transaction/trace_metric)
node tools/sentry-sink.mjs 9999
# 2. build the bundle with a local-sink DSN baked in (esbuild define)
SENTRY_DSN="http://localkey@localhost:9999/1" pnpm nx run cdktn-cli:build
# 3. telemetry-enabled workdir, CHECKPOINT_DISABLE cleared
WORK=$(mktemp -d); cd "$WORK"; unset CHECKPOINT_DISABLE
printf '{ "language":"typescript", "sendCrashReports":true, "sendUsageTelemetry":true }' > cdktf.json
CDKTN=.../packages/cdktn-cli/bundle/bin/cdktn
# 4a. SUCCESS trigger — isolates the NEW bounded success-path flush (dependency-free)
echo 'resource "null_resource" "x" {}' | "$CDKTN" convert --language typescript
# 4b. ERROR trigger — proves DSN bake + sink + flush plumbing (works on current bundle too)
"$CDKTN" synth --app "node -e 'process.exit(1)'" || true
```
**Expected**: sink records a `trace_metric` item `cli.command.invoked` (command=convert) from 4a — **empty sink ⇒ the success-path flush is missing/broken**; and an `event` (+ `cli.command.error` metric) from 4b. Then `grep -c checkpoint-api.hashicorp.com packages/cdktn-cli/bundle/bin/cdktn` is 0.
**Test**: standalone local script today; gated CI jest test that builds with a local DSN, spawns `bundle/bin/cdktn convert`, asserts a `trace_metric` envelope + exit 0. [maps US2 delivery, SC-002/005/007; Decision 7 sourcemap check folded into the release sanity below]

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

> Release sourcemap sanity (Decision 7): `SENTRY_DSN=<dsn> pnpm build && pnpm package`; a deliberately-triggered error in a release build must show un-minified frames in Sentry — if not, switch release.yml to `sentry-cli sourcemaps inject`+`upload` (keep sentry-cli 2.58.4). One-time manual dashboard check.

---

### Coverage matrix

| Journey | User Story | Success Criteria | Test layer |
|---------|-----------|------------------|-----------|
| 1 | US1 | SC-001 | integration |
| 2 | US2 | SC-002, SC-005 | unit (emission + flush) |
| 3 | US2 | SC-003 | unit (gating) |
| 4 | US3 | SC-004 | unit |
| 5 | — (edge) | — | unit |
| 6 | US2/US3/build | SC-002/005/006/007 | local script + gated CI jest (bundle E2E) |
| 7 | US5 | SC-008 | unit (prompt + non-interactive default gating) |
