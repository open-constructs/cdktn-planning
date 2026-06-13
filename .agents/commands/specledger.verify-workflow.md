---
name: specledger.verify-workflow
description: EXPERIMENTAL — cross-artifact verification WITHOUT tasks.md. Fans out N INDEPENDENT reviewers (spec → plan/research/data-model/contracts/quickstart) via a deterministic Workflow, then MERGES their findings into one report (independent passes catch complementary issues). Read-only. Run from a FRESH session at DEFAULT effort.
handoffs:
  - label: Implement (workflow)
    agent: specledger.implement-workflow
    prompt: Implement the verified feature via the workflow pipeline
---

## User Input

```text
$ARGUMENTS
```

Optional `$ARGUMENTS`: number of independent reviewers (default 2), or extra focus (e.g. "emphasize security", a feature id).

## Purpose

Read-only cross-artifact consistency verification for a feature whose **`tasks.md` was intentionally not generated** (e.g. when using `/specledger.implement-workflow`). It validates **`spec.md` against `plan.md`, `research.md`, `data-model.md`, `contracts/*.md`, and `quickstart.md`** — the planning artifacts — and produces a Specification Analysis Report.

**Why a workflow, not a single pass:** independent reviewers reliably catch *different* things. (Real example: one pass caught a committed-tree-vs-working-tree spec↔plan ambiguity; another caught a stale acceptance scenario the first missed.) So this runs **N independent reviewers in parallel** and **merges** them — keeping complementary findings, deduping overlap.

> **STRICTLY READ-ONLY.** Reviewers and the merge step report findings and recommend fixes; they do **not** edit artifacts. The only write is the optional, explicit save of the report (last step).
> **Do NOT flag the absence of `tasks.md`** — it is intentional for this flow. Skip the task↔requirement and `TestQuickstart_*`-task-mapping checks.

> **Pause for model and effort.** Subagents inherit the launcher's *model* (this script leaves `model` unset). Before launching, **AskUserQuestion which model** the reviewers should use and offer to pause to change effort because **effort is inherited** from the launching session — so a cheap, lower-effort session keeps the fan-out costs under control.

## What each reviewer checks (the four focus areas)

1. **Coverage** — every Functional Requirement (FR-*) and Success Criterion (SC-*) in `spec.md` is covered by the plan + a contract + a `TestQuickstart_*` scenario. Flag any requirement with no downstream coverage.
2. **Reverse traceability** — every contract behavior and every quickstart scenario traces back to a spec requirement (no invented behavior ungrounded in the spec).
3. **Consistency** — no contradictions across artifacts (exit codes, lock schema, fingerprint semantics, origin resolution, etc.); in particular flag any **AMBIGUITY that would let an implementer/model decide a behavior two different ways**.
4. **Decision integrity** — the spec's recorded clarification decisions are applied **consistently everywhere they appear**, with **no leftover stale wording**.

Constitution (`.specledger/memory/constitution.md`) is in scope: a MUST-principle conflict is automatically CRITICAL.

## Execution steps

1. **Locate artifacts**: run `sl spec info --json --paths-only`; read `FEATURE_DIR`. (The reviewers Read the artifacts themselves.)
2. **Discover relevant skills**: enumerate the skills available in the session (the available-skills list surfaced by the harness; or invoke `/find-skills` for a gap). **focus on design skills** — e.g. cobra, agentic CLI design, Supabase Architecture, REST and data modeling. Workflow subagents **do** have the `Skill` tool (verified empirically), so every review agent prompt **can and MUST** instruct the agent to load its relevant design and architecture skills via the `Skill` tool *before* reviewing artifacts. Record the review skills you'll bake into the brief.
3. **AskUserQuestion**: Batch which `model` for the reviewers (note effort is inherited from this session) together with the relevant skills (multiple selections allowed). Pass the `model` (or leave `model` unset to inherit) into the script.
4. **Write the feature-specific reviewer brief to disk** at `FEATURE_DIR/reviews/_reviewer-brief.md` (create `reviews/` if needed). It carries everything reviewer-facing — the **SKILLS line** (the chosen skills to load), the read-only rule, the artifact list, the feature context, the four focus areas, and the constitution note. **Why on disk:** the workflow script is plain JS, and embedding long multi-paragraph prompts as string literals is parse-fragile (a stray `/*` glob, an unescaped backtick/apostrophe, or a mis-counted paren breaks the whole script). Keeping the prose in a file makes the script tiny and robust, and gives a single inspectable/editable source of truth. The report template already lives on disk at `.specledger/templates/review-report-template.md` — reviewers/merge read it rather than re-deriving the format. *(Scaffolding files use a `_` prefix; offer to delete them after the run.)*
5. **Author + launch the Workflow** below (it just hands agents the on-disk paths).
6. When it returns, **present the merged report**. Then **offer to save** it (final step).

