<!--
  SYNC IMPACT REPORT
  ==================
  Version Change: 1.1.0 → 2.0.0 (MAJOR - principle removal + redefinition)

  Removed Principles:
  - IV. Community Alignment (process concern, enforced by specledger.io approvals)

  Merged Principles:
  - V. API Consistency + VIII. Cross-Language Parity → IV. Cross-Language Consistency
    (JSII enforces API parity by design; merged to focus on scaffolding/tooling gaps)

  Renumbered Principles:
  - VI. Predictable Behavior → V. Predictable Behavior
  - VII. Progressive Disclosure → VI. Progressive Disclosure
  - IX. Test Coverage → VII. Test Coverage
  - X. Quickstart-Driven Testing → VIII. Quickstart-Driven Testing

  Added Principles: None (X. Quickstart-Driven Testing was added in v1.1.0)

  Templates Requiring Updates:
  - .specledger/templates/plan-template.md: ✅ Updated (v1.1.0, still compatible)
  - .specledger/templates/spec-template.md: ✅ Compatible
  - .specledger/templates/tasks-template.md: ✅ Updated (v1.1.0, still compatible)

  Deferred Items: None
-->

# CDK Terrain Constitution

## Core Principles

### I. YAGNI (You Aren't Gonna Need It)

Only implement features when there is a current, concrete use case. Speculative abstractions, premature optimizations, and "future-proofing" are prohibited.

**Rules:**
- Every code addition MUST have an immediate, demonstrable need
- "We might need this later" is NOT a valid justification
- Remove unused code paths immediately; do not comment them out
- No configuration options for hypothetical scenarios
- Abstractions are earned through repetition (Rule of Three), not anticipated

**Rationale:** Unused code increases maintenance burden, cognitive load, and attack surface without providing value.

### II. KISS (Keep It Simple)

Prefer simple, readable solutions over clever ones. Minimize layers of abstraction. Code should be understandable by newcomers within minutes, not hours.

**Rules:**
- Choose boring technology over novel solutions
- Limit inheritance depth to 3 levels maximum
- Prefer composition over inheritance
- Avoid metaprogramming unless absolutely necessary
- If a solution requires extensive documentation to understand, simplify it
- Three similar lines of code is better than a premature abstraction

**Rationale:** Simple code is easier to debug, maintain, and extend. Complexity compounds over time.

### III. Minimal Viable Change

Each PR/change MUST do one thing well. Avoid bundling unrelated improvements.

**Rules:**
- Bug fixes do NOT include surrounding code cleanup
- Feature additions do NOT include unrelated refactoring
- One logical change per commit
- PRs should be reviewable in under 30 minutes
- If a change requires multiple reviewers with different expertise, split it

**Rationale:** Small, focused changes are easier to review, test, and revert if problems arise.

## User Experience Standards

### IV. Cross-Language Consistency

TypeScript is the single source of truth for all library APIs via JSII. Language-specific code (scaffolding templates, post-scaffold hooks, WASM bridges, runtime shims) MUST maintain equivalent behavior across all supported languages.

**Rules:**
- Library API parity is enforced by JSII; do NOT duplicate or override JSII-generated interfaces
- Scaffolding templates MUST provide equivalent project structure and developer experience per language
- Language-specific post-scaffold hooks MUST produce equivalent build/dependency setup
- WASM bridge changes MUST be tested against all consuming language contexts
- Language-specific limitations MUST be documented with workarounds

**Rationale:** Users choose CDK Terrain for multi-language support. JSII guarantees API parity but scaffolding and tooling gaps erode the cross-language promise.

### V. Predictable Behavior

No surprises. Users MUST be able to reason about system behavior from documentation and type signatures.

**Rules:**
- Side effects MUST be documented in method signatures or names
- Default values MUST prioritize safety over convenience
- Error messages MUST be actionable: include what went wrong, why, and how to fix it
- Implicit behaviors (auto-imports, auto-conversions) MUST be minimal and documented
- Breaking changes MUST be detectable at compile/synth time, not runtime

**Rationale:** Predictable systems build user trust and reduce support burden.

### VI. Progressive Disclosure

Simple use cases require simple code. Advanced features available but not in the way.

**Rules:**
- Hello-world examples MUST work with minimal configuration
- Sensible defaults MUST cover 80% of use cases
- Advanced options available via explicit opt-in, not required understanding
- Documentation MUST present simple examples before advanced ones
- Configuration complexity MUST scale with use case complexity

**Rationale:** Low barrier to entry enables adoption; advanced features retain power users.

## Quality Standards

### VII. Test Coverage

All changes to core libraries require appropriate test coverage.

**Rules:**
- Core library changes MUST include unit tests
- Public API changes MUST include integration tests
- Bug fixes MUST include regression tests
- Test coverage percentage MUST NOT decrease
- Tests MUST be deterministic: no flaky tests allowed in CI

**Rationale:** Tests are the specification; untested code is undefined behavior.

### VIII. Quickstart-Driven Testing

The quickstart.md produced during plan Phase 1 is the canonical source of expected user journeys. Every step MUST be directly translatable into an integration test scenario.

**Rules:**
- Each quickstart.md step MUST map to at least one integration test scenario
- CLI-facing changes MUST have corresponding integration tests derived from quickstart steps
- If a quickstart step cannot be automated as a test, it MUST be flagged as NEEDS CLARIFICATION in the spec
- Integration tests MUST exercise the same commands, flags, and expected outputs documented in quickstart.md
- Quickstart.md validation is NOT a polish-phase task; it MUST be verified per user-story phase

**Rationale:** Quickstart docs that diverge from tested behavior become misleading. Treating quickstart steps as test cases ensures documentation accuracy, catches CLI regressions, and guarantees that the plan>research output has a verifiable integration contract.

## Governance

### Amendment Procedure

1. Propose changes via specledger.io spec approval workflow
2. Maintainer approval required for all amendments
3. Migration plan required for any principle that affects existing code
4. Update all dependent templates and documentation before merging

### Versioning Policy

Constitution versions follow semantic versioning:
- **MAJOR**: Principle removal, redefinition, or backward-incompatible governance change
- **MINOR**: New principle added or existing principle materially expanded
- **PATCH**: Clarifications, typo fixes, non-semantic refinements

### Compliance Review

- All PRs MUST verify compliance with constitution principles
- Reviewers MUST cite relevant principles when requesting changes
- Complexity that appears to violate KISS or YAGNI MUST include written justification in PR description

### Principle Hierarchy

When principles conflict, apply in this order:
1. **YAGNI** - Do not build what is not needed
2. **KISS** - Keep the solution simple
3. **UX Consistency** - Maintain user experience standards
4. **Test Coverage** - Ensure quality through testing

Explicit override allowed with documented rationale approved by maintainer.

**Version**: 2.0.0 | **Ratified**: 2026-01-14 | **Last Amended**: 2026-03-20
