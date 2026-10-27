# RFC-06: Examples and Integration Tests Placement

**Status:** Proposal

## Summary

This RFC separates two things that have been conflated under the word "examples" and places each where the current tooling already expects it.

- **Integration tests** — small apps whose job is to exercise the toolchain's seams in CI. They track `main` and must stay green against the current codebase. They already have a home: the monorepo's `test/<language>/<name>/` harness, discovered by jest and run against the built `dist/`. The `edge` provider test is the canonical seam test.
- **Examples** — instructional, real-world sample projects whose job is to teach. They pin the latest released CDKTN version, evolve on their own cadence, and live in a dedicated `cdktn-examples` repo. The public [cdktn.io](https://cdktn.io/docs/examples-and-guides/examples) catalog points only here.

The confusion the RFC removes: an app that validates the toolchain in CI is a *test*, not an *example*, even when it reads like one. The monorepo `examples/` tree currently mixes both. This RFC drains it: validation apps become integration tests under `test/`, instructional apps move to `cdktn-examples`.

## Motivation

The monorepo already runs a mature integration-test harness under `test/`: each test is a `test.ts` entrypoint discovered by `tools/build-test-matrix.mjs` and executed against `dist/` through `run-against-dist.mjs`, across the Terraform/OpenTofu matrix in `.terraform.versions.json`. Separately, a tracked `examples/` tree carries ~700 files of standalone apps, several with their own `__tests__/`.

Those `examples/` apps do two unrelated jobs. Some exist to prove the toolchain still works (they belong with the other integration tests). Others exist to teach a real-world architecture (they belong where learners can find them, pinned to a release). Keeping both under one `examples/` label means the CI apps get judged on readability and the teaching apps get judged on CI coverage, and neither fits. Worse, it duplicates the `test/` harness: `examples/typescript/aws-prebuilt/__tests__/` is an integration test wearing an example's clothes.

Naming the two categories distinctly makes placement mechanical and routes each to infrastructure that already exists.

## Problem Statement

The `cdk-terrain` monorepo carries a tracked `examples/` tree organized by language, mixing CI-validation apps and instructional apps, while a separate, purpose-built integration-test harness already lives under `test/`. The high-complexity instructional projects listed in the docs catalog are not in the monorepo at all. Nothing in the layout distinguishes a CI fixture from a teaching sample, so there is no rule for where a new one goes — and validation apps are being maintained in two places.

## Goals

Draw a clear line between integration tests and examples, route integration tests into the existing `test/` harness instead of a parallel `examples/` tree, move instructional examples to `cdktn-examples` pinned to the latest release, point the public docs at that repo as the single user-facing source, and provide a repeatable procedure for adding each kind.

## Non-Goals

This RFC does not change the `test/` harness mechanics (`build-test-matrix.mjs`, `run-against-dist.mjs`, the version matrix), rewrite construct code, or alter the docs catalog structure. It does not define the `cdktn-examples` repo's internal tooling beyond its placement and release-pinning role.

## The Line: Integration Test vs. Example

| Question | Integration test (`cdk-terrain/test`) | Example (`cdktn-examples`) |
| --- | --- | --- |
| Primary purpose | Validate the toolchain in CI | Teach a real-world architecture |
| Exercised by CI on every CDKTN change? | Yes | No |
| Pins a released version or tracks `main`? | Tracks `main`, runs against `dist/` | Pins the latest release |
| Must stay green against the current codebase? | Yes | No |
| Typical complexity | Low — one feature or seam | High — multi-service |
| Linked from the docs catalog? | No | Yes |
| Owned by | Core maintainers | Community + maintainers |

Rule of thumb: if it must stay green against the current codebase to catch regressions, it is an **integration test** and belongs in `test/`. If it is a standalone learning project that evolves on its own cadence, it is an **example** and belongs in `cdktn-examples`.

Seam tests are integration tests. The `edge` provider test (`test/typescript/edge/`, backed by the edge-provider schema under `packages/@cdktn/provider-generator`) exercises the toolchain's provider seams without depending on every real provider having a matching use case — purely CI value, so it is a test, not an example.

### Where the docs point

Following AWS CDK and cdk8s, the public [cdktn.io](https://cdktn.io/docs/examples-and-guides/examples) catalog links users to the standalone `cdktn-examples` repo as the single user-facing home — never into the monorepo `test/` tree. Integration tests gate CI; they are not browsable samples and are not linked from the docs.

cdk8s makes this concrete: an app that used to live in the monorepo under `examples/typescript/cdk8s-plus-elasticsearch-query/` now has only a README stub there that reads "Moved to" the [`cdk8s-examples` repo](https://github.com/cdk8s-team/cdk8s-examples/tree/main/typescript/cdk8s-plus-elasticsearch-query). The instructional content moved out; the monorepo keeps only what CI needs. CDKTN lands in the same end state: examples in `cdktn-examples`, integration tests in `cdk-terrain/test`, no instructional content left stranded in the monorepo.

## Integration-Test Harness (Existing)

Integration tests already live under `test/<language>/<name>/` with a `test.ts` entrypoint. The harness is the source of truth and does not change:

- `tools/build-test-matrix.mjs` discovers tests via `jest --listTests` and emits the CI matrix (target × Terraform/OpenTofu version × HCL/JSON output).
- `test/run-against-dist.mjs` runs them against the packaged `dist/` build.
- `.terraform.versions.json` drives the version matrix.
- Tests are driver-based (`driver.diff()`, `driver.deploy()`, synth assertions), not standalone deployable projects.

Migrating a validation app into `test/` means expressing it as a `test.ts` against the driver, not copying a standalone app directory. This is a simplification: the app shrinks to the smallest form that exercises the feature or seam, and the duplicate `__tests__/` harness some `examples/` apps carry today is dropped in favor of the shared one.

## Migrating the Current `examples/` Tree

The tracked `examples/` tree is drained, not kept:

1. **Reclassify each entry** as an integration test or an example using the line above.
2. **Integration tests** → fold into the `test/` harness as `test/<language>/<name>/test.ts`, simplified to the minimal driver-based test. Where an `examples/` app already carries an `__tests__/` folder (e.g. `aws-prebuilt`), that logic moves into the shared harness rather than running its own jest config.
3. **Examples** → move to `cdktn-examples` as full instructional projects, pinned to the latest release, each with a complete `README.md`.
4. **Remove the `examples/` tree** from the monorepo once drained. No redirect stub is needed in `cdk-terrain`; the docs link straight to `cdktn-examples`.

## Classification Map

Mapped from the current `examples/` tree and the docs catalog.

### Integration tests → `cdk-terrain/test`

Low-complexity apps that validate the toolchain against `main`.

| App | Languages |
| --- | --- |
| aws-prebuilt | TS, Java, C#, Maven, Gradle |
| aws-multiple-stacks | TS |
| aws-cloudfront-proxy | TS |
| aws (VPC / DynamoDB / EKS) | Python, Java, C#, Go |
| aws-eks | Python |
| azure | TS, Python, Java, C#, Gradle |
| azure-app-service | TS |
| google | TS, Java, C#, Gradle |
| google-cloudrun | TS |
| docker | TS, Python, Go |
| kubernetes | TS, Python, Java, Gradle |
| ucloud | all languages |
| vault | TS |
| gradle-shared-module | Java (Gradle) |
| edge provider (seam test, already in `test/`) | TS |
| Backends: s3, gcs, azurerm, remote | TS (`backends/`) |

### Examples → `cdktn-examples`

High-complexity, instructional projects pinned to the latest release.

| Example | Languages |
| --- | --- |
| aws-ecs-docker-and-static-frontend | TS |
| aws-lambda-end-to-end | TS, Python, Maven |
| ecs-microservices-cdktn | TS |
| google-end-to-end | Python, Maven |

### External references (no repo move)

| Resource | Where it lives |
| --- | --- |
| Pocket `recommendation-api` + `terraform-modules` | Mozilla Pocket's public repos (linked from docs) |
| YouTube playlist, release demos | External video links |

## Prior Art

Comparable CDK-style and IaC projects consistently keep a dedicated examples repo separate from the core repo, with CI regression coverage handled inside the core repo as integration tests under a different name and folder. None wires the examples repo back in as a git submodule.

- **AWS CDK**: The [Developer Guide examples section](https://docs.aws.amazon.com/cdk/v2/guide/how-tos.html) points users only to the standalone [`aws-samples/aws-cdk-examples`](https://github.com/aws-samples/aws-cdk-examples) repo, organized by language for parity; large apps are linked out, not copied. CI regression coverage is a separate concern inside [`aws/aws-cdk`](https://github.com/aws/aws-cdk) as [integration tests](https://github.com/aws/aws-cdk/blob/main/INTEGRATION_TESTS.md) — small CDK apps with a 1:1 app-to-test relationship, co-located with the code and never surfaced as user-facing examples. AWS CDK draws exactly the integration-test-vs-example line this RFC adopts.
- **cdk8s**: The [docs examples page](https://cdk8s.io/docs/latest/examples/) links exclusively to the standalone [`cdk8s-team/cdk8s-examples`](https://github.com/cdk8s-team/cdk8s-examples) repo, split by language; every example link targets that repo, not the `cdk8s-team/cdk8s` umbrella monorepo. Apps that once lived in the monorepo `examples/` tree are now [redirect stubs](https://github.com/cdk8s-team/cdk8s/blob/master/examples/typescript/cdk8s-plus-elasticsearch-query/README.md) pointing at the examples repo — the instructional content moved out entirely.
- **Winglang**: Core in [`winglang/wing`](https://github.com/winglang/wing); examples in a separate [`winglang/examples`](https://github.com/winglang/examples) repo, tested against the most recent releases. Larger examples live in their own dedicated repos and are linked.
- **Pulumi**: Core in [`pulumi/pulumi`](https://github.com/pulumi/pulumi); examples in [`pulumi/examples`](https://github.com/pulumi/examples) with a flat `<cloud>-<language>` naming scheme. Documents a sparse-checkout recipe so users pull a single example without cloning the whole repo. Validation runs inside the examples repo via `make pr_preview`.

Takeaways for CDKTN: a dedicated examples repo is the norm; the public docs point users to that repo, not the core monorepo; CI validation lives in the core repo as integration tests under their own harness; none uses a submodule; oversized examples get linked rather than copied.

## Alternatives Considered

### Examples via git submodule

One option raised was to put all samples in a single `cdktn-examples` repo, embed it in `cdk-terrain` as a git submodule, and run only selected ones in CI. This RFC does not adopt it.

- **A submodule pins a commit, CI needs lockstep.** A submodule tracks one fixed commit of the examples repo, not `main`. An API change in `cdk-terrain` would not break the pinned apps until someone bumps the pointer, so CI stops catching regressions the moment they drift — the opposite of what integration tests are for.
- **The dependency direction is backwards.** Integration tests exist to validate CDKTN as it changes, so they must move with the code in one PR — which the existing `test/` harness already guarantees. A pinned submodule splits that into two steps and lets breaking changes pass green.
- **No strong precedent.** AWS CDK, cdk8s, Winglang, and Pulumi all keep examples separate without a submodule, and all keep CI validation in-repo. Real-world submodule use is for shared libraries, SDKs, and build tooling — not example catalogs.
- **Selective checkout does not need a submodule.** Pulumi's sparse-checkout gives the "pick only the relevant ones" benefit without the staleness.

If a submodule were adopted anyway, it would require scheduled auto-bump automation and `submodule.recurse` enabled for contributors — overhead the split model avoids.

## Adding a New App

1. Classify it: integration test or example?
2. **Integration test** → add `test/<language>/<name>/test.ts` in the monorepo as the minimal driver-based test. It is picked up automatically by `build-test-matrix.mjs`; no separate jest config.
3. **Example** → create a top-level project in `cdktn-examples`, pinned to the latest release, with a full instructional `README.md`. Add the row to the [docs catalog](https://cdktn.io/docs/examples-and-guides/examples) with its complexity rating, linking to `cdktn-examples` as the source.
4. Never link the docs catalog into the monorepo `test/` tree.

## Success Criteria

Every app is classified as either an integration test or an example and placed accordingly; the monorepo `examples/` tree is drained into the `test/` harness (tests) and `cdktn-examples` (examples) and then removed; the public cdktn.io catalog links users only to `cdktn-examples`; integration tests stay green against `main` through the existing harness; and instructional examples live in `cdktn-examples` pinned to the latest release.
