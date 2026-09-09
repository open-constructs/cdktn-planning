# Review round 2 (PR #62): restored usage signal, absorbed #378, one flush

**Feature**: `002-remove-hashicorp-telemetry` | **Date**: 2026-09-09

The June re-baseline left the branch with a working v10 transport and almost no
signal on it: the HashiCorp payload's per-stack contents were being received by
`sendTelemetry` and thrown away, the `Errors` factories reported nothing at all,
two of the "no HashiCorp egress" tests asserted nothing, and the bundle E2E was
a jest test that could only ever skip. This note records the decisions of the
second review round; the requirements they change are FR-005, FR-012, FR-014 and
the new FR-019 – FR-022 in spec.md.

## Decisions

### R1: stay on `@sentry/node` 10.x (10.73)
The metrics API used here (`Sentry.metrics.count` / `.distribution`) is the
current one and unchanged since the June spike; v11 is in beta and buys nothing
this feature needs. Pinned `^10.73.0` across `commons`, `cli-core` and
`cdktn-cli`. No `Sentry.init` option was added beyond the June contract.

### R2: the bundle E2E runs in CI instead of being a gated jest test
Reviewer position: *either run it regularly or don't add it*. A jest test that
skips unless a bundle happens to exist is the same as no test. `tools/validate-
sentry-e2e.sh` is now a build-workflow step that runs on **every** build: it
builds a **scratch** bundle (`bundle-e2e/`) with a local-sink DSN baked in by
esbuild, so the shipped bundle is never rewritten and no restore rebuild is
needed; the sink listens on a free port and prints it; the script polls the
sink's `/__items` until the expected items arrive rather than sleeping. The
jest wrapper is deleted. This also removed the need for the step to carry a
`SENTRY_DSN` secret.

### R3: one bounded flush helper
`flushTelemetry(timeoutMs)` in commons is the single bounded flush; the
entrypoint's success path, the entrypoint's failure reporter and the two
self-exiting synth paths all route through it. No module outside
`commons/src/telemetry.ts` calls `Sentry.flush`/`Sentry.close`. This answers the
reviewer's "at least 2 other spots doing something similar" directly and makes
the "flush duplicates" thread moot: there is one place to change the timeout.

