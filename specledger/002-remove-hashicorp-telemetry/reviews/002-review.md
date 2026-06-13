---
date: 2026-06-10
total_requirements: 20
total_tasks: 0
coverage_pct: 80
critical_issues: 3
---

# Specification Analysis Report — 002-remove-hashicorp-telemetry

**Feature**: Replace HashiCorp Telemetry with Sentry Analytics
**Date**: 2026-06-10
**Reviewers**: 2 independent passes (merged)
**Scope**: spec.md ↔ plan.md, research.md, data-model.md, contracts/*, quickstart.md (no tasks.md — intentional)

## Summary

The spec is **not** internally consistent with its planning artifacts: the normative requirements still mandate a Sentry transport that the project has already decided to abandon. The headline issue is that FR-003 (and the supporting FR-002, US2, and the Dependencies & Assumptions block) still bind implementers to the `@sentry/node@7.120.4` `metrics.metricsAggregatorIntegration()` mechanism, which research Decision D1 and the 2026-06-08 transport-viability spike established as a server-side no-op (Metrics Beta ended 2024-10-07). Every downstream artifact (plan.md, data-model.md, contracts C1/C4/C5, quickstart) has moved to `@sentry/node ^10.56` + `Sentry.metrics.count(...)`, so an implementer following the spec literally would ship a dead path. The root cause is that the spec was never re-baselined off Draft after Decision D1. Coverage is otherwise strong; the main secondary gaps are the first-use consent prompt (FR-008) having no exercised journey and the canonical metric names existing only in downstream artifacts without a spec anchor.

| Severity | Count |
|----------|-------|
| CRITICAL | 3 |
| HIGH     | 2 |
| MEDIUM   | 6 |
| LOW      | 4 |
| INFO     | 1 |

## Findings

| # | Severity | Category | Location | Summary | Recommendation |
|---|----------|----------|----------|---------|----------------|
| 1 | CRITICAL | DecisionIntegrity | spec.md:97 (FR-003) | FR-003's normative MUST mandates the sunset 7.120.4 mechanism: it requires `Sentry.metrics.metricsAggregatorIntegration()` (member of the `metrics` object in `@sentry/node@7.120.4`) and calls the API '@experimental ... functional and runtime-confirmed.' Research D1 (research.md:15-18) and the transport-viability spike (research/2026-06-08-sentry-metrics-transport-viability.md:30-32) establish this exact aggregator targets the Metrics Beta that ended server-side 2024-10-07 and is a silent no-op on 7.x; the recorded maintainer decision is to upgrade to `@sentry/node ^10.56` and use `Sentry.metrics.count(...)`. Every downstream artifact (plan.md:8, contracts C1/C4, data-model.md:44) targets v10, so an implementer following the spec literally ships a no-op. | Rewrite FR-003 to require the v10 metrics product: `@sentry/node` upgraded to `^10.56`, metrics via `Sentry.metrics.count(...)`, `enableLogs: true` + a chosen `tracesSampleRate` in `Sentry.init()`. Remove all reference to `metricsAggregatorIntegration()` and the '@experimental' 7.x API. Cite Decision D1. |
| 2 | CRITICAL | DecisionIntegrity | spec.md:96 (FR-002) + spec.md:32,34 (US2) + spec.md:85 | FR-002 ('MUST be emitted as Sentry custom metrics') plus US2 ('The existing `@sentry/node@7.120.4` SDK already supports custom metrics (`Sentry.metrics.increment()`...) — no SDK upgrade needed', and an Independent Test verifying `Sentry.metrics.increment()` is called) plus the line-85 edge case ('`Sentry.metrics.*` calls are silent no-ops') are all the invalidated 7.x mechanism (D1). US2's 'no SDK upgrade needed' is the exact opposite of the chosen Phase A SDK 7→10 upgrade (plan.md). The method `increment` is also the 7.x name, not the v10 `count` in C1/data-model.md:44. | Update FR-002, US2 'Why this priority', the US2 Independent Test, and the line-85 edge case to the v10 metrics API (`Sentry.metrics.count`) and the required SDK upgrade. Remove the 'no SDK upgrade needed' claim and the `increment()`-based test prescription. |
| 3 | CRITICAL | DecisionIntegrity | spec.md:146,160 (Dependencies & Assumptions / Research) | The Assumptions block asserts the dead transport as a load-bearing premise: line 146 '`@sentry/node@7.120.4` supports custom metrics ... Still pinned at 7.120.4 (no v8 jump...). No SDK upgrade required.' and the line-160 research bullet 'Confirmed SDK supports metrics without upgrade.' These directly contradict research D1 and plan.md (upgrade to `^10.56` across commons/cli-core/cdktn-cli), which plan.md treats as a load-bearing complexity violation. The block is internally inconsistent: lines 161/163 correctly record the v10 decision while 146/160 still claim no upgrade — an implementer cannot tell which governs. | Replace the '7.120.4 supports custom metrics / no SDK upgrade required' assumption (line 146) and the line-160 research summary with the v10 reality: legacy 7.x metrics sunset 2024-10-07, new product requires SDK ≥10.x, so `@sentry/node` upgraded to `^10.56`; state 'SDK upgrade REQUIRED.' Keep the surviving parts (uuid/ci-info retained, CHECKPOINT_DISABLE override, getUserId/getProjectId preserved). |
| 4 | HIGH | Consistency | spec.md:34 (US2 Independent Test) | The US2 Independent Test says to 'mock `@sentry/node` and verify `Sentry.metrics.increment()` is called.' Beyond the wrong 7.x method (finding 2), contract C5 (telemetry-contract.md:77) and research D4 explicitly state a pure `@sentry/node` jest mock proves only that the API was *called*, not that the metric survives to exit, and require a real-client capturing-transport delivery oracle. The spec's prescribed test would pass while metrics are silently dropped. | Rewrite the Independent Test to match C5: real v10 client + capturing transport asserting a `trace_metric` envelope for `cli.command.invoked` and `await Sentry.flush(2000) === true`; reserve mocking for gating-only unit tests. |
| 5 | HIGH | Consistency | spec.md:146,148,150,151 (Assumptions detail) | The assumption detail enumerates the 7.x metrics surface (`increment/.distribution/.set/.gauge` and `metricsAggregatorIntegration()` as members of the `metrics` object) as the basis for the no-op claim. This contradicts the v10 surface (`count`) used by contracts C1/C4 and data-model.md, and compounds finding 3 by anchoring assumptions to the sunset API even where the surviving no-op-when-uninitialized behavior is still valid. | When re-baselining the Assumptions block (finding 3), drop the 7.x method enumeration and re-ground any retained no-op-when-uninitialized assumption on the v10 `Sentry.metrics.count` surface. |
| 6 | MEDIUM | DecisionIntegrity | spec.md:85 (Edge Cases) + spec.md:152 | The 'silent no-op' edge case is valid (no-op-when-Sentry-uninitialized survives the v10 migration — data-model.md:42, C1) but is worded against the 7.x API (line 152 ties the no-op to `metrics.increment/.distribution/.set/.gauge` membership), implying the sunset surface. | Keep the no-op-when-uninitialized requirement but phrase it transport-neutrally (e.g. 'the v10 `Sentry.metrics.count` calls are silent no-ops when Sentry is not initialized'); remove the 7.x `.increment/.distribution/.set/.gauge` enumeration from line 152. |
| 7 | MEDIUM | Traceability | data-model.md:35,51-56; contracts/telemetry-contract.md:18-20 | The concrete metric names `cli.command.invoked`, `cli.synth.duration`, and `cli.command.error` are introduced in data-model.md, asserted in contract C1, and tested in quickstart Journeys 2/3/6, but no FR defines them. FR-002 only requires emitting 'command invocations, language, timing, CI environment' as custom metrics; it never names metrics nor mandates an error metric. `cli.command.error` (data-model.md:52) in particular has no spec anchor and conceptually overlaps the crash-reporting path (FR-009), leaving its gating (usage vs crash) unspecified. | Either add an FR enumerating the canonical metric names and event kinds, or annotate them in data-model.md/C1 as implementation-detail derivations of FR-002. Clarify whether `cli.command.error` is gated by `sendUsageTelemetry` or part of crash reporting, to avoid double-counting against FR-006/FR-009. |
| 8 | MEDIUM | Ambiguity | contracts/telemetry-contract.md:57 (C4 `tracesSampleRate: <chosen>`) | `tracesSampleRate: <chosen>` leaves the sample rate undecided. research/2026-06-08 Finding 4 and the SaaS note flag that spans/metrics count toward the performance-units quota and the value affects whether usage events are sampled out — an implementer could pick 0.0 (analytics effectively lost), 1.0 (full quota cost), or anything between, producing materially different telemetry behavior. | Pin a concrete `tracesSampleRate` value (or an explicit decision that metrics are independent of trace sampling under the v10 metrics API) in research.md/plan.md before implementation, and reference it from C4. |
| 9 | MEDIUM | Coverage | spec.md:105 (FR-008) / quickstart.md | FR-008 ('When neither flag is set, the user MUST be prompted on first CLI use, non-CI only') and its edge case (spec.md:87) have no dedicated quickstart journey or test. Contract C2 mentions 'Unset (non-CI) → prompt; CI → false, no prompt' as a one-line bullet (telemetry-contract.md:43) but Journeys 2-5 all preset `cdktf.json` flags, bypassing the prompt entirely. The prompt and CI-no-prompt branches are asserted but never test-mapped, which Principle VIII (each FR test-translatable/exercised) requires. | Add a quickstart journey (and matrix row) covering (a) unset flags + non-CI → prompt shown, and (b) unset flags + CI → no prompt with both flags defaulting disabled. Map it to FR-008. |
| 10 | MEDIUM | Constitution | plan.md:34, plan.md:92-97 (Complexity Tracking) vs constitution.md:60-71 (Principle III) | The bundled major SDK upgrade (7→10 across 3 packages) is a self-declared violation of Principle III (Minimal Viable Change, PRs <30 min). The justification holds in substance — the 7.x metrics product is genuinely sunset (research Findings 1-2), the breaking surface is small/concentrated (2× `configureScope` rewrites + 1 `init` rebuild), and the plan phases the bump into its own reviewable Phase A. This is NOT auto-CRITICAL: the conflict is with Principle III (below the YAGNI > KISS > UX Consistency > Test Coverage top tier), the upgrade is necessary-not-speculative (YAGNI satisfied), and the override is documented and maintainer-approved per the explicit-override clause. | Accept the complexity justification, but resolve the spec/plan contradiction (findings 1-3) so Complexity Tracking is consistent with the spec it derives from, and ensure the phase boundary is enforced as separate PRs (Phase A SDK bump alone, behavior-unchanged, error pipeline green) so the <30-min reviewability claim is real. No further spec change required for this finding. |
| 11 | MEDIUM | Ambiguity | contracts/telemetry-contract.md:37 vs data-model.md:12,18 | C2 declares `get sendUsageTelemetry(): boolean | undefined` (undefined passed through), while data-model Entity 1 (line 12) and validation rules (line 18) say the CI default for an unset flag is `false`. The artifacts do not state WHERE the CI→false defaulting happens (in the getter, which C2 types as possibly undefined, or in the downstream consent-gating logic). An implementer could apply it in either place, yielding two different getter-contract behaviors. | Specify the layer that resolves the unset-in-CI default to `false` (e.g. 'the getter returns undefined; the consent-gating step treats undefined-in-CI as false') so the getter and gating contracts are unambiguous. |
| 12 | LOW | Consistency | spec.md:147 vs FR-007 (spec.md:104), data-model.md:17, contract C2 (telemetry-contract.md:42) | FR-007, data-model Entity 1, and C2 state the init condition precisely as '(sendCrashReports OR sendUsageTelemetry) AND SENTRY_DSN set'. The assumption at spec.md:147 states the intent loosely ('Sentry is initialized if either is true') but omits the AND SENTRY_DSN conjunct, risking an implementer initializing Sentry without a DSN. | Align spec.md:147 with the FR-007 wording: 'Sentry is initialized if either flag is true AND SENTRY_DSN is set.' |
| 13 | LOW | Traceability | contracts/telemetry-contract.md:56-60 (C4) | C4 introduces `tracesSampleRate: <chosen>` and `enableLogs: true` in `Sentry.init`. These trace to research D1 (research.md:16) and the transport-viability spike (lines 72-73,95) — decision-anchored, not free-invented — but have no direct FR (FR-007 only mandates that Sentry is initialized when a flag is set, not these options). Acceptable as a recorded-decision derivation; flagged for traceability completeness. | Add a one-line pointer in C4 (and/or FR-007) noting `tracesSampleRate`/`enableLogs` derive from research Decision 1; confirm the `<chosen>` sample rate is decided before implementation (see finding 8). |
| 14 | LOW | Coverage | spec.md:120 (OS-001) / quickstart.md / contract C3 (telemetry-contract.md:50) | OS-001 (CHECKPOINT_DISABLE retained across 13 CI locations) and OS-002 are out of scope, but contract C3 asserts 'backward-compatible with the 13 CI workflow locations' as a testable claim with no quickstart verification step. Minor gap: the 13-CI-site backward-compat assertion is stated but never exercised by any journey. | Either note that OS-001 backward-compat is verified implicitly by Journey 3 (CHECKPOINT_DISABLE suppresses usage telemetry), or add an explicit assertion that no CI workflow file is modified, to close the C3 → quickstart trace. |
| 15 | LOW | DecisionIntegrity | spec.md:5-6 (Status: Draft) vs plan.md/research.md/data-model.md/contracts/quickstart (all 2026-06-08, v10) | spec.md is still 'Status: Draft' carrying the 7.120.4 framing, while every Phase 0/1 artifact has moved to the finalized v10 decision. This Draft-vs-finalized mismatch is the root cause of the stale-wording findings (1-6); the spec was never re-baselined after Decision D1. | Re-baseline spec.md against Decision D1 (update FR-002/FR-003, US2, Assumptions, edge cases per findings 1-6) and advance Status from Draft, or add a dated note at the top stating the v10 decision supersedes the original 7.x transport assumptions. |
| 16 | INFO | Consistency | spec.md:161 vs spec.md:163 | The 2026-06-07 revalidation bullet (line 161) concludes 'Plan holds; refinements folded in' and still endorses the `Sentry.metrics.metricsAggregatorIntegration()` (FR-003) wording, immediately before line 163 records the 2026-06-08 transport-invalidating finding and the 7→^10.56 decision. Read top-to-bottom the section contradicts itself within the same block. | Add a forward-reference on line 161 (e.g. 'superseded by the 2026-06-08 transport-viability finding below') so the revalidation bullet no longer endorses the now-invalidated FR-003 wording. |

## Coverage Summary

| Requirement | Plan | Contract | Quickstart scenario | Status |
|-------------|------|----------|---------------------|--------|
| FR-001 | ✓ | ✓ (C1, C6) | Journey 1 | Covered |
| FR-002 | ✓ | ✓ (C1) | Journey 2, 5 | Covered (spec wording stale — finding 2) |
| FR-003 | ✓ | ✓ (C4) | Journey 2 | Covered (spec mandates dead mechanism — finding 1) |
| FR-004 | ✓ | ✓ (C1) | ✗ | Gap (no journey verifies preserved signature / 7 call sites) |
| FR-005 | ✓ | ✓ (C2) | Journey 2/3 (preset flags) | Covered |
| FR-006 | ✓ | ✓ (C3) | Journey 3 | Covered |
| FR-007 | ✓ | ✓ (C2) | Journey 4, 5 | Covered |
| FR-008 | ✓ | ✓ (C2, one-line) | ✗ | Gap (prompt path never exercised — finding 9) |
| FR-009 | ✓ | ✓ (C4) | Journey 4 | Covered |
| FR-010 | ✓ | ✓ (C4, C6) | Journey 4 | Covered |
| FR-011 | ✓ | ✓ (C6) | Journey 1 / 6 | Covered |
| FR-012 | ✓ | ✓ (C6) | Journey 1 | Covered |
| FR-013 | ✓ | ✓ (C5) | Journey 6 | Covered |
| SC-001 | ✓ | ✓ (C1, C6) | Journey 1 | Covered |
| SC-002 | ✓ | ✓ (C1, C5) | Journey 2, 6 | Covered (no spec-level metric-name definition — finding 7) |
| SC-003 | ✓ | ✓ (C3) | Journey 3 | Covered |
| SC-004 | ✓ | ✓ (C4) | Journey 4 | Covered |
| SC-005 | ✓ | ✓ (C5) | Journey 2, 6 | Covered |
| SC-006 | ✓ (Phase D) | ✗ | Journey 6 (partial) | Gap (broad integration-suite pass asserted, not journey-mapped) |
| SC-007 | ✓ | ✓ (C6) | Journey 1, 6 | Covered |

**Coverage gaps**: FR-004 (preserved `sendTelemetry(command, payload)` signature / 7 call sites — only data-model's call-site map, no journey); FR-008 (first-use consent prompt, non-CI only / CI-no-prompt — one-line C2 bullet only, Journeys 2-5 preset flags); SC-006 (full integration-suite pass asserted in plan Phase D, only Journey 6's gated CI jest maps); SC-002 metric-name definition (canonical names exist only in data-model.md/contracts, no FR anchor); OS-001 13-CI-site backward-compat (C3 asserts, no journey).

## Decision Integrity Checklist

| Decision | Applied consistently? | Stale wording found |
|----------|----------------------|---------------------|
| D1 — upgrade `@sentry/node` 7→^10.56 + v10 metrics API (`Sentry.metrics.count`); 7.x Metrics Beta sunset 2024-10-07 | ✗ (applied in plan/research/data-model/contracts/quickstart; NOT in spec) | spec.md:97 (FR-003 `metricsAggregatorIntegration()`); spec.md:96 (FR-002); spec.md:32 (US2 'no SDK upgrade needed', `increment()`); spec.md:34 (US2 test `increment()`); spec.md:85,152 (no-op against 7.x surface); spec.md:146 ('no SDK upgrade required'); spec.md:160 ('Confirmed SDK supports metrics without upgrade'); spec.md:161 (endorses FR-003 wording) |
| D4 — delivery oracle: real v10 client + capturing transport (mock-only test insufficient) | ✗ (applied in C5; NOT in spec) | spec.md:34 (US2 Independent Test prescribes mock-only `increment()` assertion) |
| Typed `ConfigBase` pattern for `sendUsageTelemetry` (per merged `importExtension` feature) | ✓ | none |
| CI count 14→13 (CHECKPOINT_DISABLE locations) | ✓ | none |
| `tracesSampleRate` concrete value | ✗ (left `<chosen>` in C4 — undecided) | contracts/telemetry-contract.md:57 |

## Reverse Traceability

Contract behaviors and quickstart scenarios that do NOT trace cleanly back to a spec requirement (invented behavior):

- Metric names `cli.command.invoked`, `cli.synth.duration`, `cli.command.error` (data-model.md:35,51-56; contract C1; quickstart Journeys 2/3/6) — derived from FR-002 but not enumerated by any FR; `cli.command.error` additionally has no FR anchor and ambiguous gating vs FR-009 (finding 7).
- `tracesSampleRate: <chosen>` and `enableLogs: true` (C4) — anchored to research Decision D1, not to any FR; acceptable recorded-decision derivation, flagged for completeness (finding 13).

## Constitution Compliance

MUST-principle conflicts (automatically CRITICAL): **none**. The only constitutional tension is Principle III (Minimal Viable Change / PRs <30 min) vs the bundled `@sentry/node` 7→10 major upgrade. Principle III is below the priority-hierarchy top tier (YAGNI > KISS > UX Consistency > Test Coverage), the upgrade is necessary-not-speculative, and the override is documented and maintainer-approved per the explicit-override clause — so it does not escalate to CRITICAL. Tracked as finding 10 (MEDIUM), contingent on resolving the spec/plan contradiction (findings 1-3) and enforcing the Phase A PR boundary.

## Metrics

- Total requirements (FR + SC): 20 (13 FR + 7 SC)
- Requirements fully covered: 16 (80%)
- Total tasks: 0 (tasks.md intentionally not generated)
- Critical issues: 3

## Next Actions

1. **Re-baseline spec.md off Draft against Decision D1 (CRITICAL — findings 1, 2, 3, 15).** Rewrite FR-003 to require `@sentry/node ^10.56` + `Sentry.metrics.count(...)` + `enableLogs`/`tracesSampleRate`, removing all `metricsAggregatorIntegration()` / 7.120.4 wording; update FR-002, US2 ('Why this priority' and Independent Test), and the line-85 edge case to the v10 API; replace the line-146/160 Assumptions/research claims with 'SDK upgrade REQUIRED'; advance Status from Draft.
2. **Fix the US2 Independent Test to the C5 delivery oracle (HIGH — finding 4).** Real v10 client + capturing transport asserting a `trace_metric` envelope for `cli.command.invoked` and `await Sentry.flush(2000) === true`; reserve mocking for gating-only unit tests.
3. **Re-ground stale 7.x API wording in Assumptions and edge cases (HIGH/MEDIUM — findings 5, 6).** Drop the `increment/.distribution/.set/.gauge` enumeration (lines 151-152); phrase the no-op-when-uninitialized requirement transport-neutrally on `Sentry.metrics.count`.
4. **Pin `tracesSampleRate` and anchor v10 init options (MEDIUM/LOW — findings 8, 13).** Decide a concrete value in research.md/plan.md and reference it from C4; add the D1 pointer for `tracesSampleRate`/`enableLogs`.
5. **Close coverage gaps (MEDIUM — findings 9, 7).** Add a quickstart journey for the FR-008 consent prompt (non-CI → prompt, CI → no prompt); add an FR (or annotate data-model/C1) enumerating canonical metric names and clarify `cli.command.error` gating vs FR-009.
6. **Disambiguate the CI-default layer and DSN conjunct (MEDIUM/LOW — findings 11, 12).** State where unset-in-CI resolves to `false`; align spec.md:147 with the FR-007 '... AND SENTRY_DSN set' wording.
7. **Resolve remaining low/info items (findings 10, 14, 16).** Enforce the Phase A PR boundary as separate PRs; add the OS-001 13-CI-site backward-compat assertion/note; add the spec.md:161 forward-reference to the 2026-06-08 supersession.
