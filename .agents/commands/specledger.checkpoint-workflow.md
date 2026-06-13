---
name: specledger.checkpoint-workflow
description: Critical divergence review — compare implementation against plan artifacts, flag divergence from plan, and surface gaps. Updates session log at FEATURE_DIR/sessions/<branch-name>-checkpoint.md
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

**Execution Tracking**: Before starting work, create a task list (using the TaskCreate tool) covering all execution steps in this workflow. If `$ARGUMENTS` contains user-specified actions beyond the standard workflow, place those tasks where they logically fit: before setup steps if arguments change what gets set up, or after all standard steps if arguments extend the workflow. Update task status as you complete each step.

**User Interaction**: Whenever you need input, clarification, or a decision from the user, use the **AskUserQuestion** tool directly. Do not output questions as plain text and stop — always use the interactive tool for proper UX.

## Purpose

Perform a critical divergence review of the current implementation state against plan artifacts. Your job is to **find problems, not confirm success**. Surface plan drift, uncovered requirements, and implementation gaps that human reviewers need to know about before merge.

**When to use**: During or after implementation to catch drift, before handoff, or before merging.

## Framing

Adopt an adversarial reviewer mindset. Assume the implementation has gaps until proven otherwise.

## Outline

Goal: Identify divergences between planned and actual implementation, classify them, and produce an actionable review.

Execution steps:

1. Run `sl spec info --json --paths-only` to get `FEATURE_DIR` and `BRANCH`.

2. Gather implementation state: Use git to see the staged changes

3. Run project tests and checks:
   - Consult the project's `CLAUDE.md` (or equivalent) for the canonical test/lint/format commands.
   - If no project-level instructions exist, detect the project type and use conventional commands:
     - **Go**: `go test ./...`
     - **Node (npm/pnpm/yarn)**: check `package.json` for `test`, `lint`, `format:check` scripts and run those that exist
     - **Python**: `pytest` or the configured test runner
     - **Other**: look for a `Makefile`, `justfile`, or CI config for test commands
   - If no test runner is configured, state that explicitly — do not fabricate a test step
   - All executed checks must pass (exit code 0) for a clean checkpoint
   - If any check fails, report failures and include them as CRITICAL divergences

