# Proposal: "synth and test" — TypeScript-authored `terraform test` / `tofu test` suites

Status: **proposed** · Companion dataset (`test-features-matrix.json`,
rendered as [`MATRIX.md`](MATRIX.md)) and sweep tooling (`scripts/`,
`fixture/`) live next to this file — the same shape as
`04-provider-feature-availability`, but sweeping `<binary> test -json` over
one-feature-per-file probes instead of `providers schema -json`. Research
notes that are not reproducible by the sweep are in [`research/`](research/).

## Problem

CDKTN's testing library stops at "synth and **plan**". Between a Jest
assertion over synthesized JSON and a real `cdktn deploy` there is nothing:

| Tier | Today | Catches | Misses |
| --- | --- | --- | --- |
| 0 — synth assertions (`Testing.synth`, `toHaveResourceWithProperties`) | ✅ in-process, ms | construct wiring as *JSON shape* | anything Terraform evaluates: expressions, `count`/`for_each`, conditionals, validations, references |
| 1 — `toBeValidTerraform` / `toPlanSuccessfully` | ✅ `execSync`, pass/fail only | config is loadable / plannable | *what* the plan contains; needs real credentials for most providers; no diagnostics (`stdio: "ignore"`) |
| 2 — evaluated assertions without credentials | ❌ | — | — |
| 3 — deploy, assert, destroy | ❌ (community: Terratest over `cdktf.out`, e.g. `tcons/base/integ`) | — | — |

