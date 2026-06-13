# Implementation Plan: Replace HashiCorp Telemetry with Sentry Analytics

**Branch**: `002-remove-hashicorp-telemetry` | **Date**: 2026-06-08 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specledger/002-remove-hashicorp-telemetry/spec.md`

## Summary

Remove all outbound telemetry to `checkpoint-api.hashicorp.com` from the cdktn CLI and route usage analytics through the project's own Sentry instead. Because Sentry **sunset the custom-metrics product the original spec targeted** (2024-10-07; the 7.x `Sentry.metrics.*` aggregator is a server-side no-op), the chosen approach is to **upgrade `@sentry/node` 7.120.4 → ^10.56** across the three packages and emit usage analytics via the new v10 metrics API (`Sentry.metrics.count(...)`; `Sentry.init()` pins `tracesSampleRate: 0` + `serverName: "cdktn-cli"` — `enableLogs` is omitted, confirmed unnecessary for metrics by the 2026-06-10 spike / Decision 9). Sentry error/crash reporting is preserved throughout. A **bounded flush on normal exit** is added so happy-path analytics are actually delivered from the short-lived CLI. Work is phased so the SDK upgrade, the HashiCorp removal, and the analytics addition are independently reviewable and the known-working error pipeline stays green at each step.

## Technical Context

**Language/Version**: TypeScript (ES2022), Node 20.20 (`.nvmrc`); CLI bundle built with esbuild, target `node22`
**Primary Dependencies**: `@sentry/node` `7.120.4 → ^10.56` (UPGRADE); `uuid@9.0.1`, `ci-info@3.9.0` (retained); esbuild (bundle + `define` DSN bake-in); `@sentry/cli@2.58.4` (release tooling — **pinned, unchanged**)
**Storage**: `~/.cdktf/config.json` (`userId`), `cdktf.json` (`projectId`, `sendCrashReports`, new `sendUsageTelemetry`) — files, unchanged shape except the new flag
**Testing**: Jest 29.7 + ts-jest, per-package; integration via `TestDriver` (`--enable-crash-reporting=false`); new unit tests use a **real v10 client + capturing transport** as the delivery oracle (contract C5); `@sentry/node` mocks reserved for consent-gating tests
**Target Platform**: Node CLI (`cdktn`), distributed as an esbuild bundle; multi-language scaffolding unaffected
**Project Type**: JSII monorepo (single logical project, multiple packages)
**Performance Goals**: Telemetry MUST NOT add perceptible latency or block the CLI; flush bounded (≤4000ms, mirrors error path) and only when reporting is enabled
**Constraints**: Zero outbound HashiCorp requests; Sentry error reporting unchanged; no SaaS-required CI changes; `sentry-cli` stays at 2.58.4; metrics silent no-op when Sentry uninitialized
**Scale/Scope**: ~4 files import `@sentry/node`; 7 `sendTelemetry` call sites; ~6 commons/cli-core files edited; one major dep bump ×3 packages

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **Specification-First**: spec.md complete with prioritized user stories (US1-US4, P1/P2), re-validated 2026-06-08.
- [x] **Test-First**: test strategy defined — unit tests (mock `@sentry/node`) for metric emission, consent gating, and **flush-before-exit delivery**; integration smoke test asserting no HashiCorp egress. (Decisions 3-4.)
- [x] **Code Quality**: ESLint/Prettier + tsc (esbuild transpile + tsc pre-commit) — existing tooling, unchanged.
- [x] **UX Consistency**: consent flow reuses existing prompt model; `sendUsageTelemetry` independent of `sendCrashReports`; `CHECKPOINT_DISABLE` honored. Acceptance scenarios in spec.
- [x] **Performance**: bounded flush (≤4000ms) defined; no-op when Sentry off; no added latency on the hot path.
- [x] **Observability**: analytics via Sentry metrics; errors via existing Sentry pipeline; `release: cdktn-cli-<version>` correlation preserved.
- [ ] **Issue Tracking**: Epic to be created with `sl issue create --type epic` and linked to spec (action item — see Phase 2 handoff).

**Complexity Violations**: One — a **major SDK upgrade (7→10)** is larger than a typical minimal change. Justified in Complexity Tracking; mitigated by phasing (SDK bump isolated from telemetry logic) and the small concrete breaking surface (2 `configureScope` rewrites + 1 init rebuild).

## Project Structure

### Documentation (this feature)

```text
specledger/002-remove-hashicorp-telemetry/
├── plan.md              # This file
├── research.md          # Phase 0 consolidated decisions
├── research/            # Detailed spikes (2026-03-20 … 2026-06-08)
├── data-model.md        # Phase 1 — config + telemetry event entities
├── quickstart.md        # Phase 1 — user journeys → integration scenarios
├── contracts/           # Phase 1 — config schema + metric/event contract
└── tasks.md             # Phase 2 (/specledger.tasks — NOT created here)
```

### Source Code (repository root)

```text
packages/@cdktn/commons/src/
├── checkpoint.ts        # STRIP HashiCorp transport; keep id utils (relocate → identity.ts)
├── identity.ts          # NEW — getUserId/getProjectId/getId/homeDir (relocated)
├── errors.ts            # REMOVE report()/ReportRequest import; migrate configureScope→getCurrentScope
├── environment.ts       # CHECKPOINT_DISABLE (retain as usage-telemetry override)
├── logging.ts           # addBreadcrumb ×6 (unchanged under v10)
├── config.ts            # ADD sendUsageTelemetry to ConfigBase
└── telemetry.ts         # NEW — sendTelemetry() wrapper emitting Sentry v10 metrics