4. Compare implementation against plan artifacts:

   Read the following from `FEATURE_DIR` (skip any that don't exist):

   **From spec.md:**
   - Functional requirements (FR-xxx or numbered list)
   - User stories and their acceptance criteria
   - Non-functional requirements
   - Edge cases
   - Derive Definition of Done per User Story acceptance criteria **Example conversion**:
      - Spec acceptance: "Then the user can log in with valid credentials"
      - DoD item: "- User can authenticate with valid username/password"
      - Spec acceptance: "Then invalid credentials show an error message"
      - DoD item: "- Invalid credentials display appropriate error message"
   - Also verify:
      - quickstart.md scenario(s) match this story's user stories
      - TestQuickstart_<scenario> integration test(s) exist and pass for each scenario

   **From plan.md:**
   - Phases and their deliverables
   - Project structure (expected files/components)
   - Architecture decisions and constraints

   **From data-model.md** (if present):
   - Entity names and key fields
   - Validation rules
   - Relationships

   **From quickstart.md** (if present):
   - Integration scenarios
   - Expected output formats

   For each artifact claim, check:
   - Does the implementation match the specification? (Check actual code if uncertain.)
   - Are there planned files/components that don't exist?
   - Are there data model entities defined but not implemented, or implemented differently?
   - Are there quickstart scenarios not validated by tests?

5. Classify each divergence:

   **Severity** (use same scale as `/specledger.verify`):
   - **CRITICAL**: Missing core requirement, failing tests, security/compliance gap
   - **HIGH**: Significant unchecked DoD, requirement partially implemented, test gap for critical path
   - **MEDIUM**: Data model drift, terminology inconsistency, undocumented architecture change
   - **LOW**: Minor format difference, non-critical edge case not covered

   **Type** — Leverage any Decision in the session log:
   - **conscious**: Divergence is documented somewhere (decision log, commented source code, ...)
   - **oversight**: No documentation found — this was likely missed

6. Update session log:
   - Create `FEATURE_DIR/sessions/` directory if it doesn't exist
   - **Determine output file based on scope**:
     - **Phase-scoped checkpoint**: If `$ARGUMENTS` indicates a phase scope (e.g., `"Verify phase:setup issues only"`), write to `FEATURE_DIR/sessions/<branch-name>-checkpoint-<phase-name>.md`. One file per phase, overwriting any prior phase-scoped checkpoint for the same phase.
     - **Full checkpoint** (no phase scope): Append a timestamped entry to `FEATURE_DIR/sessions/<branch-name>-checkpoint.md`.
   - Use the entry format below

   ```markdown
   ## Divergence Review: YYYY-MM-DD HH:MM

   ### Divergences

   | # | Severity | Type | Category | Artifact | Description |
   |---|----------|------|----------|----------------|-------------|
   | 1 | HIGH | oversight | Missing requirement | spec.md FR-003 | Rate limiting not implemented |
   | 2 | MEDIUM | conscious | Data model drift | SL-xxx / data-model.md | Field renamed from X to Y (documented in source code) |

   ### DoD Bypassed

   | User Story | Title | Acceptance Criteria | Risk |
   |------------|-------|---------------------|------|
   | US1 | Add validation | "Integration test passes" unchecked | HIGH — no test coverage |

   ### Issues Encountered & Resolutions
   - <What went wrong> → <How it was resolved or worked around>

   ### Items Requiring Action Before Merge
   1. [CRITICAL] Fix <specific gap> — <why it matters>
   2. [HIGH] Write test for <scenario> — <what's at risk>

   ### Tests & Checks
   - Status: PASS/FAIL/SKIPPED
   - Commands run: <list of commands executed>
   - Failures: <details if any>

   ---
   ```

7. Report divergence summary to the user:
   - Lead with divergence count and severity breakdown
   - Show the divergence table
   - List items requiring action
   - End with test status and progress numbers
   - If CRITICAL divergences exist, recommend resolving before commit/merge

8. Offer adversarial deep-dive agent:

   After reporting your findings, **always offer** to launch an independent adversarial review agent. This agent runs in a fresh context with no knowledge of the implementation session — it cannot rationalize shortcuts or inherit anchoring bias from prior decisions.

   > **PRECONDITION — commit first / clean working tree.** Before launching the review agent, the working tree SHOULD be committed (or otherwise clean). A thorough reviewer **exercises the real binary** — building, running the app, and running git round-trips (`add`/`commit`/`reset`, integration tests) to confirm behavior — and it may do so **in the repo itself**. That is *fine and encouraged once the tree is clean*: a committed tree means any stray test commit/reset the agent makes can't clobber uncommitted or mis-staged work, and is trivially undone (`git reset --hard <your-HEAD>` / drop the dangling commit). If you launch with uncommitted or partially-staged changes, a reviewer's `git add -A && git commit` can sweep up files you didn't intend and disturb your staging. So: **commit, confirm `git status` is clean, then launch.** Do not instead forbid the agent from using git — the freedom to exercise the binary is what makes the review valuable.

   **When all Definition of Done completed** strongly recommend running the adversarial agent as a best practice before merge. This is the highest-value moment: the work appears complete, so the risk of undetected drift is greatest.

   Otherwise, present it as an optional next step — useful when the checkpoint is mid-implementation and more sessions are expected.

   Generate an adversarial review agent filling in the definition of done derived, per User story into the prompt tempalate below.

   ~~~
   You are an adversarial code reviewer. Your job is to find problems, not confirm success.

   ## Context
   - Feature directory: {FEATURE_DIR}
   - Branch: {BRANCH}
   - This review is context-free by design — you have no prior knowledge of
     implementation decisions or tradeoffs made during development.

   ## Skills — load these FIRST (you have the Skill tool)
   Before reviewing, invoke the Skill tool for the project's design/best-practice
   skills so you judge against the SAME standards the code was meant to meet — not
   ad-hoc taste. Review findings should cite these where relevant. For this Go CLI:
   `agentic-go-cli-design` (errors-as-navigation, two-level output, exit codes,
   `--help`/`--json`/`--verbose`/`--dry-run`/`--force`), plus `golang-code-style`,
   `golang-testing`, and `golang-lint`. (Adapt the set to the repo's language/stack
   and the skills available in the session.)

   ## Instructions

   1. Run `sl spec setup-plan --json` from repo root and parse JSON for FEATURE_SPEC, IMPL_PLAN, SPECS_DIR, BRANCH
   2. Read the spec, plan, and any design artifacts in {FEATURE_DIR}.
   3. Focus on these definition of done items per user story:
      <FOR EVERY USER STORY>
         x. User Story: 
             - <definition of done item 1>
             - <definition of done item 2>
           Also verify:
             - quickstart.md scenario(s) match this story's user stories
             - TestQuickstart_<scenario> integration test(s) exist and pass for each scenario
      </FOR EVERY USER STORY>
      
   4. Read the actual implementation code on this branch. For each requirement and
      planned deliverable, verify it exists and behaves as specified.
   5. Run the project's test/lint commands (check CLAUDE.md for canonical commands).
   6. Produce a findings report:
      - Divergences (severity + conscious/oversight classification)
      - User Stories and Acceptance Criteria with unchecked DoD items
      - Code quality concerns (dead code, missing error handling, untested paths)
      - Requirements with no corresponding implementation
      - Implementation that has no corresponding requirement (scope creep)
   7. Be specific: cite file paths, line numbers, user story IDs, and artifact references.
   8. Report findings only — do not fix anything.
   ~~~

   Show the generated print output to the user and Use AskUserQuestion to ask: **"Would you like me to launch an independent adversarial review agent?"** This runs in a separate context with no memory of this session — it reviews the code and artifacts cold. 

## Behavior Rules

- **Lead with divergences, not accomplishments** — the progress summary is an appendix
- **Flag unchecked DoD** this is always worth reporting
- **Classify every divergence** as conscious or oversight by checking source code and decision logs
- **If zero divergences found**, report that explicitly — this is a positive signal worth stating, not a default
- All executed tests/checks must pass for a clean checkpoint
- Don't auto-commit — prompt user instead
- If CRITICAL divergences exist, strongly recommend resolving before merge
- If no progress since last checkpoint, report "no changes detected"
- Include file paths for uncommitted changes

## Example Usage

```bash
# Critical divergence review after implementation
/specledger.checkpoint

# Review with specific focus area
/specledger.checkpoint "Focus on data model alignment and test coverage"

# Pre-merge divergence review
/specledger.checkpoint "Pre-merge review for PR #42"

# Checkpoint with known context
/specledger.checkpoint "We switched from go-vcr to httptest — flag that as conscious"
```

## Session Log Format

Session logs are stored at `FEATURE_DIR/sessions/<branch-name>-checkpoint.md`:

```markdown
# Session Log: <branch-name>

## Divergence Review: 2026-03-05 14:30

### Divergences

| # | Severity | Type | Category | Artifact | Description |
|---|----------|------|----------|----------------|-------------|
| 1 | HIGH | oversight | Missing requirement | spec.md FR-009 | JSONL fallback on 404 not implemented — only shows warning |
| 2 | LOW | conscious | Architecture change | plan.md Phase 2 | Used httptest instead of go-vcr cassettes |
| 3 | MEDIUM | oversight | Test gap | quickstart.md Scenario 12 | TestPlanShowCacheReuse never written |

### DoD Missing

| User Story | Title | Unchecked DoD Items | Risk |
|-------|-------|---------------------|------|
| US1 | go-vcr cassette setup | "Cassette file created", "Replay test passes" | LOW — httptest approach covers same ground |
| US2 | TestPlanShowCacheReuse | "Test implemented", "Cache hit verified" | MEDIUM — no test for cache reuse path |

### Issues Encountered & Resolutions
- TestParsePlanJSONSensitive failed: sensitive values compared equal → added isSensitive flag
- TestRunCancelJSON mock returned non-cancelable state → fixed mock to return cancelable first

### Items Requiring Action Before Merge
1. [HIGH] Fix Scenario 11 JSONL fallback (spec.md FR-009 requires it)
2. [MEDIUM] Write TestPlanShowCacheReuse or document why it's deferred
3. [MEDIUM] Verify formatAttrValue output matches quickstart scenarios

### Tests & Checks
- Status: PASS
- Commands run: go test ./pkg/cli/commands/... ./pkg/plan/...
- 21 tests passing

### Uncommitted Changes
- None

---
```