## Skill loading is mandatory (not optional)

> The reviewer brief MUST begin with a **`SKILLS:` line** naming the skills to invoke via the `Skill` tool and apply *before* reviewing. Design artifacts say *what* to build; the skills carry *how this repo designs it* — relying on the artifacts alone leaves that on the table. Workflow subagents have the `Skill` tool; do **not** distill skill content into the brief by hand and do **not** assume an agent will load a skill unprompted.

## Workflow pipeline (author this script)

> Keep the script **minimal**: it reads the on-disk brief + report template (step 4) and passes their paths to agents. Do **not** embed long prose, globs (`/*`), or multi-paragraph strings — that is the parse-fragility this disk-based design exists to avoid. Use an explicit `for`-loop to build the thunks (clearer paren-balance than a nested `parallel(Array.from(...))` one-liner).

```
export const meta = {
  name: 'verify-artifacts',
  description: 'Cross-artifact verification (no tasks): N independent reviewers + merge, reading on-disk brief + template',
  phases: [{ title: 'Review' }, { title: 'Merge' }],
}

const FD = args.featureDir
const N = args.reviewers || 2
const MODEL = args.model            // undefined → inherit launcher; or set from the AskUserQuestion answer
const BRIEF = FD + '/reviews/_reviewer-brief.md'
const TEMPLATE = '.specledger/templates/review-report-template.md'

const FINDINGS = { type: 'object', required: ['findings'], properties: {
  findings: { type: 'array', items: { type: 'object',
    required: ['category', 'severity', 'location', 'summary', 'recommendation'],
    properties: {
      category: { type: 'string' },                  // Coverage|Traceability|Consistency|DecisionIntegrity|Constitution|Ambiguity
      severity: { enum: ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'] },
      location: { type: 'string' },                  // file:line(s) or section refs
      summary: { type: 'string' },
      recommendation: { type: 'string' } } } },
  coverageGaps: { type: 'array', items: { type: 'string' } },   // FR-*/SC-* with no downstream coverage
  staleWording: { type: 'array', items: { type: 'string' } } } }

// Phase 1 — N INDEPENDENT reviewers (parallel, fresh context each), schema'd findings.
phase('Review')
const thunks = []
for (let i = 0; i < N; i++) {
  const pass = i + 1
  thunks.push(() => agent(
    'Read ' + BRIEF + ' FIRST and follow it exactly (load the SKILLS it names via the Skill tool before reviewing, obey the read-only rule, read every artifact it lists). You are INDEPENDENT reviewer pass ' + pass + ' of ' + N + '. Perform the four-focus-area cross-verification described in the brief and return findings per the StructuredOutput schema, citing file:line. Edit nothing.',
    { schema: FINDINGS, model: MODEL, phase: 'Review', label: 'reviewer#' + pass }))
}
const passes = (await parallel(thunks)).filter(Boolean)

// Phase 2 — Merge: keep complementary findings, dedup overlap, reconcile severity, fill the on-disk template.
phase('Merge')
const report = await agent(
  'Read the report template at ' + TEMPLATE + ' and emit a single filled copy as your output, following its structure EXACTLY. Merge ' + passes.length + ' independent review passes: KEEP complementary findings, DEDUP true overlaps (same location+claim), reconcile each severity to the highest justified. Fill the coverage table (one row per FR/SC), the decision-integrity checklist, the metrics, and next actions. STRICTLY READ-ONLY. The passes as schema JSON: ' + JSON.stringify(passes),
  { model: MODEL, phase: 'Merge', label: 'merge' })

return { report, reviewers: passes.length }
```

Pass `args: { featureDir: "<FEATURE_DIR>", reviewers: <N>, model: "<choice-or-undefined>" }`.

## Report format

The merge agent fills the on-disk template at **`.specledger/templates/review-report-template.md`** (findings table → coverage summary → decision integrity → metrics → next actions). Present that filled report to the user.

## Final step — offer to save (explicit, opt-in write)

After presenting the report, **AskUserQuestion**: save to `FEATURE_DIR/reviews/<spec-number>-review.md`? If yes, write the report with YAML frontmatter (`date`, `total_requirements`, `total_tasks: 0`, `coverage_pct`, `critical_issues`), creating `reviews/` if needed, and confirm the path. If a review already exists, offer to **merge into it** (mark resolved/open) rather than overwrite blindly.
