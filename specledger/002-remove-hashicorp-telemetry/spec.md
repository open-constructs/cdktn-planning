# Feature Specification: Replace HashiCorp Telemetry with Sentry Analytics

**Feature Branch**: `002-remove-hashicorp-telemetry`
**Created**: 2026-03-20
**Re-validated**: 2026-06-07 (against current `main` after rebase — see [revalidation note](research/2026-06-07-revalidation-against-main.md))
**Re-baselined**: 2026-06-10 (transport decision D1 — the `@sentry/node` 7.x custom-metrics product was sunset server-side; upgraded to v10. This supersedes the original `7.120.4` framing throughout the spec. See [transport-viability spike](research/2026-06-08-sentry-metrics-transport-viability.md).)
**Status**: Draft
**Input**: GitHub Issue #48 - cdktn-cli telemetry uses HashiCorp's endpoint
**Issue**: https://github.com/open-constructs/cdk-terrain/issues/48

## User Scenarios & Testing *(mandatory)*

### User Story 1 - CLI stops sending data to HashiCorp (Priority: P1)

As a cdktn user, I want the CLI to not send any data to HashiCorp's checkpoint API, so that my usage data is not shared with an unrelated third party and the CLI does not depend on HashiCorp infrastructure.

**Why this priority**: This is the core ask of the issue. The cdktn project has forked from cdktf, and the checkpoint module still sends telemetry and error reports to `checkpoint-api.hashicorp.com`. This is a privacy concern and an operational dependency on infrastructure the project does not control.

**Independent Test**: Can be fully tested by running any CLI command (e.g., `cdktn synth`) and verifying no outbound HTTP requests are made to `checkpoint-api.hashicorp.com`. Delivers immediate value by removing the external dependency.

**Acceptance Scenarios**:

1. **Given** a user runs any cdktn CLI command, **When** the command executes, **Then** no HTTP requests are made to `checkpoint-api.hashicorp.com` or any other HashiCorp-owned endpoint.
2. **Given** a user has not set `CHECKPOINT_DISABLE`, **When** they run a cdktn CLI command, **Then** no data is sent to HashiCorp.
3. **Given** a user upgrades from a previous cdktn version, **When** they run CLI commands, **Then** behavior is identical except no HashiCorp calls are made.

---

### User Story 2 - Usage analytics are preserved via Sentry (Priority: P1)

As a project maintainer, I want usage telemetry (which commands are run, which languages are used, synth timing) routed through the project's own Sentry account instead of HashiCorp, so that the project retains data-driven insights for feature prioritization and support without depending on Hashicorp infrastructure.

**Why this priority**: The project has a full Sentry business plan with OSS support that includes the Logs & Metrics product. Deleting analytics entirely would leave the project blind to adoption patterns, language usage, and performance trends. Migrating to Sentry preserves these insights using infrastructure the project already controls. **The legacy `@sentry/node@7.120.4` custom-metrics aggregator the spec originally targeted was sunset server-side on 2024-10-07 — a silent no-op on 7.x; the replacement metrics product requires SDK ≥10.x. The chosen approach (research Decision D1) upgrades `@sentry/node` `7.120.4 → ^10.56` and emits usage analytics via the v10 metrics API (`Sentry.metrics.count(...)`).**

**Independent Test**: Can be validated in isolation by a unit test that initializes a **real v10 Sentry client with a capturing `transport`** (`createTransport` from `@sentry/core`), runs a command, and asserts a `trace_metric` envelope item carrying `cli.command.invoked` (with the expected attributes) reached the transport **and** that `await Sentry.flush(2000) === true` before exit. A pure `@sentry/node` mock proves only that the API was *called*, not that the metric survives the short-lived CLI's exit (research Decision D4); mocking is reserved for the wrapper's consent-gating tests. Runs in seconds without a real Sentry DSN.

**Acceptance Scenarios**:

1. **Given** a user has usage telemetry enabled (`sendUsageTelemetry: true` in `cdktf.json`) and `SENTRY_DSN` is set and `CHECKPOINT_DISABLE` is not set, **When** they run `cdktn synth`, **Then** a command invocation metric is emitted to Sentry with tags for command name, language, and environment, and is flushed before exit.
2. **Given** a user has usage telemetry disabled (`sendUsageTelemetry: false` in `cdktf.json`), **When** they run any CLI command, **Then** no usage metrics are sent to Sentry.
3. **Given** a user has `CHECKPOINT_DISABLE` set (regardless of `sendUsageTelemetry` value), **When** they run any CLI command, **Then** no usage metrics are sent to Sentry.
4. **Given** the CLI is running in CI, **When** a command executes with telemetry enabled, **Then** the CI environment is captured as a metric tag.
5. **Given** the `sendTelemetry` function is called, **When** Sentry is not initialized (no DSN), **Then** the metric calls are silent no-ops with no errors.

---

### User Story 3 - Sentry error reporting continues working (Priority: P1)

As a project maintainer, I want the existing Sentry-based error/crash reporting to continue functioning after the HashiCorp endpoint is removed, so that the team retains visibility into production errors.

**Why this priority**: Sentry is the project's own error reporting system and must not be disrupted. The Sentry integration depends on shared utilities (`getUserId`, `getProjectId`) that currently live in the checkpoint module, and the error-handling module currently sends error reports to both Sentry and HashiCorp's checkpoint API. Both coupling points must be handled carefully. The SDK upgrade (US2 / FR-003) touches the same Sentry init path, so error reporting must be re-verified after the bump.

**Independent Test**: Can be tested by triggering a crash-reportable error with `SENTRY_DSN` set and `sendCrashReports: true`, then verifying the error appears in Sentry. Also verify that `getUserId` and `getProjectId` continue to function for Sentry scope tagging.

**Acceptance Scenarios**:

1. **Given** a user has `sendCrashReports: true` in `cdktf.json` and `SENTRY_DSN` is set, **When** an internal error occurs, **Then** the error is reported to Sentry.
2. **Given** the checkpoint module's HashiCorp-specific code is removed, **When** Sentry initializes, **Then** it can still obtain `userId` and `projectId` for scope tagging (via `Sentry.getCurrentScope()` under v10, replacing the removed `configureScope`).
3. **Given** the error-handling module previously sent reports to both Sentry and HashiCorp, **When** an error is created via `Errors.Internal/External/Usage`, **Then** only the Sentry path remains active.

---

### User Story 4 - HashiCorp checkpoint code is cleaned up (Priority: P2)

As a project maintainer, I want all HashiCorp checkpoint-specific code removed from the codebase, so that there is no dead code, no confusion about what telemetry is active, and reduced maintenance burden.

**Why this priority**: Once the HashiCorp endpoint is replaced by Sentry (P1), cleaning up the remaining dead code is a follow-on concern. This includes removing the `ReportRequest` function, the `post()` helper, the `BASE_URL` constant, the `report()` function in errors.ts, and the checkpoint-specific tests.

**Independent Test**: Can be tested by searching the codebase for references to `checkpoint-api.hashicorp.com`, `ReportRequest`, and the `post()` function. Delivers value by reducing code complexity.

**Acceptance Scenarios**:

1. **Given** the cleanup is complete, **When** a maintainer searches the codebase for HashiCorp checkpoint references, **Then** no active code references remain (copyright headers are acceptable).
2. **Given** the checkpoint code is removed, **When** the project is built, **Then** all builds succeed without errors.
3. **Given** the `report()` function in errors.ts is removed, **When** `Errors.Internal/External/Usage` is called, **Then** no errors occur and Sentry error tracking still functions.

---

### User Story 5 - Consent on upgrade & non-interactive defaults (Priority: P1)