Terraform ≥ 1.6 and OpenTofu ≥ 1.6 ship a native test framework that fills
tiers 2 and 3: `run` blocks that plan or apply the module, HCL `assert`
conditions evaluated by the real engine, `expect_failures` for custom
conditions, and — since Terraform 1.7 / OpenTofu 1.8 — `mock_provider` and
`override_*` blocks that make an **apply** run offline and credential-free.
Upstream CDKTF never designed an integration
([hashicorp/terraform-cdk#1093][u1093], a 2021 placeholder that was never
filled in; [#3687][u3687], a two-phase proposal with no maintainer response)
and the repository was archived on 2025-12-10 — there is no upstream design
to align with; CDKTN owns this decision.
CDKTN has **zero** support: no test-file model, no way to place test files in
the synth output, no `test` verb in `TerraformCli` or the CLI, and no
structured consumption of Terraform's machine-readable output.

The research also surfaced bugs and gaps in the features tests exist to
exercise — custom conditions ("validators"):

- **`TerraformOutput.precondition` is accepted and silently dropped**
  (`packages/cdktn/src/terraform-output.ts:26,35,45` store it; neither
  `synthesizeAttributes()` `:99-106` nor `synthesizeHclAttributes()` `:108-137`
  emit it) — [cdk-terrain#448][i448]. Related but distinct:
  [cdk-terrain#313][i313] (HCL-mode resource `lifecycle` conditions render as
  an attribute list).
- **No `check` block construct** (only `stack.addOverride("check.x", …)`) —
  [cdk-terrain#449][i449].
- **A legal variable validation cannot be written in the constructor.**
  Terraform requires a validation condition to reference its own variable —
  still true after 1.9 allowed *additional* cross-object references — and the
  variable's token does not exist until construction finishes, so
  `addValidation()` (or a `Lazy.anyValue` producer) is the only path,
  undocumented, with no synth-time check — [cdk-terrain#450][i450].
  Upstream [#3571][u3571] is the Python flavour of the same confusion.
- **No `targetVersions` gating** for cross-object validation conditions
  (Terraform ≥ 1.9.0, OpenTofu ≥ 1.9.0) although the default target floor is
  1.5.7 / 1.6.0 and `ValidateFeatureTargetSupport` exists for exactly this —
  [cdk-terrain#451][i451].
- **The existing tier-1 matchers are unsafe under Jest's default parallel
  workers** — each assertion runs a bare `terraform init` against the shared
  `TF_PLUGIN_CACHE_DIR`, which is documented as not concurrency-safe
  ([hashicorp/terraform#31964][tf31964]; upstream [#2939][u2939] is this race)
  — and `init` touches the real backend (upstream [#3909][u3909]) —
  [cdk-terrain#452][i452].

## Data: what the engines can actually do

`scripts/sweep.sh` downloads every minor-boundary release of both products
from 1.6 up (Terraform → 1.16.x, OpenTofu → 1.12.x), and
`scripts/run-probes.py` runs each `fixture/probes/*` — one test file
exercising exactly one feature against a tiny `random`-provider JSON root
module — through `init -backend=false` + `test -json`. A probe is "supported"
only if the run exits 0 **and** reports ≥ 1 passed run. See
[`MATRIX.md`](MATRIX.md) for the generated table; the facts that shape the
design:

1. **`terraform test` works unchanged against `cdk.tf.json`**, and
   **`.tftest.json` is a first-class format in both engines since 1.6** — no
   JSON-only feature gap found. We synthesize JSON test files with the
   existing resolver; no HCL emitter needed.
2. **JSON object key order is run order.** `run` blocks execute in document
   order (verified in both engines: `zzz_first` ran before `aaa_second`).
   Any key-sorting serializer silently reorders the test plan. Note
   `Testing.synth` uses a *stable* (sorting) stringify — the test-file writer
   must not.
3. **Two value kinds.** Expressions are `"${…}"` template strings;
   *traversal-typed* arguments (`expect_failures`, `override_*.target`,
   `providers` values, `plan_options.target/replace`) must be **bare**
   strings — `"${var.len}"` is a hard error.
4. **Mocked providers still require the provider binary.** Mocking removes
   credentials and API calls, not `init`: the real schema shapes mock values.
   Measured with `hashicorp/aws` 6.0.0: cold `init` 15.7 s / 666 MB; warm
   `init -plugin-dir=<cache>` 0.29 s; one mocked run 0.72 s.
5. **Mock values are type-conformant only — and the real provider still
   validates them.** Core generates computed values from the schema *type*
   alone: strings are random 8-char alphanumerics (`region = "uzv87bki"`),
   numbers `0`, bools `false`, collections empty; **non-deterministic across
   invocations**, so unpinned values cannot be snapshotted. Only the CRUD/read
   calls are mocked: the provider's **config validation still runs** on
   whatever flows into a validated argument. So an unpinned
   `data.aws_iam_policy_document.x.json` (`"eypeo4xi"`) fed into
   `aws_iam_role.assume_role_policy` fails with *"contains an invalid JSON
   policy: not a JSON object"* ([terraform-provider-aws#36700][aws36700],
   open; [terraform#35451][tf35451], [terraform#34764][tf34764],
   [terraform-provider-aws#42834][aws42834] — all closed *working as
   designed*: "mocking is controlled entirely by Terraform Core", pin the value
   with `override_data`/`mock_data`). No provider or core release fixed or
   will fix this class. Core-side breakage is the sibling: an empty
   `aws_availability_zones.names` → index error, `jsondecode()` of a random
   string, ARN parsing. Conversely a garbage *computed* value that feeds
   nothing validated (`bucket_region = "afbah75e"`) passes silently — mocked
   tests verify *your wiring*, not *provider acceptance*.
   For `hashicorp/aws`, the attributes that in practice **must** be pinned:
   `aws_iam_policy_document.json` (and every `policy`-shaped consumer), any
   `arn` parsed or ARN-validated downstream, `aws_caller_identity.account_id`,
   `aws_region.name`/`.region`, `aws_partition.partition`/`.dns_suffix`,
   `aws_availability_zones.names`/`.zone_ids`, security-group `id`s and
   `ingress`/`egress` sets where code branches on them. OpenTofu fixed real
   bugs in this area ([#2140][ot2140] required-argument validation under
   mocks, 1.9; [#2144][ot2144] silently dropped overrides on tuple-vs-list
   types, 1.9; [#3069][ot3069] schema-accurate generation, 1.11 — which makes
   previously tolerated invalid mocks fail).
6. **The engines have forked on test semantics**, not just features:

   | Behaviour (probe) | Terraform floor | OpenTofu floor |
   | --- | --- | --- |
   | Test framework, `.tftest.json`, `expect_failures` on variable / output / check (01-05, 26) | ≥ 1.6 | ≥ 1.6 |
   | `mock_provider`, `override_resource` / `override_data` (06, 07, 22) | ≥ 1.7 | ≥ 1.8 |
   | Mock/override values **known during `command = plan`** (08-10) | ≥ 1.11, and only with `override_during = plan` | ≥ 1.8, always — `override_during` is a **parse error** in every release |
   | run `variables` referencing `run.<name>.<output>`; helper `module { source }` runs (15, 21) | ≥ 1.6 | ≥ 1.7 |
   | file-level `variables` referencing `run.<name>` (14) | ≥ 1.13 | ≥ 1.8 |
   | `assert.condition` referencing `run.<name>.<output>` (23) | ≥ 1.6 | never ("no managed resource `run`") |
   | run `variables` referencing a file-level `variables` entry (24) | ≥ 1.6 | never ([opentofu#4567][ot4567]) |
   | functions inside mock `defaults` / override `values` (17) | ≥ 1.15 | never (not evaluated) |
   | `mock_provider.source` + `.tfmock.*` files (16) | ≥ 1.7 | never ([opentofu#1778][ot1778]) |
   | `state_key` (11) · `test { parallel }` / `run.parallel` (12) | ≥ 1.11 · ≥ 1.12 | never — parse errors ([opentofu#2542][ot2542]) |
   | `variable` blocks in test files (13) | ≥ 1.13 | never |
   | `-junit-xml` (19) | ≥ 1.11 | never ([opentofu#2501][ot2501]) |
   | `.tofutest.json`, shadowing a same-basename `.tftest.json` unparsed (20, 25) | never (file ignored) | ≥ 1.8 |
   | `skip_cleanup` (18), `backend` in `run`, `terraform test cleanup` | never — **experimental builds only** through 1.16.3 | never |
   | `-json` event timing (not probed) | streamed per run | batched at file end ([opentofu#3876][ot3876]) |
   | One unparsable test file aborts the directory, even with `-filter` (not probed) | yes | yes |

   "never" = absent from every swept release (Terraform 1.6.6 → 1.16.3,
   OpenTofu 1.6.0 → 1.12.6). Floors are the first swept minor that passes the
   probe; no probe regressed in a later release of either product.

7. **`expect_failures` reaches every validator kind** in both engines:
   `var.<name>` (validation), `output.<name>` (precondition), resource/data
   addresses (pre/postconditions), `check.<name>` (a check *warning* counts).
   Only custom conditions — never provider or type errors. Use `command =
   plan`: an expected variable failure under `apply` fails the run anyway.
   An *unexpected* failing `check` block — a mere warning for `plan`/`apply` —
   ends the run with status `error` in both engines (probe 26), so `check`
   blocks are usable as test assertions that also ship to production.
8. **A failing run skips the remaining runs of its file** (both engines).
   This is not Jest semantics and must be documented, not hidden.
9. **`terraform test` ignores the backend, `init` does not.** With an `s3`
   backend block and no credentials `init` fails, `init -backend=false`
   succeeds, and the test then passes with in-memory state. Probe 22 confirms
   the CDKTN cross-stack shape — a `terraform_remote_state` data source
   pointing at a state that does not exist — is testable in isolation via
   `override_data`.
10. **Plugin-cache race reproduced on a warm cache**: 6 concurrent
    `init`+`test` workers sharing `TF_PLUGIN_CACHE_DIR` → 6/6 failed
    (truncated provider binary / checksum mismatch, 80 s). Pre-seeding each
    working directory with one shared `.terraform.lock.hcl` → 6/6 passed in
    2.4 s. The upstream fix attempt was closed unmerged on 2026-09-08.

## Design

Guiding decisions:

- **Tests are defined in code, only.** Suites are constructs authored in
  TypeScript (or Python / Java / C# / Go through jsii) and lowered by the
  existing token resolver, from the construct references the user already
  holds; nobody writes `random_string.s_3F2A91`. Hand-written
  `.tftest.hcl` / `.tftest.json` passthrough — the "cheap half" of upstream
  [#3687][u3687] — is deliberately **not** offered: it is not in the spirit
  of CDK Terrain, and it would make logical IDs a public contract.
- **One artifact per suite: `<suite>.tftest.json`**, valid for both engines
  when it stays inside the common subset (fact 6). Engine-exclusive features
  are **gated, not papered over**: using one registers a synth-time
  validation against the project's declared `targetVersions`. OpenTofu-only
  semantics and the `.tofutest.json` overlay are a follow-up (see
  [Follow-up](#follow-up--opentofu-specific-test-semantics)) — no part of
  cdk-terrain handles OpenTofu core differentiators today.
- **Gate by declared `targetVersions`, never by the binary on disk.**
  Synthesis does not shell out (in the spirit of [cdk-terrain#275][i275]).
  The constraints map below is this RFC's dataset, enforced through the
  existing `ValidateFeatureTargetSupport` (precedent: `S3Backend.useLockfile`,
  `backends/s3-backend.ts:20-26`).
- **Default to `command = apply` against `mock_provider`** for unit-style
  suites: offline, credential-free, every computed attribute concrete, and —
  unlike plan-time mocks — **identical on both engines**. Plan runs are for
  `expect_failures` and deliberate diff assertions.
- **Implement once in the runner-agnostic core.** New matchers live in
  `testingMatchers` (`packages/cdktn/src/testing/matchers.ts`); the in-core
  Jest adapter and `@cdktn/vitest` each add a few lines of registration.

```ts
// packages/cdktn/src/testing/test-feature-constraints.ts  (generated from test-features-matrix.json)
// an omitted product = not supported by any release of that product
export const testFeatureConstraints = {
  testFramework:        { terraform: ">=1.6.0",  opentofu: ">=1.6.0" },
  mocksAndOverrides:    { terraform: ">=1.7.0",  opentofu: ">=1.8.0" },
  runOutputInVariables: { terraform: ">=1.6.0",  opentofu: ">=1.7.0" },
  overrideDuringPlan:   { terraform: ">=1.11.0" },
  runOutputInAssert:    { terraform: ">=1.6.0" },
  stateKey:             { terraform: ">=1.11.0" },
  parallelRuns:         { terraform: ">=1.12.0" },
  functionsInMocks:     { terraform: ">=1.15.0" },
} as const satisfies Record<string, TerraformFeatureVersionConstraints>;
```

Every `TerraformTest` registers `testFramework`; with the default targets
(`terraform >=1.5.7`, `opentofu >=1.6.0`) that already fails synth with the
standard "requires terraform >=1.6.0, but the project targets …" message, so
adopting tests means declaring a floor. A Terraform-exclusive feature in a
project whose targets still admit OpenTofu fails the same way, with a hint
naming the portable alternative (e.g. *"`override_during` is Terraform-only;
use `command: "apply"` or drop `opentofu` from `targetVersions`"*).

**`override_during` is supported** on `MockProvider` and on
`overrideResource/Data/Module`, gated by `overrideDuringPlan`. It is never
inferred: a plan run asserting on mocked values without it is left to fail
with Terraform's own (excellent) *Unknown condition value* diagnostic, which
the reporter surfaces verbatim.

### Coordinating test synthesis with the stack synthesizer

Writing an extra, **insertion-ordered** JSON file per suite is not an
existing capability. Today one `StackSynthesizer` per stack
(`synthesize/synthesizer.ts:29-136`) writes exactly `cdk.tf.json` (or
`cdk.tf` + `metadata.json`), everything goes through `safe-stable-stringify`
(deterministic = **keys sorted**), `toTerraform()` collects only
`TerraformElement`s (`terraform-stack.ts:611-630`), and the manifest lists no
extra files. Options considered:

| | Option | Verdict |
| --- | --- | --- |
| A | Replace/subclass `stack.synthesizer` (public mutable `IStackSynthesizer`) with a test-aware synthesizer | ✗ one synthesizer per stack and users may already replace it — no composition story |
| B | Make suites `TerraformElement`s and teach `toTerraform()` to route them to a second document | ✗ `toTerraform()` returns one sorted document; pollutes `cdk.tf.json` metadata and every existing `Testing.synth` snapshot |
| C | **`addCustomSynthesis(suite, { onSynthesize })`** — the `ICustomSynthesis` hook `TerraformAsset` already uses to write files into the stack directory (`terraform-asset.ts:149-151,200-224`) | ✓ **recommended** |
| D | A separate post-synth pass owned by `Testing` / the CLI | ✗ suites would not exist after a plain `app.synth()`; two code paths to keep in sync |

With **C**, `TerraformTest` is a plain `Construct` (not a `TerraformElement`,
so it is invisible to `cdk.tf.json`, to `Testing.synth` snapshots and to
every existing validation) that registers a custom synthesis. The hook runs
inside `StackSynthesizer.synthesize()` step 6 — after `prepareStack()` and
validations, before the stack document is written — receives the
`ISynthesisSession`, derives the directory from
`session.manifest.forStack(stack).workingDirectory`, resolves the suite with
the internal `resolve(stack, …)` and writes
`<workingDirectory>/tests/<suite id>.tftest.json` with plain
`JSON.stringify(doc, null, 2)`. It fires identically under `App.synth()` and
`Testing.fullSynth()`. What the recommended option still has to solve:

1. **Ordering.** Runs are an array in the API; the document is assembled
   into an insertion-ordered object and written with a **non-sorting**
   writer. A unit test pins `zzz_first` before `aaa_second` end to end (the
   resolver's object walk must preserve key order too). Duplicate run names
   are rejected at construction — JSON could not represent them anyway.
2. **Own-stack references only.** Cross-stack reference registration is a
   side effect of the *preparing* resolve pass, which walks
   `TerraformElement`s only; resolving a foreign-stack token from the hook
   would silently emit a wrong bare identifier, too late for the producer
   stack to gain its output. A suite therefore may reference only elements of
   its own stack: `prepareStack()` gains a second, small collector that
   resolves suites with `preparing = true` under a guard that turns a
   foreign-stack `Reference` into a synth error pointing at
   `overrideRemoteState()`. The same pass lets resolve-discovered feature
   usage (`GatedFeatureValidation`) work inside suites.
3. **Stale files.** Neither the synthesizer nor `cdktn synth` prunes inside a
   surviving stack directory (`synth-stack.ts:202-209` removes whole orphaned
   stacks only), so a deleted suite would linger — and one unparsable file
   aborts the whole directory. The first suite hook per stack and session
   clears `tests/` (tracked in the open `ISynthesisSession` bag), mirroring
   `TerraformAsset` removing its stale folder. `tests/` is owned by the
   synthesizer; helper modules are emitted under `tests/modules/<id>/`.
4. **Two value kinds** (fact 3). Conditions and variables are expressions
   (`"${…}"`, `$${` escaping already handled by `tfExpression.ts`);
   `expectFailures`, override targets and `providers` take
   `ITerraformAddressable` elements and lower to **bare** traversals built
   from the public getters (`<terraformResourceType>.<friendlyUniqueId>`,
   `data.…`, `var.…`, `output.…`, `module.…`) — `fqn` is a braced token and
   cannot be reused. `TestTarget.fromAddress("check.health")` is the escape
   hatch for blocks without a construct.
5. **Manifest.** `StackManifest` gains an additive `tests?: string[]` so the
   CLI knows which stacks carry suites without scanning directories.
6. **Snapshots.** `Testing.synth` bypasses custom synthesis by design;
   `Testing.synthTest(suite)` returns the resolved test document as a string
   for unit-testing suites themselves.
7. **HCL mode** (`SYNTH_HCL_OUTPUT`): suites are still written as
   `.tftest.json` next to `cdk.tf` — mixed syntaxes in one module are
   standard; to be confirmed by an added probe.

### Prerequisites (cdk-terrain issues)

Implementation of this RFC does not start before the **blocking** issues are
closed; the others are tracked alongside but do not gate it.

| Issue | What | Relation |
| --- | --- | --- |
| [cdk-terrain#448][i448] | `TerraformOutput.precondition` accepted but never synthesized | **blocks** — `expectFailures: [output]` is meaningless while the block is dropped |
| [cdk-terrain#452][i452] | Testing matchers: plugin-cache race under parallel workers, `init` touches the real backend, diagnostics discarded | **blocks** — `toPassTerraformTests` and `cdktn test` reuse this `init` path (facts 9, 10) |
| [cdk-terrain#449][i449] | `TerraformCheck` construct | related — core language gap since Terraform 1.5 / OpenTofu 1.6. **Not required by this RFC**: check blocks already work as test targets through `addOverride` + `TestTarget.fromAddress`; the construct only makes them typed `expectFailures` targets and lets assertions ship to production as continuous checks |
| [cdk-terrain#450][i450] | Construct-time variable validation: `condition: VariableCondition.of({ produce: (v) => … })` — a deferred condition handed the variable, the `Lazy.anyValue` pattern (behavioural interface + static factory, since jsii has no function types); no new prop, no `SELF` sentinel; missing self-reference is a *warning* | related, **nice-to-have** — `addValidation()` and `Lazy.anyValue` already express every legal validation (the latter awkwardly in Java / C#), hence validations are testable today |
| [cdk-terrain#451][i451] | `targetVersions` gate for cross-object validation conditions (≥ 1.9 / ≥ 1.9) | related |
| [cdk-terrain#385][i385] | "backend should not be required" (a `LocalBackend` is always injected) | related, not blocking — every synthesized stack carries a backend block, which `terraform test` ignores but `init` does not; the test path always runs `init -backend=false`, whatever #385 decides |
| [cdk-terrain#313][i313] | HCL-mode `lifecycle` conditions render as attribute lists | related — same family as #448 for HCL output |
| [cdk-terrain#275][i275] | synth-time validations from declared `targetVersions`, not binary probes | related — the gating model this RFC follows |

### Phase 1 — test constructs and synthesis (`cdktn`, jsii)

```ts
// NOTE: or raise the targetVersions floor as part of RFC
const app = Testing.app({ context: { targetVersions: { terraform: ">=1.7.0", opentofu: ">=1.8.0" } } });
const stack = new BucketStack(app, "bucket");

const suite = new TerraformTest(stack, "defaults", {
  mockProviders: [new MockProvider(AwsProvider.tfResourceType, {   // "aws" — a string, see below
    resources: { [S3Bucket.tfResourceType]: { arn: "arn:aws:s3:::mocked", id: "mocked" } },
  })],
  // alternative: well-known presets from a separate package, e.g. @cdktn/mock-provider-aws
  // mockProviders: [new AwsMockPresets()],
});
suite.run("tags and versioning", {            // command defaults to "apply" when every provider is mocked
  variables: [{ variable: stack.prefix, value: "unit" }],
  assert: [
    { condition: Op.eq(stack.bucket.bucketPrefix, "unit"), errorMessage: "prefix follows the variable" },
    { condition: Op.eq(Fn.lookup(stack.bucket.tags, "ManagedBy"), "cdktn"), errorMessage: "ManagedBy tag" },
  ],
});
suite.run("rejects empty prefix", {
  command: "plan",
  variables: [{ variable: stack.prefix, value: "" }],
  expectFailures: [stack.prefix],             // ITerraformAddressable -> bare "var.prefix"
});

expect(Testing.fullSynth(stack)).toPassTerraformTests();   // Phase 2
```

- **Constructs**: `TerraformTest` (one file), `TerraformTestRun` (`command`,
  `variables`, `assert`, `expectFailures`, `planOptions`, `providers`,
  helper `module`), `MockProvider` (`mock_resource` / `mock_data` defaults,
  `alias`, `overrideDuring`, scoped overrides), `overrideResource/Data/Module`
  at file or run scope, `overrideRemoteState(producerStack, { outputs })`.
  Keeping suites in test files (as above) is the recommended style; test
  files are inert for `plan`/`apply`, so a suite declared in a deployable app
  is harmless.
- **Common-subset rules enforced at synth** (fact 6): run variables may
  reference `run.<name>` outputs (`runOutputInVariables`); `run.<name>` in an
  assertion registers `runOutputInAssert` (Terraform-only); file-level
  `variables` are not exposed — values are inlined per run, side-stepping
  [opentofu#4567][ot4567]; `stateKey` / `parallel` register their gates;
  `.tfmock` files, test-file `variable` blocks, `skip_cleanup` and `backend`
  in runs are not modelled.
- **Cross-stack**: a consumer stack's synthesized `terraform_remote_state`
  is overridden with `overrideRemoteState(producer, { outputs })` (probe 22,
  with a backend block present). Upstream [#3538][u3538] (`fullSynth`
  mis-wires incoming cross-stack references) must be checked first. True
  multi-stack e2e is Phase 3.
- **Mock values are literals.** Functions inside mock `defaults` / override
  `values` are evaluated by Terraform ≥ 1.15 only; older Terraform and every
  OpenTofu release keep the template as an unevaluated value (probe 17), so
  `Fn.jsonencode(...)`, `Fn.format(...)` or *any token* — including a
  reference to another resource's attribute — inside a mock value yields
  garbage or an error rather than the intended value. The synthesizer rejects
  unresolved tokens in mock values unless `functionsInMocks` is satisfied by
  the declared targets. The cost is small because the host language computes
  the value instead (`JSON.stringify(policy)`), which hand-written HCL mocks
  cannot do; what is genuinely lost is *deriving a mock from another
  run-time value* (e.g. `arn = "arn:aws:s3:::${var.name}"`) — pin both sides
  to literals instead.
- **Mock presets are `MockProvider` subclasses, not a second concept.** A
  preset package exports a ready-made mock — `new AwsMockPresets()` *is* the
  `mock_provider "aws"` block, pre-filled with the values fact 5 says must be
  pinned (well-formed ARNs, `account_id`, region, partition, AZ names,
  `sg-…`-shaped ids). There is no separate `IMockPreset` interface to learn
  or implement. What this shape implies for the core class:
  - *Identified by strings.* `MockProvider` takes the provider's local name
    (`"aws"`, i.e. `AwsProvider.tfResourceType`) and resource-type strings,
    never a class — jsii cannot pass classes as values (the jsii-facing
    `Testing.toHaveResource` statics take strings for the same reason). The
    upside: a preset package needs **no dependency on the provider bindings**
    — it mocks `aws_iam_role` by name and works with prebuilt, locally
    generated and `cdktn-aws`-style bindings alike, versioned against
    provider majors.
  - *Layering replaces composition.* Terraform allows one `mock_provider`
    block per provider + alias, so two presets for one provider cannot be
    listed side by side. Instead presets accept the same props as the base
    class and expose mutators —
    `new AwsMockPresets({ alias, resources: { … } })`,
    `.addResourceDefaults(type, values)`, `.addDataDefaults(type, values)` —
    with the precedence *user values > preset values > engine-generated*.
    Duplicate provider + alias in `mockProviders` is a synth error.
  - *A synth-time hook for computed presets.* A protected
    `onBind(suite)` runs when the suite synthesizes, so a preset can inspect
    the stack under test: for every element whose type is
    `aws_iam_policy_document` it can render the document in the host language
    and emit an `override_data` (falling back to `"{}"` when it holds
    unresolved tokens) — something a static HCL mock file cannot do.
  - *Aliased / renamed providers* are a constructor option (`alias`,
    `localName`), since a preset cannot know how the stack named its provider.

  **Core ships only `MockProvider`** — cdk-terrain has never shipped
  provider-specific code. Well-known presets are published separately (the
  `cdktn-io` org is the natural home) or by construct libraries next to their
  constructs. This is a differentiator: `mock_provider.source` accepts a
  local directory only, no registry distribution of mock data exists, no
  community mock library was found, OpenTofu has no mock files at all
  ([opentofu#1778][ot1778]), and "providers define their own mock value
  patterns" is an open, undecided request ([opentofu#2338][ot2338]). A
  package manager is exactly the missing distribution channel.
- **Source mapping.** The synthesizer records run/assert index → call site
  in a side-car map; `diagnostic.snippet.context` (`run.<name>.assert[<i>]`)
  is the only machine-readable link back to an individual assertion.

### Phase 2 — execution: cli-core, `cdktn test`, matchers

- `Terraform` interface + `TerraformCli` gain
  `test(opts): AsyncIterable<TestEvent>` and `init({ backend: false })`
  (`@cdktn/cli-core/src/lib/models/terraform-cli.ts:116-201`);
  `CdktfProject.test()` mirrors `diff()` and reuses `execute()`'s scheduler
  for stack-level concurrency.
- `cdktn test [stacks...] [--filter <suite>] [--verbose] [--parallelism <n>]
  [--terraform-parallelism <n>] [--junit-xml <path>] [--var k=v]`. Pipeline:
  **synth → one serialized warm-up `init` → seed `.terraform.lock.hcl` into
  every stack dir → per stack `init -backend=false` → `<binary> test -json`**
  (facts 9, 10). The engine that *executes* is `TERRAFORM_BINARY_NAME`, as
  for every other command; what may be *synthesized* was already decided by
  `targetVersions`. Stacks without suites are skipped via the manifest.
  Exit 1 if any stack fails.
- The reporter consumes the `-json` stream (same schema on both engines:
  `test_abstract`, `test_file`, `test_run`, `test_summary`, `diagnostic`,
  `test_cleanup`), tolerating Terraform's per-run streaming and OpenTofu's
  batch-at-file-end. **JUnit is written by CDKTN** from the events —
  OpenTofu has no `-junit-xml`. `test_cleanup.failed_resources[]` (leaked
  resources) is an error even when every assertion passed. Documented, not
  hidden: a failing run skips the remaining runs of its file (fact 8).
- `toPassTerraformTests()` in `testingMatchers` runs the same pipeline for a
  `fullSynth` directory and renders failed runs with Terraform's
  diagnostics mapped to the TypeScript call site. A `globalSetup` helper
  performs the single warm-up `init` so parallel workers take the
  verified-checksum path ([cdk-terrain#452][i452]). TypeScript-only sugar
  `describeTerraformTest(suite)` (one runner test per run block) ships in the
  Jest adapter and in `@cdktn/vitest`.

### Phase 3 — e2e integration mode (real providers)

`command = apply` without mocks: multi-run chaining through run variables,
helper `module { source }` runs (probe 21) for fixtures, injected unique
`run_id`/region variables for naming, leak reporting from `test_cleanup`.
Parallelism is **process-level** (one `terraform test` per stack / per
suite, bounded by `--parallelism`) and therefore engine-neutral;
Terraform's `parallel` / `state_key` stay available behind their gates.
`skip_cleanup`-style iteration is **not** designed in: experimental builds
only in Terraform, absent in OpenTofu.

### Follow-up — OpenTofu-specific test semantics

**Unlocked only once cdk-terrain itself handles OpenTofu core
differentiators** — the `.tofu` / `.tofu.json` extensions and
[override files](https://opentofu.org/docs/language/files/override/) — which
no part of the project does today. Until then this RFC emits a single
`.tftest.json` and gates instead of adapting. Recorded for that follow-up:

- The mechanism is proven: from OpenTofu 1.8 a `<suite>.tofutest.json`
  shadows a same-basename `<suite>.tftest.json` *without parsing it*, and
  Terraform ignores `.tofutest.json` entirely (probes 20, 25). It is the only
  safe segregation — one unparsable file aborts the directory even with
  `-filter`.
- What an overlay would buy: plan-time mock assertions in dual-engine
  projects (emit `override_during = plan` for Terraform only — OpenTofu
  already knows mock values at plan, probe 08), Terraform-only `parallel` /
  `state_key` without dropping OpenTofu from the targets, and OpenTofu-only
  features (`mock_provider` `for_each` ≥ 1.11, instance/wildcard override
  targets ≥ 1.13).
- The data is already in the matrix; the follow-up adds an `opentofu`-only
  half to `testFeatureConstraints` and the second writer.

### Long-term goal — `@cdktn/integ`: custom-code smoke tests (the Terratest gap)

`terraform test` assertions are HCL expressions. There is **no hook between
apply and destroy** of a run: `skip_cleanup` / `terraform test cleanup` exist
only in experimental Terraform builds (probe 18; still under "Unreleased" on
`main`) and not at all in OpenTofu, so user code — SDK calls, polling,
invoke-and-observe round-trips — can never be interleaved. Data sources cover
part of it (`data "http"` with its `retry` block, `aws_lambda_invocation`,
attribute reads), but there is no generic "call any API" data source and no
poll-until-converged primitive.

The evidence that this tier is the main body of e2e work, not a long tail, is
`tcons/base/integ` — a production Terratest suite over CDKTN-synthesized
stacks ([`research/terratest.md`](research/terratest.md) §6): roughly a third
of its assertion *statements* are HCL-expressible, but almost none of its ~45
test functions could run end-to-end inside `terraform test`. Its signature
regression test — deploy, **re-synth the TypeScript app under a new
environment name**, replan, assert zero replace actions — cannot be hosted by
any version of `terraform test`. It also carries ~65 lines of Go→Bun synth
bridge, 11 near-identical stage drivers, a hand-rolled port of CDK's
`ExpectedResult`, and **177 of its own AWS SDK helpers on top of Terratest's
428**, while never touching `k8s`, `helm`, `ssh`, `docker`, `gcp` or `azure`.

Direction (a follow-up RFC, enabled by this one):

- **Harness-owned lifecycle in TypeScript**, built on `CdktfProject`
  (deploy/destroy/outputs and cross-stack ordering already exist): a
  TypeScript-only, non-jsii `@cdktn/integ` with five primitives —
  `stage(name, fn)` honouring `SKIP_<stage>` (the Terratest
  `%-no-cleanup` / `%-validate-only` iteration loop); a JSON `.test-data`
  store to register data in one stage and read it back in a later stage or
  process; a deploy/destroy wrapper with retryable-error regexes and
  `applyAndIdempotent`; **typed** stack outputs with a nested-attribute
  accessor; `retry` / `eventually`. Plus `uniqueId()` and a plan-struct
  helper (`countReplaceActions`) for the rename class of tests.
- **Do not rebuild Terratest's SDK-wrapper monorepo.** ~1,200 hand-maintained
  wrappers still did not cover one construct library's suite. Users call
  AWS SDK v3 / Azure / GCP / `fetch` / `@kubernetes/client-node` directly;
  CDKTN supplies typed outputs and the retry/staging scaffolding.
- **One assertion vocabulary, two engines**: assertions declared as data can
  be lowered into `.tftest.json` `assert` blocks (this RFC) or evaluated in
  TypeScript against SDK responses (`@cdktn/integ`).
- **Go stays first-class at zero cost**: Terratest with `TerraformDir =
  <CDKTF_OUTDIR>/stacks/<stack>` and `TerraformBinary: "tofu"` works today.
  Freeze and document the contract (`CDKTF_OUTDIR`, `manifest.json`,
  `stacks/<name>/cdk.tf.json`, `TERRAFORM_BINARY_NAME`) and recommend
  `cdktn synth` as a pre-step over an embedded synth bridge.
- **Prerequisite**: a documented, semver'd subset of `@cdktn/cli-core`
  (`CdktfProject`, `CdktfStack`, `SynthesizedStack`, outputs types) — today
  its index warns "the interfaces in this file are not stable". Phase 2 of
  this RFC is the first consumer and should start that stabilisation.
- **Rejected**: calling back into Node from inside `terraform test` via
  `external` / `local-exec` (opaque failures, arbitrary code execution
  triggered by `tofu test`). **Deferred, named**: a CDKTN-owned provider with
  a generic cloud-API data source (the `integ-tests-alpha` `awsApiCall`
  analogue, à la `cfncompat`) — it relocates the SDK-wrapper burden into Go.
- Worth stealing from `integ-runner` independently: the **snapshot tier**
  (synth, diff against a committed `cdk.tf.json`, deploy only on change).

### Explicitly out of scope

- **Hand-written test files** (copying `*.tftest.hcl` / `.tftest.json` into
  the stack directory) — see the first guiding decision.
- **`.tofutest.json` and any OpenTofu-only test semantics** — see
  [Follow-up](#follow-up--opentofu-specific-test-semantics).
- **Folding `@cdktn/vitest` into core** ([cdk-terrain#289][i289]). The Jest
  adapter is jsii-compilable only because it never imports `jest` (ambient
  `declare global` + a runtime `global.expect` check, using Jest's
  `expect.arrayContaining(...).asymmetricMatch()`); a Vitest adapter needs a
  real `import { expect } from "vitest"`, which would have to be
  jsii-excluded. The seam already works — `@cdktn/vitest` consumes the public
  `testingMatchers` factories — so new matchers reach it for free.
- **`cdktn init` template changes.** Templates stay Jest; per the
  [cdk-terrain#422][p422] discussion the template matrix does not grow a
  test-runner axis.
- **Provider-specific mock presets in core** — `MockProvider` only; presets
  are separate packages.
- `-cloud-run`, `backend` blocks in `run`, `terraform test cleanup`,
  `.tfmock` files, `hcl2cdk` conversion of test files.

## Rollout

### This repository (`cdktn-planning`)

1. `docs(rfc):` this directory — proposal, probes, sweep tooling, committed
   digests, generated matrix, Terratest research — plus the `RFCS/README.md`
   entry.
2. Follow-ups as data changes: new CLI minors (`scripts/sweep.sh` +
   `build-matrix.py`); added probes for HCL-mode modules with JSON test files
   and for an `aws`-fixture mock-validation case (open questions).

### `open-constructs/cdk-terrain`

Prerequisites first (each its own PR, reviewable in < 30 min):

1. `fix(lib):` synthesize `TerraformOutput.precondition` — closes
   [#448][i448]. **blocking**
2. `fix(lib):` testing matchers — `init -backend=false`, lock-file seeding +
   `globalSetup` warm-up helper, surfaced diagnostics — closes [#452][i452].
   **blocking**
3. `feat(lib):` `TerraformCheck` ([#449][i449]), `VariableCondition.of`
   ([#450][i450]), cross-object validation gate ([#451][i451]) —
   independent, non-blocking.

Then the RFC itself:

4. `feat(lib):` `testFeatureConstraints` (generated from
   `test-features-matrix.json`, like `function-availability.generated.ts`) +
   `TerraformTest` / `TerraformTestRun` + custom-synthesis writer
   (insertion-ordered, `tests/` ownership, own-stack guard, manifest `tests`)
   + `Testing.synthTest`.
5. `feat(lib):` `MockProvider`, overrides, `overrideRemoteState`,
   `overrideDuring` gate, literal-only mock values, preset extension points
   (`onBind`, `add*Defaults`).
6. `feat(cli-core):` `TerraformCli.init({ backend: false })`,
   `TerraformCli.test()` event parser, JUnit writer, `CdktfProject.test()`.
7. `feat(cli):` `cdktn test`.
8. `feat(lib):` `toPassTerraformTests` + source mapping + Jest adapter
   registration and `describeTerraformTest`.
9. `feat:` Phase 3 e2e mode. Docs land with each PR.

### `cdktn-io`

- `@cdktn/vitest`: register `toPassTerraformTests` / `describeTerraformTest`
  (release after step 8).
- Well-known mock preset packages (AWS first), versioned against provider
  majors — after step 5.
- `@cdktn/integ` — the long-term goal, its own RFC.

## Open questions

- Whether Terraform schedules test **files** concurrently (the research
  passes disagree; no authoritative statement found). The design assumes
  nothing: cross-file parallelism is process-level.
- Fact 5's claim that provider config validation runs under `mock_provider`
  rests on maintainer statements in the linked issues, not on a source trace
  or a probe; an `aws`-fixture probe (unpinned policy JSON → expected error)
  would make it part of the dataset, at ~700 MB of provider per CLI version.
- No dedicated upstream issue was found for mocked security groups; the
  pin-list entry comes from field experience, not from a citation.
- Should suites declared in a deployable app be omitted from
  `cdktn synth` / `deploy` output behind a context flag, or is "inert for
  plan/apply" good enough?
- Sync (`execSync`-style, jsii-friendly) vs. async matcher for long e2e runs.
- Non-TypeScript ergonomics of the construct-time variable validation
  ([cdk-terrain#450][i450]) and of subclassing `MockProvider` from a preset
  package were reasoned from jsii semantics, **not built**.
- JSON test files next to an **HCL-mode** module (`cdk.tf`) need an added
  probe before Phase 1 relies on them.
- Suggestion (originally raised by jsteinich when `targetVersions` landed):
  raise `DEFAULT_TARGET_VERSIONS` in a breaking-change release. With today's
  defaults (`terraform >=1.5.7`, `opentofu >=1.6.0`) every project must
  declare a floor before its first suite synthesizes (≥ 1.6 for the test
  framework, ≥ 1.7 / ≥ 1.8 for mocks); a higher default would make tests work
  out of the box. Could be listed as a prerequisite; noted here as an option
  only.

## Maintenance

New CLI minors append to the dataset with `scripts/sweep.sh` (idempotent —
existing digests are skipped) followed by `scripts/build-matrix.py`, which
flags regressions (a probe passing, then failing in a later version) instead
of emitting an untruthful `>=` constraint. A new test-framework feature is one
new directory under `fixture/probes/`.

[u1093]: https://github.com/hashicorp/terraform-cdk/issues/1093
[u3687]: https://github.com/hashicorp/terraform-cdk/issues/3687
[u3571]: https://github.com/hashicorp/terraform-cdk/issues/3571
[u2939]: https://github.com/hashicorp/terraform-cdk/issues/2939
[u3909]: https://github.com/hashicorp/terraform-cdk/issues/3909
[u3538]: https://github.com/hashicorp/terraform-cdk/issues/3538
[i448]: https://github.com/open-constructs/cdk-terrain/issues/448
[i449]: https://github.com/open-constructs/cdk-terrain/issues/449
[i450]: https://github.com/open-constructs/cdk-terrain/issues/450
[i451]: https://github.com/open-constructs/cdk-terrain/issues/451
[i452]: https://github.com/open-constructs/cdk-terrain/issues/452
[i385]: https://github.com/open-constructs/cdk-terrain/issues/385
[ot2338]: https://github.com/opentofu/opentofu/issues/2338
[i313]: https://github.com/open-constructs/cdk-terrain/issues/313
[i275]: https://github.com/open-constructs/cdk-terrain/issues/275
[i289]: https://github.com/open-constructs/cdk-terrain/issues/289
[p422]: https://github.com/open-constructs/cdk-terrain/pull/422
[tf31964]: https://github.com/hashicorp/terraform/issues/31964
[tf34764]: https://github.com/hashicorp/terraform/issues/34764
[tf35451]: https://github.com/hashicorp/terraform/issues/35451
[aws36700]: https://github.com/hashicorp/terraform-provider-aws/issues/36700
[aws42834]: https://github.com/hashicorp/terraform-provider-aws/issues/42834
[ot2140]: https://github.com/opentofu/opentofu/pull/2140
[ot2144]: https://github.com/opentofu/opentofu/pull/2144
[ot3069]: https://github.com/opentofu/opentofu/pull/3069
[ot1778]: https://github.com/opentofu/opentofu/issues/1778
[ot4567]: https://github.com/opentofu/opentofu/issues/4567
[ot2542]: https://github.com/opentofu/opentofu/issues/2542
[ot2501]: https://github.com/opentofu/opentofu/issues/2501
[ot3876]: https://github.com/opentofu/opentofu/issues/3876
