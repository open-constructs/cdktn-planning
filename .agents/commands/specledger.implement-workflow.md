---
name: specledger.implement-workflow
description: EXPERIMENTAL — implement the current feature by fanning the plan/contracts out to subagents via a deterministic Workflow (interface-first pipeline → primitives → add/verify → CLI → tests → make-check-until-green), instead of /specledger.tasks + /specledger.implement. Run from a FRESH session at DEFAULT effort for cost.
handoffs:
  - label: Checkpoint For Consistency
    agent: specledger.checkpoint
    prompt: Run critical divergence review
---

## User Input

```text
$ARGUMENTS
```

Optional `$ARGUMENTS`: a phase-scope override (e.g. "skillcore only", "skip docs/skill phase") or a feature id. If empty, implement the full current feature.

## Purpose

Run **one deterministic multi-agent Workflow** that reads the design artifacts and fans the implementation out to subagents. This is an **experiment**: it deliberately **skips the durable `sl issue` ledger** — the **quickstart scenarios + `make check` are the acceptance gate** instead.

> **AskUserQuestion which model to use advise switching effort (it is inherited).** This script leaves `model` **unset** on every `agent()` (the override is optional — it defaults to the launcher's session model), this can keep the fanned-out agents cheap. The workflow author can add `model:` per `agent()` if a specific tier is wanted.

## Execution steps

1. **Locate artifacts**: run `sl spec info --json --paths-only`. Read from `FEATURE_DIR`: `plan.md`, `research.md`, `data-model.md`, `contracts/*.md`, `quickstart.md`. These are the source of truth — the agents will Read them too.
2. **Discover relevant skills**: enumerate the skills available in the session (the available-skills list surfaced by the harness; or invoke `/find-skills` for a gap). **Map each pipeline phase to the skills that govern that work** — e.g. Go code style, lint, cobra, agentic CLI design, Go testing. Workflow subagents **do** have the `Skill` tool (verified empirically), so every agent prompt **can and MUST** instruct the agent to load its relevant skills via the `Skill` tool *before* writing code. Record the phase→skills map you'll bake into the prompts.
3. **Author + launch the Workflow** following the pipeline below. It is a **dependency-ordered pipeline**, not a wide fan-out, because the Go code must compile together. Every `agent()` prompt MUST open with a `SKILLS:` directive (see the mandatory rule below).
4. When the workflow completes, **report**: files written, the final `make check` result, and any remaining failures. Do **not** create `sl issue` entries (the experiment skips the durable ledger).

## Skill loading is mandatory (not optional)

> **Every `agent()` prompt MUST begin with a `SKILLS:` line** naming the skills to invoke via the `Skill` tool and apply *before* doing the work. Design artifacts say *what* to build; the skills carry *how this repo builds it* (idioms, lint rules, cobra/CLI-design conventions, test patterns) — relying on the artifacts alone leaves that on the table. Workflow subagents have the `Skill` tool, so this works directly; do **not** distill skill content into the prompt by hand and do **not** assume an agent will load a skill unprompted.

Here is an example phase to skill mapping, adjust to your discovered skill set and the feature's needs (this is the Go/CLI default):

**Phase → skill mapping (adapt to the discovered skill set; this is the Go/CLI default):**

| Phase | Skills the agent loads first |
|---|---|
| Scaffold | `golang-code-style` |
| Primitives | `golang-code-style` (+ `golang-cli` for any exec/IO/git-client file) |
| Operations | `golang-code-style` |
| CLI | `agentic-go-cli-design` + `golang-spf13-cobra` + `golang-cli` |
| Tests | `golang-testing` |
| Verify / repair | `golang-lint` + `golang-code-style` |
| Doc sync | `agentic-go-cli-design` |

Map by *relevance*, not volume: 1–3 skills per agent. Loading skills unrelated to a phase just burns context.

## Workflow pipeline (author this script)

```
export const meta = {
  name: 'implement-feature',
  description: 'Implement <feature> from its plan/contracts; gate on make check',
  phases: [
    { title: 'Scaffold' }, { title: 'Primitives' }, { title: 'Operations' },
    { title: 'CLI' }, { title: 'Tests' }, { title: 'Verify' },
  ],
}
const FD = args.featureDir   // pass FEATURE_DIR in via Workflow `args`

// Every prompt OPENS with a `SKILLS:` directive — the agent invokes those skills
// via the Skill tool and applies them before writing code (mandatory rule above).

// Phase 1 — Scaffold (interface-first): ONE agent pins the exact public API.
phase('Scaffold')
await agent(`SKILLS: invoke "golang-code-style" via the Skill tool and apply it. Then: read ${FD}/contracts/skillcore-sdk.md and ${FD}/data-model.md. Create pkg/skillcore/ with the EXACT exported types + function signatures (Manifest, Require, LockFile, LockEntry, AddOptions, AddResult, Report, Verdict, Counts, VerifyFailure, GitError) and stub bodies returning errors.New("not implemented"). Ensure 'go build ./...' compiles. Touch ONLY pkg/skillcore/.`,
  { phase: 'Scaffold', label: 'scaffold' })

// Phase 2 — Primitives in parallel (disjoint files).
phase('Primitives')
await parallel([
  () => agent(`SKILLS: invoke "golang-code-style" AND "golang-cli" via the Skill tool and apply them (this is the exec/IO/git boundary). Then: implement pkg/skillcore/git.go: a small git client (pluggable commandContext field + GitError{ExitCode,Stderr}, gh-cli pattern) with revParse and statusPorcelain helpers. Read ${FD}/research.md (D1,D7) and ${FD}/contracts/skillcore-sdk.md. Touch ONLY git.go.`, { phase: 'Primitives', label: 'git' }),
  () => agent(`SKILLS: invoke "golang-code-style" via the Skill tool and apply it. Then: implement pkg/skillcore/treesha.go: TreeSHA(gitDir,ref,relPath) = shell 'git -C gitDir rev-parse <ref>:<relPath>'. Read ${FD}/research.md (D1) + ${FD}/data-model.md. Touch ONLY treesha.go.`, { phase: 'Primitives', label: 'treesha' }),
  () => agent(`SKILLS: invoke "golang-code-style" via the Skill tool and apply it. Then: implement pkg/skillcore/manifest.go: ParseManifest(skill.toml) via go-toml/v2; ignore unknown keys. Read ${FD}/data-model.md. Touch ONLY manifest.go.`, { phase: 'Primitives', label: 'manifest' }),
  () => agent(`SKILLS: invoke "golang-code-style" via the Skill tool and apply it. Then: implement pkg/skillcore/lock.go: ReadLock/WriteLock for .skillrig/skills-lock.json (atomic temp+rename, deterministic JSON, NO 'requires' field). Read ${FD}/data-model.md (D4). Touch ONLY lock.go.`, { phase: 'Primitives', label: 'lock' }),
])

// Phase 3 — Operations in parallel (depend on primitives).
phase('Operations')
await parallel([
  () => agent(`SKILLS: invoke "golang-code-style" via the Skill tool and apply it. Then: implement pkg/skillcore/add.go: Add(opts) — copy subtree mode-preserving (no injection), treeSha+commit via the git client on the ORIGIN, write lock; force/dry-run/idempotent. Read ${FD}/contracts/add.md + ${FD}/contracts/skillcore-sdk.md. Touch ONLY add.go.`, { phase: 'Operations', label: 'add' }),
  () => agent(`SKILLS: invoke "golang-code-style" via the Skill tool and apply it. Then: implement pkg/skillcore/verify.go: Verify(repoRoot) — label-honesty (TreeSHA on HEAD vs lock) + orphan/completeness + dirty; aggregate ALL findings; read-only; return *VerifyFailure when not ok. Read ${FD}/contracts/verify.md. Touch ONLY verify.go (+ errors.go if needed).`, { phase: 'Operations', label: 'verify' }),
])

// Phase 4 — CLI wiring.
phase('CLI')
await agent(`SKILLS: invoke "agentic-go-cli-design", "golang-spf13-cobra", AND "golang-cli" via the Skill tool and apply them (they encode this repo's CLI contract — errors-as-navigation, two-level output, exit codes, cobra patterns). Then: wire the CLI in internal/cli/: add.go (resolve origin via config.ResolveOrigin, call skillcore.Add, render), verify.go (call skillcore.Verify, render, exit code), extend exit.go so *skillcore.VerifyFailure → ExitVerification(2), output.go renderers (human compact + --json), register both in root.go. Read ${FD}/contracts/{add,verify}.md + ${FD}/plan.md. Match the existing internal/cli style.`, { phase: 'CLI', label: 'cli' })

// Phase 5 — Tests in parallel (RAW git oracle — never skillcore; research D11).
phase('Tests')
await parallel([
  () => agent(`SKILLS: invoke "golang-testing" via the Skill tool and apply it (table-driven, helpers, t.TempDir, idiomatic naming). Then: create test/testdata/sample-origin/ (.skillrig-origin.toml + skills/<skill>/{SKILL.md,skill.toml}, research D12) and test/quickstart_test.go with the TestQuickstart_* scenarios from ${FD}/quickstart.md. Bootstrap fixtures with RAW git (git init/commit) and compute expected tree-SHAs with RAW 'git rev-parse' — NEVER via skillcore (Constitution III, no circular oracle). Touch ONLY test/.`, { phase: 'Tests', label: 'quickstart' }),
  () => agent(`SKILLS: invoke "golang-testing" via the Skill tool and apply it. Then: write pkg/skillcore/*_test.go unit tests: a ground-truth test asserting skillcore.TreeSHA == raw 'git rev-parse' output; lock round-trip; manifest parse; error paths via a stubbed commandContext. Touch ONLY pkg/skillcore/*_test.go.`, { phase: 'Tests', label: 'unit' }),
])

// Phase 6 — Verify + repair (loop on make check until green or budget).
phase('Verify')
let green = false
for (let i = 0; i < 4 && !green; i++) {
  const r = await agent(`SKILLS: invoke "golang-lint" AND "golang-code-style" via the Skill tool and use them to interpret/fix lint+vet+fmt output (nolint only as a justified last resort). Then: run 'make check' (fmt+vet+lint+test). If it passes, report PASS. If not, FIX the smallest set of files to make it pass (respect the contracts; do not weaken tests to pass) and report what you changed. Return JSON {pass:boolean, changed:string[], failures:string}.`,
    { phase: 'Verify', label: `make-check#${i+1}`, schema: { type:'object', properties:{ pass:{type:'boolean'}, changed:{type:'array',items:{type:'string'}}, failures:{type:'string'} }, required:['pass'] } })
  green = r?.pass === true
  log(`make check round ${i+1}: ${green ? 'PASS' : 'fail'}`)
}
return { green }
```

Pass `args: { featureDir: "<FEATURE_DIR>" }` to the Workflow call. After it returns, report `green` + the last round's `failures`/`changed` if not green, and list the files created under `pkg/skillcore/`, `internal/cli/`, `test/`.

## What this deliberately skips (experiment)

- **No `sl issue` ledger** — the durable, team-visible record is *not* produced; the acceptance gate is the quickstart tests + `make check`.
- **No `docs/design/cli.md` / agent-skill update** unless you add a Phase 7 agent (recommended before merge — Constitution IX + the same-branch doc-sync rule).