As an existing cdktn user upgrading to this version — who already answered the crash-reporting prompt but has never seen a usage-telemetry prompt (usage telemetry was previously on-by-default with no prompt) — I want to be asked once about usage telemetry when I'm at an interactive terminal, and, when I'm not (CI/piped), to have my existing usage-tracking behavior preserved (on by default, now routed to the project's own Sentry instead of HashiCorp), so that nothing about my data sharing changes silently and the project does not lose analytics continuity across its existing install base.

**Why this priority**: Every existing project hits this path on upgrade, because `sendUsageTelemetry` is a brand-new field and is therefore unset everywhere. A naive "prompt only when neither flag is set" rule never fires for these users (their `sendCrashReports` is already decided), so the implementation would silently pick a default — either dropping analytics for the entire existing base, or resuming collection without consent. This story closes that gap and is tied to US1 (privacy: recipient changes from HashiCorp to the project's own Sentry) and US2 (analytics continuity).

**Independent Test**: Unit tests mocking `isInteractiveTerminal()` / `process.stdout.isTTY` / `process.env.CI` and the inquirer prompt, asserting: (a) interactive + `sendUsageTelemetry` unset → prompt shown once, decision persisted, `sendCrashReports` not re-prompted; (b) non-interactive + unset → no prompt and usage telemetry effective-enabled (metric emitted when `SENTRY_DSN` set and `CHECKPOINT_DISABLE` unset); (c) `CHECKPOINT_DISABLE` or explicit `false` → suppressed, no prompt.

**Acceptance Scenarios**:

1. **Given** an existing project with `sendCrashReports` set and `sendUsageTelemetry` unset, **When** the user runs a command in an interactive terminal (TTY, non-CI), **Then** they are prompted **once** for usage telemetry and the choice is persisted to `cdktf.json`; `sendCrashReports` is **not** re-prompted.
2. **Given** `sendUsageTelemetry` unset and a non-interactive run (no TTY) or CI, **When** a command executes with `SENTRY_DSN` set and `CHECKPOINT_DISABLE` unset, **Then** usage telemetry is emitted (default-on, legacy-preserving) to the project's Sentry, and **no** prompt is shown.
3. **Given** `sendUsageTelemetry` unset and `CHECKPOINT_DISABLE` set, **When** any command executes, **Then** no usage metric is emitted and no prompt is shown.
4. **Given** a brand-new `cdktn init` in an interactive terminal with both flags unset, **When** init runs, **Then** the user is asked for both consent flags (presentation MAY be consolidated into one step) and both decisions are persisted.

---

### Edge Cases

- What happens when existing users have `CHECKPOINT_DISABLE` set in their environment? It continues to disable usage telemetry (now via Sentry instead of HashiCorp). No behavior change from the user's perspective.
- What happens when `CHECKPOINT_DISABLE` is set but `sendCrashReports: true`? Crash reporting still works — `CHECKPOINT_DISABLE` only controls usage telemetry, not crash reports. These are independent concerns.
- What happens to the `~/.cdktf/config.json` file that stores `userId`? The file and `getUserId()` function must be preserved since Sentry uses `userId` for scope tagging.
- What happens to `projectId` in `cdktf.json`? The field and `getProjectId()` function must be preserved since Sentry uses `projectId` for scope tagging.
- What happens to the `report()` function in errors.ts that sends error telemetry to HashiCorp via `ReportRequest`? It must be removed. Sentry already captures these errors with richer context (stack traces, breadcrumbs, environment info) — the HashiCorp path is redundant.
- What happens if Sentry is not initialized (no DSN, user opted out of both flags)? The v10 `Sentry.metrics.count(...)` calls are silent no-ops — no errors, no data sent.
- What happens to `CHECKPOINT_DISABLE` in CI workflows (set in 13 locations across 6 files as of 2026-06-07: `build.yml`, `examples.yml`, `integration.yml`, `provider-integration.yml`, `release.yml`, `registry-docs-pr-based.yml`)? These continue to work as before — they disable usage telemetry. No CI workflow changes needed.
- What happens when a consent flag is unset in `cdktf.json`? The prompt is **per-flag**, not "neither set": on first CLI use in an **interactive terminal** (TTY and non-CI), the user is prompted for **each** unset flag (`sendUsageTelemetry` and/or `sendCrashReports`), mirroring the existing `sendCrashReports` consent flow — now that usage analytics also flow through Sentry, the consent surfaces are deliberately aligned (see FR-005, FR-008).
- What happens to an existing project that already has `sendCrashReports` set but no `sendUsageTelemetry` (the upgrade path — every existing project)? In an interactive terminal the user is prompted **once** for usage telemetry (and `sendCrashReports` is not re-asked). In a **non-interactive** run (no TTY) or CI, usage telemetry **defaults to enabled** — preserving the legacy on-by-default behavior — but now routed to the project's own Sentry instead of HashiCorp, still subject to the `CHECKPOINT_DISABLE` override (see FR-016). Nothing about usage-data sharing changes silently.
- What is the non-interactive default for each flag? `sendUsageTelemetry` defaults to **enabled** (legacy on-by-default, gated by `CHECKPOINT_DISABLE`); `sendCrashReports` retains its existing default of **disabled**. The two non-interactive defaults intentionally differ, each preserving its own legacy behavior (see FR-016).
- What happens when a command runs **outside a project** (no `cdktf.json`, e.g. `cdktn convert`)? There is nowhere to persist a consent decision, so no prompt is shown and the non-interactive defaults apply: usage telemetry effective-enabled (legacy-preserving, still gated by `CHECKPOINT_DISABLE` + `SENTRY_DSN`); crash reporting off. (Decided 2026-06-10; see research Decision 8.)
- ⚠️ Implementation/migration note: the pre-existing runtime crash-consent prompt was **dead code** (`shouldReportCrash()` could never return `undefined` — an absent key coerced to `false`), so it never fired. Implementing FR-008's per-flag tri-state **revives the crash prompt** for interactive users whose `cdktf.json` lacks `sendCrashReports`. This MUST be called out in user-facing migration/release notes. (See research Decision 8.)

## Requirements *(mandatory)*

### Functional Requirements

**Telemetry migration:**

- **FR-001**: The CLI MUST NOT make any outbound HTTP requests to `checkpoint-api.hashicorp.com` or any other HashiCorp-owned endpoint.
- **FR-002**: Usage telemetry (command invocations, language, timing, CI environment) MUST be emitted as Sentry **v10 metrics** (`Sentry.metrics.count(...)`) instead of being sent to HashiCorp.
- **FR-003**: `@sentry/node` MUST be upgraded from `7.120.4` to `^10.56` across the three consuming packages (`@cdktn/commons`, `@cdktn/cli-core`, `cdktn-cli`), and usage analytics MUST be emitted via the **v10 metrics API** (`Sentry.metrics.count(...)`). `Sentry.init()` MUST set `tracesSampleRate: 0` — empirically confirmed (spike 2026-06-10, `@sentry/node@10.57.0`) to deliver metrics independently of trace sampling (see FR-015). `enableLogs` is NOT required for metrics and MUST be omitted unless structured logs are independently needed (they are not — YAGNI). The legacy 7.x `Sentry.metrics.metricsAggregatorIntegration()` / `Sentry.metrics.increment()` mechanism MUST NOT be used — the server-side product it targeted was sunset 2024-10-07 and is a silent no-op on `7.120.4` (research Decision D1).
- **FR-018**: The shared `Sentry.init()` MUST set `serverName` to a fixed constant (e.g. `"cdktn-cli"`) so the machine **hostname** is not attached to any payload. This scrubs hostname from **both** new usage metrics (v10 auto-attaches `server.address` = hostname to every metric) **and** error/crash events (Sentry populates `event.server_name` = hostname by default — a pre-existing leak in today's crash reports, since the current `initializErrorReporting()` sets no `serverName`). Both confirmed scrubbed by a single `serverName` setting (spike 2026-06-10: error `server_name` and metric `server.address` both become the constant). `userId`/`projectId` scope tags remain for triage, so debugging is unaffected. This keeps the privacy posture at least as tight as — in fact tighter than — the legacy HashiCorp transport, which never sent hostname (US1, and a privacy improvement to US3).
- **FR-004**: The existing `sendTelemetry(command, payload)` function signature SHOULD be preserved where practical, with the implementation changed from HTTP POST to HashiCorp to Sentry v10 metric emission, to minimize churn across the 7 call sites.

**Consent model:**

- **FR-005**: A new `sendUsageTelemetry` field MUST be added to `cdktf.json` to independently control usage telemetry, separate from `sendCrashReports` which controls crash reporting. It MUST follow the repo's current **typed** config pattern (as established by the `importExtension`/`languageOptions` feature): declared on `ConfigBase` in `packages/@cdktn/commons/src/config.ts` (language-agnostic — NOT inside the language-discriminated union) with a validated getter on `CdktfConfig` (`cli-core/src/lib/cdktf-config.ts`), rather than the legacy loose raw-JSON access that `sendCrashReports` uses in `error-reporting.ts`. **The consent UX for `sendUsageTelemetry` MUST mirror `sendCrashReports`** (prompt on first CLI use in an interactive terminal, decision persisted to `cdktf.json`; see FR-008). The non-interactive/CI default differs per flag (FR-016). This deliberate alignment of the consent *surface* is the rationale for introducing the new config field — now that usage analytics also flow through Sentry, the prompt mechanism is unified. It is the **only** intended UX change relative to the legacy on-by-default usage telemetry; the tracking semantics (what is collected, the CI handling) and the `CHECKPOINT_DISABLE` override are otherwise preserved.
- **FR-006**: The `CHECKPOINT_DISABLE` environment variable MUST continue to disable usage telemetry when set, overriding `sendUsageTelemetry: true`. It MUST NOT affect crash reporting (`sendCrashReports`).
- **FR-007**: Sentry MUST be initialized if either `sendCrashReports` or the effective `sendUsageTelemetry` value (after applying FR-016 defaults) is true **AND** `SENTRY_DSN` is set.
- **FR-008**: The consent prompt MUST be **per-flag**: on first CLI use in an **interactive terminal** (detected via the existing `isInteractiveTerminal()` = `process.stdout.isTTY && !process.env.CI`), the user MUST be prompted for **each** unset consent flag (`sendUsageTelemetry` and/or `sendCrashReports`), and the decision MUST be persisted to `cdktf.json` (mirroring the existing `persistReportCrashReportDecision` flow). A flag that is already set MUST NOT be re-prompted. When both are unset at `cdktn init`, the prompts MAY be consolidated into one step. The runtime prompt path MUST gate on `isInteractiveTerminal()` (not only on CI), so non-TTY runs fall through to the FR-016 defaults instead of attempting to prompt.
- **FR-016**: When a consent flag is unset and **no prompt can be shown** (non-interactive: no TTY, or CI), the effective default MUST preserve each system's legacy behavior: `sendUsageTelemetry` defaults to **enabled** (legacy on-by-default usage telemetry, now routed to the project's own Sentry), and `sendCrashReports` defaults to **disabled**. The `sendUsageTelemetry` default remains subject to the `CHECKPOINT_DISABLE` override (FR-006) and requires `SENTRY_DSN` to actually emit.
- **FR-017**: Usage-telemetry gating MUST follow this precedence (highest first): (1) `CHECKPOINT_DISABLE` set → disabled, no prompt; (2) `sendUsageTelemetry` explicitly set → honor the value; (3) unset + interactive → prompt once and honor/persist the answer; (4) unset + non-interactive → FR-016 default (enabled). Emission additionally requires `SENTRY_DSN` (otherwise a silent no-op per the v10 metrics API).

**Sentry preservation:**

- **FR-009**: The Sentry error reporting system MUST continue to function unchanged from the user's perspective, including `userId` and `projectId` scope tagging, breadcrumbs, and crash reporting, after the v10 SDK upgrade.
- **FR-010**: The `getUserId()` and `getProjectId()` utility functions MUST be preserved and relocated from `checkpoint.ts` to an appropriate module.

**Code cleanup:**

- **FR-011**: The `ReportRequest` function, `post()` helper, `BASE_URL` constant, and `ReportParams` interface MUST be removed.
- **FR-012**: The `report()` function in errors.ts that sends error data to HashiCorp via `ReportRequest` MUST be removed. The `Errors` object and its Sentry integration MUST be preserved.
- **FR-013**: All existing tests MUST continue to pass, with checkpoint-specific tests replaced by Sentry metrics tests (using the real-client capturing-transport delivery oracle per US2 Independent Test and research Decision D4).

**Metric definitions & delivery:**

- **FR-014**: The canonical usage metric names MUST be: `cli.command.invoked` (per-command invocation; attributes `command`, optional `language`, `ci`), `cli.synth.duration` (synth timing, distribution-style), and `cli.command.error` (command-level **usage** error counter). `cli.command.error` is a usage metric gated by `sendUsageTelemetry` (and `CHECKPOINT_DISABLE`), distinct from crash reporting (FR-009) — the two MUST NOT double-count the same event.
- **FR-015**: Usage metrics MUST be delivered independently of trace sampling — a low or zero `tracesSampleRate` MUST NOT silently drop usage analytics. The concrete `tracesSampleRate` value is pinned in research.md/plan.md and referenced by the `Sentry.init()` contract (contracts/telemetry-contract.md C4).

**Out of scope:**

- **OS-001**: Removing `CHECKPOINT_DISABLE` from CI workflows (13 locations across 6 files) is explicitly out of scope. The env var continues to function as a usage telemetry override.
- **OS-002**: Renaming `sendCrashReports` to a broader name, or merging the two flags into one, is out of scope. The two flags remain independent (though their consent UX is aligned per FR-005).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero outbound HTTP requests to HashiCorp endpoints when running any CLI command.
- **SC-002**: Usage metrics (`cli.command.invoked` with command name, language, OS, CI environment; `cli.synth.duration`) appear in Sentry when `sendUsageTelemetry: true` and `CHECKPOINT_DISABLE` is not set.
- **SC-003**: Usage metrics are not sent when `CHECKPOINT_DISABLE` is set, regardless of `sendUsageTelemetry` value.
- **SC-004**: Sentry error reporting functions correctly (errors appear in Sentry when `sendCrashReports: true`), independent of usage telemetry settings, after the v10 upgrade.
- **SC-005**: All unit tests pass, including new telemetry tests validating Sentry metric emission (real-client capturing transport), flush-before-exit delivery, and consent gating.
- **SC-006**: All integration tests pass after the migration.
- **SC-007**: No dead code remains related to HashiCorp's checkpoint API.
- **SC-008**: On upgrade, usage-data sharing never changes silently: an existing project (`sendCrashReports` set, `sendUsageTelemetry` unset) is prompted **once** for usage telemetry in an interactive terminal, and defaults to **enabled** (legacy-preserving, routed to the project's Sentry, subject to `CHECKPOINT_DISABLE`) in non-interactive/CI runs.

### Previous work

- **SL-6b54af - Update Sentry telemetry release tag** (001-cdktn-package-rename): Related task that updates Sentry telemetry release tags as part of the rename. Sentry error reporting is preserved and unaffected by this feature.
- **SL-3d9d60 - Add migration telemetry events** (001-cdktn-package-rename): Related task for adding migration telemetry events. This feature replaces the HashiCorp transport with Sentry, so migration telemetry should use the new Sentry-based `sendTelemetry` function.
- **GitHub Issue #48**: The originating issue reporting that cdktn-cli telemetry uses HashiCorp's endpoint.

## Dependencies & Assumptions

### Assumptions

- **Sentry business plan includes the Logs & Metrics product**: The project has a full Sentry business plan with OSS support. The v10 Logs & Metrics product is available at no additional cost (org-side enablement required; the SaaS toggle is gated to SDK ≥10.x).
- **`@sentry/node` upgrade to `^10.56` is REQUIRED**: The legacy 7.x custom-metrics aggregator (`Sentry.metrics.increment()/.distribution()/.set()/.gauge()`, `metricsAggregatorIntegration()`) targeted a Metrics Beta that **ended server-side 2024-10-07** — a silent no-op on `7.120.4`. The replacement metrics product requires **SDK ≥10.x** (confirmed against the project's own SaaS settings: the "Logs and Metrics" toggle is gated to SDK version 10.x and above). The chosen transport (research Decision D1) upgrades `@sentry/node` `7.120.4 → ^10.56` across the three consuming packages and uses the v10 `Sentry.metrics.count(...)` API.
- **Two independent, UX-aligned consent flags**: `sendCrashReports` controls crash/error reporting; `sendUsageTelemetry` controls usage analytics. Both live in `cdktf.json` and share the same interactive consent prompt mechanism (per-flag prompt on first interactive use, persisted). Their **non-interactive/CI defaults differ** (usage→enabled, crash→disabled) to preserve each system's legacy behavior (FR-016). Sentry is initialized iff either flag's effective value is true **AND `SENTRY_DSN` is set**.
- **Interactivity & CI detection already exist**: `isInteractiveTerminal()` (`check-environment.ts:151` = `process.stdout.isTTY && !process.env.CI`), `ci-info`, and the `askForCrashReportingConsent`/`persistReportCrashReportDecision`/`initializErrorReporting` consent machinery are reused as-is. The only refinement is gating the runtime prompt on `isInteractiveTerminal()` (the existing runtime path guards CI but not TTY).
- **`CHECKPOINT_DISABLE` remains a usage telemetry override**: The env var continues to disable usage telemetry when set, providing backward compatibility for existing CI workflows (13 locations across 6 files) and users. It does not affect crash reporting. The legacy early-return gate inside `ReportRequest` (`checkpoint.ts:155`) is removed with the HashiCorp transport; the override moves into the new usage-telemetry gating (alongside the `environment.ts` constant).
- **`getUserId` and `getProjectId` are shared utilities**: Used by both the checkpoint system (being removed) and Sentry error reporting (being preserved). Must be retained and relocated from `checkpoint.ts`.
- **`ci-info` is a shared dependency**: Used by both the checkpoint system and Sentry error reporting, so it must not be removed.
- **`uuid` is still needed**: `getUserId()` uses `uuidv4()` and is preserved for Sentry. Also used by `init.ts` for project ID generation.
- **Metrics are silent no-ops when Sentry is not initialized**: If `SENTRY_DSN` is not set or the user has opted out of both flags, the v10 `Sentry.metrics.count(...)` calls do nothing — no errors, no data sent.

### Research

The following research spikes informed this specification:

- [Checkpoint usage analysis](research/2026-03-20-checkpoint-usage-analysis.md): Complete map of checkpoint.ts exports, 7 sendTelemetry call sites, and dependency analysis.
- [Sentry usage and migration feasibility](research/2026-03-20-sentry-usage-and-checkpoint-migration.md): Sentry metrics capabilities, migration mapping, and decision to route analytics through Sentry.
- [Testing strategy and SDK validation](research/2026-03-20-testing-strategy-and-sentry-sdk-validation.md): Original isolated validation-test approach and call-site mapping. **Partly superseded by the 2026-06-08 transport-viability finding below** — the "SDK supports metrics without upgrade" conclusion no longer holds (the 7.x metrics product was sunset; see Decision D1 and the v10 delivery oracle).
- [Re-validation against current main](research/2026-06-07-revalidation-against-main.md): After rebasing the stale branch onto `main` (~118 commits of drift), re-verified every code claim via parallel exploration. The typed `ConfigBase` pattern for `sendUsageTelemetry` (FR-005, per the merged `importExtension` feature) and CI count 14→13 still hold. **Note: this bullet's original endorsement of the 7.x `Sentry.metrics.metricsAggregatorIntegration()` wording (FR-003) is SUPERSEDED by the 2026-06-08 transport-viability finding below (Decision D1 — upgrade to `^10.56`).** The ESM/import-extension feature was checked and does not conflict.
- [Build & release Sentry config injection](research/2026-06-07-build-release-sentry-injection.md): Confirmed the known-working error path — DSN baked at build time via esbuild `define` (`build.ts:96-97`) from `secrets.SENTRY_DSN` in `build.yml`/`release.yml`/`integration.yml`; runtime `release: cdktn-cli-<version>` (`error-reporting.ts:87`) matches the release pipeline. **No CI changes needed** for metrics. **New risk surfaced**: `Sentry.close(4000)` only runs on the error path (`cdktn.ts:184`), so happy-path usage metrics would be dropped without a bounded flush on normal exit — added as a plan requirement.
- [Sentry metrics transport viability](research/2026-06-08-sentry-metrics-transport-viability.md): ⚠️ **Transport-invalidating finding.** Sentry's custom Metrics Beta (the product `@sentry/node@7.120.4`'s `Sentry.metrics.*` aggregator targets) **ended 2024-10-07**; the new Logs/Metrics product requires **SDK ≥10.x** (confirmed against the project's own SaaS settings — the toggle is grayed out on 7.x). So the original FR-002/FR-003 metrics mechanism is a server-side no-op on the pinned SDK. **Decision (maintainer): upgrade `@sentry/node` 7→^10.56 + new v10 metrics API.** Includes the loader-script exploration (live SDK train = 10.56.0), the v7→v10 migration blast radius (2× `configureScope` + `init` rebuild), and the `sentry-cli` 2.58.4 pin constraint. **This decision is now reflected in FR-002/FR-003/FR-014/FR-015 and the Assumptions above.**
- [v10 end-to-end validation](research/2026-06-08-v10-e2e-validation.md): Local + CI verification path for the v10 migration. Integration suite runs the real bundle as a child process (nock can't reach it); `SENTRY_DSN` is esbuild-baked at build time. Delivery oracle = real v10 client + capturing custom `transport` asserting a `trace_metric` envelope + `flush()===true` (short-lived CLI drops buffered metrics without an explicit bounded flush). Layered: L1 unit (transport capture), L2 no-egress nock (with `CHECKPOINT_DISABLE` unset), L3 bundle E2E (build with local-sink DSN), L4 manual Spotlight.
- [Bundle E2E local validation recipe](research/2026-06-10-bundle-e2e-validation-recipe.md): Makes L3 concrete and runnable. The cdktn-cli bundle is directly runnable (no Verdaccio/dist needed); build with `SENTRY_DSN=http://k@localhost:9999/1`, run a ~30-line local Sentry sink, and trigger with `cdktn convert` (dependency-free SUCCESS path that isolates the new bounded flush) + `synth --app 'node -e process.exit(1)'` (error path). Empty sink ⇒ flush missing/broken. Ships as `tools/sentry-sink.mjs` + `tools/validate-sentry-e2e.sh`, reused by a gated CI jest test; runnable today against the v7 bundle via the error trigger.
