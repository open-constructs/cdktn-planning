# Phase 1 Data Model: Sentry Analytics Migration

**Feature**: `002-remove-hashicorp-telemetry` | **Date**: 2026-06-08 | **Synced**: 2026-09-09 (review round 2)

This feature is telemetry/config plumbing — no persistent domain entities. The "entities" are configuration flags, the runtime gating state, and the shape of an emitted usage-analytics event.

## Entity 1: Consent configuration (`cdktf.json`)

| Field | Type | Location | Default | Notes |
|-------|------|----------|---------|-------|
| `sendCrashReports` | `boolean \| undefined` | raw `cdktf.json` (loose access, unchanged) | undefined → prompt (non-CI) | Gates Sentry error/crash reporting. Existing. Read at `error-reporting.ts:23`. |
| `sendUsageTelemetry` | `boolean \| undefined` | declared on **`ConfigBase`**; read only by `getUsageTelemetryConsent` in commons | unset → prompt (interactive); non-interactive/CI → **enabled** (legacy, FR-016) | **NEW** (FR-005). Gates usage analytics independently. One reader; the typed `CdktfConfig` getter was removed 2026-09-09. |
| `projectId` | `string` | `cdktf.json` | generated (uuid) | Preserved — Sentry scope tag. `getProjectId()`. |

**Validation rules**:
- Both flags independent (FR-006, OS-002). `CHECKPOINT_DISABLE` overrides `sendUsageTelemetry` → false, but never affects `sendCrashReports` (FR-006).
- Sentry initialized iff (`sendCrashReports` OR effective `sendUsageTelemetry`) AND `SENTRY_DSN` set (FR-007).
- **Per-flag interactive prompt** (FR-008): each unset flag is prompted on first use in an interactive terminal (`isInteractiveTerminal()` = `stdout.isTTY && !CI`) and persisted; a set flag is never re-prompted.
- **Non-interactive defaults differ** (FR-016): when no prompt can be shown (no TTY, or CI), `sendUsageTelemetry` defaults to **enabled** (legacy-preserving), `sendCrashReports` defaults to **disabled**.
- **Default-resolution layer**: `getUsageTelemetryConsent` returns the raw `boolean | undefined` (and never throws); the **consent-gating step** `isUsageTelemetryEnabled` applies the FR-016/FR-017 precedence to derive the effective state. The reader never invents a default.
- **Captured at command start**: `initializErrorReporting` resolves the decision and the project's target attributes for the project path that applies (the cwd for every command, the freshly created project for `init`), because `convert` chdirs into a throwaway project before emitting.

## Entity 2: User/project identity (preserved)

| Field | Type | Location | Notes |
|-------|------|----------|-------|
| `userId` | `string` (uuidv4) | `~/.cdktf/config.json` | `getUserId()` — Sentry `scope.setUser({id})`. Relocated checkpoint.ts → `identity.ts`. |
| `projectId` | `string` (uuidv4) | `cdktf.json` | `getProjectId()` — Sentry `scope.setTag("projectId")`. |

State: created on first use (`getId()` writes if absent), then stable. Unchanged behavior.

## Entity 3: Usage analytics event (emitted, not stored)

Replaces the HashiCorp `ReportParams` POST body. Emitted as Sentry v10 metrics.
Everything below is enumerated or validated before it becomes an attribute
(FR-021); nothing is forwarded because it happens to be a scalar.

### Base attribute set (every metric except `cli.error`)

| Attribute | Type | Source | Example |
|-----------|------|--------|---------|
| `command` | string | the CLI command; the `Errors` scope on the failure path | `synth`, `init`, `get`, `convert`, `watch`, `deploy` |
| `ci` | string \| false | `ci-info` | `github-actions` \| `false` |
| `os` / `arch` | string | `process.platform` / `process.arch` | `darwin` / `arm64` |
| `binary` | enum | one lazy process-global probe, 1500 ms ceiling | `terraform`, `opentofu`, `unknown`, `missing` |
| `binary_version` | string | the probe, release only, recognised products only | `1.12.6` |
| `target_terraform` / `target_opentofu` | string | `cdktf.json` `targetVersions`, else the CLI defaults; canonical range or `invalid` | `>=1.9.0` |
| `targets_declared` | boolean | a `targetVersions` block exists | `true` |
| `validate_installed_binary` | boolean | `cdktf.json` flag | `false` |
| `language` | enum | `cdktf.json` / command argument, must be one of `LANGUAGES` | `typescript` |