### R4: absorb PR #378 (fixes #360, #361)
#378 rewrites the same yargs `.fail()` lines this branch touches for the
success-path flush, and it had already reserved a slot for the failed-command
metric before the flush. Landing it inside #62 avoids rebasing the same file
twice and lets the failure metric and the crash capture share one awaited path.
The cherry-pick keeps its author; the adaptation is a separate commit. #378's
tests come along and are the regression guards for the two fixed issues: the
`.fail` handler stays synchronous (yargs discards its return value, so an
`await` there races Node's unhandled-rejection reporter), the recorded failure
is handled once by an awaited `reportFailure`, and there is exactly one
`process.exit`. The E2E's crash trigger asserts the same end-to-end: the debug
block is reached and no `ERR_UNHANDLED_REJECTION` /
`PromiseRejectionHandledWarning` is printed.

### R5: the restored payload is per-item counts, never contents
The stack payload is reduced at emission, not at the call site: one `cli.stack`
per stack, one `cli.stack.override` per overridden resource type, one
`cli.stack.provider` per required provider, `cli.stack.failed` for the stacks
that did not complete, and one item per generated binding for `get`/`init`.
Imports and moves survive only as counts. `SynthStack.telemetryPayload` is
deliberately **not** the privacy boundary — it still carries stack names and
resource ids, and its test says so — because reducing there would hide the
reduction from the tests that matter.

### R6: one reader for the usage flag
The typed `CdktfConfig.sendUsageTelemetry` getter that FR-005 originally
required is removed (see the FR-005 revision note). Zero production callers, and
it parsed the same file differently from the reader that actually gates
emission. `ConfigBase` keeps the field.

### R7: `cli.command.error` has one emission point per failure
The entrypoint's failure reporter counts anything that reaches it. The two synth
paths that print and `process.exit(1)` themselves count their own failure
immediately before the bounded flush, because the reporter never sees them. The
earlier double count (synth-stack **and** the entrypoint, for one thrown error)
is gone.

## Privacy findings from the refutation rounds

Each was found by trying to make the CLI leak, then fixed:

1. **Private registry host and organization.** A `required_providers` entry
   sourced from `tfe.example.com/org/vault` sent the host and org verbatim.
   Fixed: only public-registry `namespace/type` is sent; any other host becomes
   `private-registry`, paths and malformed input `other`. The same reduction now
   covers module sources (`local` / `git` / `private-registry` / `other`).
2. **Remote template URL.** `cdktn init --template <url>` derived the template
   attribute from the URL. Fixed: a built-in template name, else the literal
   `remote`, through one mapping function.
3. **`SENTRY_*` environment values.** The SDK seeds environment from
   `SENTRY_ENVIRONMENT` and the trace from `SENTRY_TRACE`/`SENTRY_BAGGAGE`.
   Fixed: `environment` is pinned to the constant `"production"` in
   `Sentry.init`, and a fresh propagation context with a random trace id is set
   on the scope. The E2E exports all three as `LEAK-*` markers and asserts none
   of them reaches the sink.
4. **Free text reaching attributes.** Version-like and constraint-like values
   are user-authored: a locally built library, a wrapper's version line, a
   hand-edited constraint. Fixed by FR-021's validation — canonical range or
   `invalid`, release-only versions, enumerated backend kinds, the Terraform
   type grammar for resource types, and 64/128-character caps on the identities
   that are sent as-is.
5. **Unrecognised binaries.** `binary_version` is only sent when the probed
   product is `terraform` or `opentofu`; a wrapper's output is not a version.

## Test review verdicts

Two adversarial review passes (one per slice) produced 21 + 21 findings; both
were applied in full. The counts that matter:

- **Deleted as valueless**: the static source-scan egress test and the nock
  canary egress test (they asserted what a build failure already asserts); the
  jest bundle-E2E wrapper (could only skip); six `CdktfConfig` getter tests
  (with the getter); and roughly a dozen double-entry or tautological delivery
  cases folded into `it.each` tables. The deleted `checkpoint.test.ts` asserted
  `expect(scope.isDone)` — a function reference, always truthy — so no coverage
  was lost with it either.
- **Added because nothing covered them**: the init-time captures
  (`setUsageTelemetryEnabled` / `setProjectTargetAttributes`), the exact sorted
  attribute key set of `cli.command.invoked` in exactly one place, the failing
  `get` counting once through the entrypoint, the malformed `get`/`init` payload
  entries still yielding the command metric, and the raw-envelope privacy
  invariant (hostname, username, cwd, temp project dir).
- **Three internal edge-case tests kept deliberately**, each with a WHY comment:
  malformed stack metadata (a throw inside `sendStackTelemetry` is swallowed by
  `sendTelemetry`'s catch and would silently drop the whole run's command
  metric); the probe timeout (a hung or interactive `terraform version` must
  never delay a command; 1500 ms ceiling); and the unparsable synthesized
  content on the failure path (it is read from disk before the throw and must
  degrade to `{}` rather than take down deploy).

## Known gaps recorded, not fixed

- HCL-output stacks yield no `cli.stack.provider`: the CLI reads only the
  separate metadata file for them, so `required_providers` is not in hand.
- yargs pre-handler validation failures (invalid choice, unknown option) emit no
  metric — Sentry is initialized inside the command handlers. Same on main.
- `cmds/get.ts` reads the config at module import, so an invalid `cdktf.json`
  crashes before the failure reporter. Pre-existing; noted in #378.
- The bundled `@cdktn/hcl2cdk` loads a second copy of commons, whose error scope
  is never set: an `Errors.External` raised inside it counts `cli.error` with
  `command: "unknown"`. The binary probe is already shared across copies via
  `globalThis`; the scope is not.

## Asset pipeline

Whether this telemetry should grow to serve the asset-pipeline decision (#380 /
#371 / #339) was evaluated separately:
[2026-09-09-asset-pipeline-telemetry-evaluation.md](2026-09-09-asset-pipeline-telemetry-evaluation.md).
Conclusion: it contributes little, and the one candidate metric
(an allow-listed `cli.stack.resource`) is deferred as a follow-up.
