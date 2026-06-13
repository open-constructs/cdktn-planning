# Specification Analysis Report — {{FEATURE_ID}}

**Feature**: {{FEATURE_NAME}}
**Date**: {{DATE}}
**Reviewers**: {{N}} independent passes (merged)
**Scope**: spec.md ↔ plan.md, research.md, data-model.md, contracts/*, quickstart.md (no tasks.md — intentional)

## Summary

{{One-paragraph verdict: is the spec internally consistent and fully covered by the planning artifacts? Headline the most serious issue.}}

| Severity | Count |
|----------|-------|
| CRITICAL | {{n}} |
| HIGH     | {{n}} |
| MEDIUM   | {{n}} |
| LOW      | {{n}} |
| INFO     | {{n}} |

## Findings

| # | Severity | Category | Location | Summary | Recommendation |
|---|----------|----------|----------|---------|----------------|
| 1 | {{sev}} | {{Coverage\|Traceability\|Consistency\|DecisionIntegrity\|Constitution\|Ambiguity}} | {{file:line}} | {{what}} | {{fix}} |

## Coverage Summary

One row per Functional Requirement (FR-*) and Success Criterion (SC-*). Mark downstream coverage in plan / contract / quickstart scenario.

| Requirement | Plan | Contract | Quickstart scenario | Status |
|-------------|------|----------|---------------------|--------|
| FR-001 | {{✓/✗}} | {{✓/✗}} | {{Journey n / ✗}} | {{Covered / Gap}} |

**Coverage gaps**: {{list FR-*/SC-* with no downstream coverage, or "none"}}

## Decision Integrity Checklist

Each recorded clarification/decision applied consistently everywhere, no stale wording.

| Decision | Applied consistently? | Stale wording found |
|----------|----------------------|---------------------|
| {{D-n / clarification}} | {{✓/✗}} | {{location or "none"}} |

## Reverse Traceability

Contract behaviors and quickstart scenarios that do NOT trace back to a spec requirement (invented behavior): {{list or "none"}}

## Constitution Compliance

MUST-principle conflicts (automatically CRITICAL): {{list or "none"}}

## Metrics

- Total requirements (FR + SC): {{n}}
- Requirements fully covered: {{n}} ({{pct}}%)
- Total tasks: 0 (tasks.md intentionally not generated)
- Critical issues: {{n}}

## Next Actions

1. {{ordered, concrete, by severity}}