packages/@cdktn/cli-core/src/lib/
├── error-reporting.ts   # init rebuild (v10): tracesSampleRate: 0 + serverName (FR-018); configureScope→getCurrentScope; consent gate
├── cdktf-config.ts      # ADD validated sendUsageTelemetry getter
└── (synth-stack.ts, watch.ts, cdktf-project.ts)  # convert sendTelemetry call sites

packages/cdktn-cli/src/bin/
├── cdktn.ts             # ADD bounded flush on normal exit (mirrors :184 error-path close)
└── cmds/{handlers.ts, helper/init.ts, ui/get.tsx}  # convert sendTelemetry call sites

packages/@cdktn/commons/src/
└── telemetry.test.ts    # NEW — delivery oracle (real v10 client + capturing transport) + gating; co-located with the wrapper

packages/@cdktn/cli-core/src/test/
├── error-reporting.test.ts           # NEW — consent prompt/default gating matrix (mock @sentry/node)
├── cdktf-config.test.ts              # NEW — validated sendUsageTelemetry getter (FR-005)
├── no-hashicorp-runtime-egress.test.ts # NEW — nock runtime no-egress oracle (J1/L2)
└── (checkpoint.test.ts DELETED)

packages/cdktn-cli/src/test/
├── no-hashicorp-egress.test.ts       # NEW — static source + bundle scan (FR-001/SC-007)
└── sentry-bundle-e2e.test.ts         # NEW — gated bundle E2E (CDKTN_SENTRY_E2E=1)

# Build/release (verify, mostly unchanged)
packages/cdktn-cli/build.ts        # SENTRY_DSN define — unchanged
.github/workflows/release.yml      # verify sourcemap symbolication under v10; modernize command form only if needed (keep sentry-cli 2.58.4)
Dockerfile / mise.toml             # sentry-cli 2.58.4 — UNCHANGED
```

**Structure Decision**: Single JSII monorepo. Changes concentrate in `@cdktn/commons` (transport + identity + config + new telemetry wrapper), `@cdktn/cli-core` (Sentry init + call sites + config getter), and `cdktn-cli` (exit flush + call sites). No new packages.

## Implementation Phases (for /specledger.tasks)

> Each phase is an independently reviewable change that keeps error reporting working.

- **Phase A — SDK upgrade (no behavior change)**: bump `@sentry/node` → `^10.56` in 3 `package.json` + lockfile; migrate `Sentry.configureScope` → `Sentry.getCurrentScope()` (`error-reporting.ts:120`, `errors.ts:56`); rebuild `Sentry.init` options (drop/replace `autoSessionTracking`); confirm `addBreadcrumb`/`setContext`/`captureException`/`close` unchanged. Verify error reporting + release sourcemap symbolication (sentry-cli 2.58.4). Maps US3.
- **Phase B — Remove HashiCorp transport**: strip `sendTelemetry`/`ReportRequest`/`ReportParams`/`post`/`BASE_URL` from `checkpoint.ts`; relocate id utils → `identity.ts`; remove `report()` from `errors.ts`; delete `checkpoint.test.ts`; update barrel exports. Maps US1, US4.
- **Phase C — Usage analytics via v10 metrics**: new `telemetry.ts` `sendTelemetry(command, payload)` → `Sentry.metrics.count(...)` (names per FR-014); set `tracesSampleRate: 0` + `serverName: "cdktn-cli"` in `init` (FR-015/FR-018/Decision 9 — metrics confirmed to deliver at 0; `enableLogs` omitted per YAGNI); reconnect the 7 call sites; add `sendUsageTelemetry` to `ConfigBase` + `CdktfConfig` getter; **consent gating** = per-flag interactive prompt (reuse `isInteractiveTerminal()`/`askForCrashReportingConsent`/`persistReportCrashReportDecision`) + non-interactive default-on for usage / off for crash (FR-008/FR-016/FR-017, Decision 8); gate the runtime prompt on `isInteractiveTerminal()` (currently CI-only); **bounded flush on normal exit** in `cdktn.ts`; `telemetry.test.ts` (emission + flush-before-exit + prompt/default gating matrix). Maps US2, US5.
- **Phase D — Verify**: integration smoke test asserting zero `checkpoint-api.hashicorp.com` egress; SaaS dashboard manual check (one-time). Maps SC-001…SC-007.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Major SDK upgrade `@sentry/node` 7→10 (×3 packages) | The 7.x metrics product the spec targeted was sunset server-side (2024-10-07); the new metrics API requires SDK ≥10.x (confirmed via project SaaS settings + live loader = 10.56.0). Maintainer chose first-class metrics. | **Spans on 7.x** (no upgrade) was viable and lighter but rejected by maintainer in favor of first-class metric counters/dashboards. Mitigated by isolating the bump (Phase A) and a small breaking surface. |
| New `sendUsageTelemetry` config field | Spec FR-005 requires usage telemetry to be independently controllable from crash reporting. | Reusing `sendCrashReports` for both rejected (OS-002) — conflates two independent consent concerns. |
