# Phase 1 Data Model: Sentry Analytics Migration

**Feature**: `002-remove-hashicorp-telemetry` | **Date**: 2026-06-08

This feature is telemetry/config plumbing — no persistent domain entities. The "entities" are configuration flags, the runtime gating state, and the shape of an emitted usage-analytics event.

## Entity 1: Consent configuration (`cdktf.json`)

| Field | Type | Location | Default | Notes |
|-------|------|----------|---------|-------|
| `sendCrashReports` | `boolean \| undefined` | raw `cdktf.json` (loose access, unchanged) | undefined → prompt (non-CI) | Gates Sentry error/crash reporting. Existing. Read at `error-reporting.ts:23`. |
| `sendUsageTelemetry` | `boolean \| undefined` | **`ConfigBase`** (`config.ts:272-279`) + `CdktfConfig` getter | unset → prompt (interactive); non-interactive/CI → **enabled** (legacy, FR-016) | **NEW** (FR-005). Gates usage analytics independently. Typed pattern per `importExtension`. |
| `projectId` | `string` | `cdktf.json` | generated (uuid) | Preserved — Sentry scope tag. `getProjectId()`. |

**Validation rules**:
- Both flags independent (FR-006, OS-002). `CHECKPOINT_DISABLE` overrides `sendUsageTelemetry` → false, but never affects `sendCrashReports` (FR-006).
- Sentry initialized iff (`sendCrashReports` OR effective `sendUsageTelemetry`) AND `SENTRY_DSN` set (FR-007).
- **Per-flag interactive prompt** (FR-008): each unset flag is prompted on first use in an interactive terminal (`isInteractiveTerminal()` = `stdout.isTTY && !CI`) and persisted; a set flag is never re-prompted.
- **Non-interactive defaults differ** (FR-016): when no prompt can be shown (no TTY, or CI), `sendUsageTelemetry` defaults to **enabled** (legacy-preserving), `sendCrashReports` defaults to **disabled**.
- **Default-resolution layer** (resolves finding-11 ambiguity): the `CdktfConfig.sendUsageTelemetry` getter returns the raw `boolean | undefined`; the **consent-gating step** (not the getter) applies the FR-016/FR-017 precedence to derive the effective enabled/disabled state. The getter never invents a default.

## Entity 2: User/project identity (preserved)

| Field | Type | Location | Notes |
|-------|------|----------|-------|
| `userId` | `string` (uuidv4) | `~/.cdktf/config.json` | `getUserId()` — Sentry `scope.setUser({id})`. Relocated checkpoint.ts → `identity.ts`. |
| `projectId` | `string` (uuidv4) | `cdktf.json` | `getProjectId()` — Sentry `scope.setTag("projectId")`. |

State: created on first use (`getId()` writes if absent), then stable. Unchanged behavior.

## Entity 3: Usage analytics event (emitted, not stored)

Replaces the HashiCorp `ReportParams` POST body. Emitted as a Sentry v10 metric.

| Attribute | Type | Source | Example |
|-----------|------|--------|---------|
| metric name | string | fixed per event kind | `cli.command.invoked`, `cli.command.error`, `cli.synth.duration` |
| `command` | tag/attribute | call site | `synth`, `init`, `get`, `convert`, `watch`, `deploy` |
| `language` | tag/attribute | `cdktf.json` | `typescript`, `python`, `go`, `csharp`, `java` |
| `ci` | tag/attribute | `ci-info` | `github-actions` \| `false` |
| `value`/`duration` | number | timing (synth) | ms (distribution) |

**Emission rules**:
- Canonical names are defined by **FR-014**: `cli.command.invoked`, `cli.synth.duration`, `cli.command.error`. `cli.command.error` is a **usage** metric gated by `sendUsageTelemetry`/`CHECKPOINT_DISABLE` — distinct from crash reporting (FR-009); the two MUST NOT double-count the same event.
- Silent no-op when Sentry uninitialized (no DSN / opted out) (FR-002, assumptions).
- Delivered independently of `tracesSampleRate` — metrics MUST NOT be sampled out (FR-015).
- Emitted only when `sendUsageTelemetry` effective-true (gating, Entity 1).
- v10 API: `Sentry.metrics.count(name, value, { attributes: { command, language, ci } })`; timing as a distribution-style metric. Auto-correlated to `release: cdktn-cli-<version>` and (if within a span) trace/span IDs.

### Call-site map (7 sites → metric events)

| Call site (current) | Metric |
|---|---|
| `watch.ts:184` | `cli.command.invoked` {command:watch} |
| `synth-stack.ts:279` | `cli.command.invoked` {command:synth,language} + `cli.synth.duration` |
| `synth-stack.ts:294` | `cli.command.error` {command:synth} |
| `cdktf-project.ts:647` | `cli.command.invoked` {command,language} |
| `handlers.ts:169` | `cli.command.invoked` {command:convert} |
| `init.ts:287` | `cli.command.invoked` {command:init,language} |
| `get.tsx:63` | `cli.command.invoked` {command:get,language} |

## Entity 4: Reporting runtime state (in-memory, per-invocation)

| State | Derivation | Effect |
|-------|-----------|--------|
| `sentryInitialized` | DSN present AND (crash OR usage consent) | enables metrics + error capture |
| `usageEnabled` | effective `sendUsageTelemetry` (FR-017 precedence: `CHECKPOINT_DISABLE` off > explicit value > interactive prompt > non-interactive default **on**) AND NOT `CHECKPOINT_DISABLE` | gates metric emission |
| `flushPending` | any metric/event emitted this run | requires bounded flush before exit (Decision 3) |

**Lifecycle**: init (per command, `initializErrorReporting`) → emit (call sites) → **bounded flush on exit** (success: new teardown; error: existing `Sentry.close(4000)` at `cdktn.ts:184`).