### Metrics

| Metric | Kind | Attributes beyond the base set |
|---|---|---|
| `cli.command.invoked` | count 1 | the per-command allow-listed scalars (contract C1) |
| `cli.command.error` | count 1 | `error_type` ∈ `Usage`, `External`, `Internal`, `unexpected` |
| `cli.synth.duration` | distribution (ms) | — |
| `cli.stack` | count 1 per stack | `backend`, `cloud`, `override_count`, `import_count`, `moved_count`, `library_version` |
| `cli.stack.override` | count 1 per resource type | `resource_type`, `override_count` |
| `cli.stack.provider` | count 1 per required provider | `provider`, `binding`, `version_constraint` |
| `cli.stack.failed` | count = failed stacks | — |
| `cli.get.provider` / `cli.get.module` | count 1 per binding | `provider` / `module` |
| `cli.init.provider` | count 1 per provider | `provider` |
| `cli.error` | count 1 per constructed error | `type`, `command` — **and nothing else** |

### Fields stamped by the SDK (not attributes of ours)

`user.id` (the persistent random uuid from `~/.cdktf/config.json`),
`sentry.release` = `cdktn-cli-<version>` (which is why the CLI version needs no
attribute), `sentry.environment` = the constant `"production"`,
`sentry.sdk.name`/`version`, `server.address` = the constant `"cdktn-cli"`, a
per-process monotonic sequence, a random per-process `trace_id`, and the
emission timestamp. One session item per process carries the Node **major**
version as its user agent. No value from a `SENTRY_*` environment variable is
used. [FR-018, FR-021]

**Emission rules**:
- The canonical catalogue is defined by **FR-014**; `cli.command.error` and `cli.error` are usage metrics gated by `sendUsageTelemetry`/`CHECKPOINT_DISABLE`, distinct from crash reporting (FR-009). `cli.error` counts constructed errors, `cli.command.error` counts failed runs; neither double-counts the other.
- Silent no-op when usage telemetry is off or Sentry is uninitialized (no DSN / opted out) (FR-002, assumptions).
- Delivered independently of `tracesSampleRate` — metrics MUST NOT be sampled out (FR-015).
- A malformed payload entry is skipped; it never costs the run its command metric (FR-021).

### Call-site map (call site → metrics)

| Call site | Metrics |
|---|---|
| `watch.ts` (`sendTelemetry("watch")`) | `cli.command.invoked` {command:watch, event} |
| `synth-stack.ts` `synthTelemetry` | `cli.command.invoked` + `cli.synth.duration` + `cli.stack` / `cli.stack.override` / `cli.stack.provider` |
| `synth-stack.ts` `synthErrorTelemetry` (the two self-exiting paths only) | `cli.command.error` |
| `cdktf-project.ts` (diff/deploy/destroy, one shared helper) | `cli.command.invoked` + the `cli.stack*` family + `cli.stack.failed` |
| `cmds/handlers.ts` (convert) | `cli.command.invoked` {command:convert, module_count, provider_count, converted_lines} |
| `cmds/helper/init.ts` | `cli.command.invoked` {command:init, template, is_remote, provider_count} + `cli.init.provider` |
| `cmds/ui/get.ts` | `cli.command.invoked` {command:get, provider_count, module_count} + `cli.get.provider` / `cli.get.module` |
| `bin/error-handling.ts` `reportFailure` (the entrypoint failure path) | `cli.command.error` |
| `commons/errors.ts` `Errors.*` factories | `cli.error` |

## Entity 4: Reporting runtime state (in-memory, per-invocation)

| State | Derivation | Effect |
|-------|-----------|--------|
| `sentryInitialized` | DSN present AND (crash OR usage consent) | enables metrics + error capture |
| `usageEnabled` | effective `sendUsageTelemetry` (FR-017 precedence: `CHECKPOINT_DISABLE` off > explicit value > interactive prompt > non-interactive default **on**) AND NOT `CHECKPOINT_DISABLE` | gates metric emission |
| `flushPending` | any metric/event emitted this run | requires bounded flush before exit (Decision 3) |

**Lifecycle**: init (per command, `initializErrorReporting`; for `init`, against the project it just created) → emit (call sites) → **one bounded flush on exit** through `flushTelemetry` — the entrypoint success path, the entrypoint failure reporter (after the `cli.command.error` metric, before the single `process.exit`) and the two self-exiting synth paths. No other module calls `Sentry.flush`/`Sentry.close`. [FR-022]
