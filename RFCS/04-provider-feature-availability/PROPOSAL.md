# Proposal: Support newer provider plugin-protocol features with targetVersions-aware codegen

Status: **proposed** · Companion dataset (`features-matrix.json`), interactive
report (`report.html`) and sweep tooling (`scripts/`) live next to this file —
the same shape as `tools/generate-function-bindings/function-availability`,
but sweeping `<binary> providers schema -json` instead of
`metadata functions -json`.

## Problem

The provider plugin protocol has grown five capability families since the
schema model CDKTN understands was written, and Terraform/OpenTofu have
**diverged** on which of them exist at all:

| Feature | Schema JSON surface | Protocol | Terraform emits | OpenTofu emits |
| --- | --- | --- | --- | --- |
| Provider-defined functions | `functions` | 5.5 / 6.5 | ≥ 1.8.0 | ≥ 1.8.0 (language support since **1.7.0**) |
| Ephemeral resources | `ephemeral_resource_schemas` | 5.7 / 6.7 | ≥ 1.10.0 | ≥ 1.11.0 |
| Write-only attributes | attribute flag `write_only` | 5.8 / 6.8 | ≥ 1.11.0 | ≥ 1.11.0 |
| Resource identity | `resource_identity_schemas` | 5.9 / 6.9 | ≥ 1.12.0 | ≥ 1.12.0 |
| List resources / `terraform query` | `list_resource_schemas` | 5.10 / 6.10 | ≥ 1.14.0 | — (opentofu/opentofu#3787 open) |
| Actions | `action_schemas` | 5.10 / 6.10 | ≥ 1.14.0 | — |
| Pluggable state stores | `state_store_schemas` | 6.11 (proto 6 only) | ≥ 1.15.0 (not GA in core) | — |

(Deferred actions — protocol 5.6/6.6 — have no `providers schema -json`
surface and never left experimental in Terraform; excluded.)

CDKTN currently ignores all of it:

- `packages/@cdktn/commons/src/provider-schema.ts:18-22` models a provider as
  exactly `provider` + `resource_schemas` + `data_source_schemas`; none of the
  keys above exist in the type system.
- `packages/@cdktn/provider-schema/src/provider-schema.ts:315-320`
  (`sanitizeProviderSchema`) walks only those three sections, and
  `packages/@cdktn/provider-generator/src/get/generator/provider-generator.ts:156-182`
  builds models only for resources/data sources. A provider that ships
  ephemeral resources or functions (e.g. `random` ≥ 3.7.0, `time` ≥ 0.11.0)
  generates bindings with those sections silently dropped.
- `write_only` is declared nowhere; write-only attributes (e.g. the `*_wo`
  pairs in the vault provider) are generated as ordinary attributes, including
  a state-backed getter — but providers never persist write-only values, so
  every read of that token is `null` by protocol contract. The generated
  getter is a trap.
- Schema **acquisition** is silently version-sensitive: the new keys are fixed
  fields on the CLI's internal `jsonprovider` serializer, so an old binary
  *structurally cannot* emit them (verified per release tag; see the matrix).
  This repo pins Terraform **1.7.5** via mise — a `cdktn get` run with it can
  never see functions or ephemeral resources, regardless of provider version.
  Worse, `packages/@cdktn/provider-schema/src/cache.ts:10-16` keys the cache
  on `fqpn@version` only, so a schema fetched once with an old CLI poisons
  every later generation until the cache is cleared.

Meanwhile #237 > #269 > #268 gave projects a way to declare what they run against —
`targetVersions` in `cdktf.json` (`packages/@cdktn/commons/src/config.ts:283-302`,
default `{ terraform: ">=1.5.7", opentofu: ">=1.6.0" }`) — and the
function-availability work built the synth-time enforcement machinery:
`resolveTargetVersions` + `checkFeatureSupportedByTargets`
(`packages/cdktn/src/validations/target-versions.ts:45-146`),
`ValidateFeatureTargetSupport` (`target-versions.ts:157-178`), and the
usage-registry pattern (`packages/cdktn/src/functions/usage-registry.ts`).
This proposal extends that exact model from built-in functions to
provider-protocol features.

## Data: the comparison report

`scripts/sweep.sh` downloads every minor-boundary release of both products
(Terraform 1.5.7 → 1.15.x, OpenTofu 1.6.0 → 1.12.x), runs `init` +
`providers schema -json` against two fixtures, and commits compact digests
under `data/`:

- **core** (all versions): small providers chosen per feature — `random`
  3.9.0 and `tls` 4.2.0 for ephemeral, `time` 0.13.0 and `local` 2.8.0 for
  functions and actions, `vault ~> 5.0` for `write_only`.
- **aws** (`hashicorp/aws` 6.14.1, CLI ≥ 1.12 only): the only provider that
  ships the families the utility providers lack — resource identity, list
  resources, and cloud actions (`aws_lambda_invoke`). Its raw schema dump is
  >100 MB per CLI version, so digests cap every name list at 50 entries
  (full totals in a `counts` block) and the raw dump is not retained; columns
  below 1.12 are skipped because no new section is emitted there anyway.
`scripts/build-matrix.py` merges the observed evidence with a source-verified
overlay (protocol minors from the `tfplugin6.proto` headers at each
terraform-plugin-go tag; CLI emission boundaries from
`internal/command/jsonprovider` at each core release tag) and flags any
contradiction between the two. `scripts/build-report.py` renders `report.html`.

Key facts the data establishes:

1. **Emission is a property of the fetching CLI, not just the provider.** The
   same `random` 3.9.0 schema contains `ephemeral_resource_schemas` under
   Terraform ≥ 1.10 / OpenTofu ≥ 1.11 and lacks it under anything older.
2. **The products have genuinely forked** at the top of the matrix: list
   resources, actions and state stores are Terraform-only today, so "supported
   by Terraform X" is no longer a proxy for "supported by OpenTofu Y" — only
   a per-product constraint matrix (`TerraformFeatureVersionConstraints`)
   expresses this correctly.
3. **No removals, no gaps** in either product within the swept range, so —
   exactly like function availability — simple `>=x.y.z` per-product
   constraints suffice; no version-set bookkeeping needed.
4. **Every emission boundary except state stores is now empirically
   confirmed.** The aws fixture observes resource identity (475 resources)
   from Terraform 1.12.0 *and* OpenTofu 1.12.0 — with identical
   `resource_identity_schemas` shape — plus list resources (4) and cloud
   actions (5, including `aws_lambda_invoke`) from Terraform 1.14.0, absent
   under OpenTofu. Only `state_store_schemas` remains documented-only: no
   provider implements it because `state_store` is not GA in core.

## Design

Guiding decision: **generate the full surface the schema offers; narrow per
project at synth time via targetVersions.** Generation-time filtering would
fork the generated API by project configuration — impossible for prebuilt
providers (generated once, consumed everywhere) and hostile to caching. The
function-availability work already proved the alternative: ship the superset,
record usage, validate against `resolveTargetVersions()` during synth. The
constraints baked into generated code are exactly the per-product `>=` ranges
from this dataset.

A small hand-maintained map in core (sourced from `features-matrix.json`, in
the spirit of `function-availability.generated.ts`):

```ts
// packages/cdktn/src/provider-feature-constraints.ts
export const providerFeatureConstraints = {
  providerFunctions: { terraform: ">=1.8.0", opentofu: ">=1.7.0" }, // language support, not schema emission
  ephemeralResources: { terraform: ">=1.10.0", opentofu: ">=1.11.0" },
  writeOnlyAttributes: { terraform: ">=1.11.0", opentofu: ">=1.11.0" },
  resourceIdentity: { terraform: ">=1.12.0", opentofu: ">=1.12.0" },
} as const satisfies Record<string, TerraformFeatureVersionConstraints>;
```

### Phase 0 — schema acquisition correctness (`@cdktn/provider-schema`)

Prerequisite for everything else, and a bugfix on its own:

1. Extend the commons types (`commons/src/provider-schema.ts:18-22`) with
   `functions`, `ephemeral_resource_schemas`, `resource_identity_schemas`, and
   `write_only?: boolean` on `BaseAttribute` (line 53-61). List/action/state-
   store sections are *not* typed yet (YAGNI — nothing consumes them; they
   pass through untouched since `sanitizeProviderSchema` mutates in place).
   Extend the sanitizer's entity walk to `ephemeral_resource_schemas` so the
   attribute-doubling fix applies to ephemeral schemas too.
2. Record the fetching CLI in the schema payload next to the existing
   `provider_versions` attachment (`provider-schema.ts:282`):
   `{ cli_name, cli_version }` from the `terraform version -json` call that
   already runs at `provider-schema.ts:276-280`.
3. Make the cache honest: include the fetching CLI product + minor in the
   cache key (`cache.ts:12-16`), so upgrading the CLI naturally re-fetches
   richer schemas instead of serving section-less ones forever.
4. Warn at fetch time when the CLI is the bottleneck: if the configured
   `targetVersions` admit a product/version whose features the fetching binary
   cannot emit (e.g. targets allow `terraform >=1.10` but `cdktn get` ran with
   1.7.5), log
   `"provider schema fetched with terraform 1.7.5 — ephemeral resources and provider functions will not be generated; run cdktn get with terraform >=1.10 / opentofu >=1.11"`.
   The emission boundaries come from the same constraints map.

### Phase 1 — ephemeral resources (core + generator)

- **Core:** new `TerraformEphemeralResource` base class in
  `packages/cdktn/src` (sibling of `terraform-resource.ts` /
  `terraform-data-source.ts`), synthesizing into the top-level `ephemeral`
  key of `cdk.tf.json` (JSON syntax mirrors `resource`/`data`). Its
  constructor registers
  `ValidateFeatureTargetSupport("ephemeral resources", providerFeatureConstraints.ephemeralResources, hint)`
  on the stack — so a project whose `targetVersions` still admit
  `terraform 1.9` gets a synth-time error naming the offending range, in the
  established message format of `target-versions.ts`.
- **Generator:** third loop in `buildResourceModels`
  (`provider-generator.ts:165-182`) over `ephemeral_resource_schemas` with an
  `ephemeral_` name prefix (mirroring `data_`), giving
  `EphemeralRandomPassword`-style classes in `ephemeral-random-password/`
  namespace dirs; fourth branch in `ResourceModel.parentClassName`
  (`resource-model.ts:117-123`) returning `TerraformEphemeralResource`;
  `resource-emitter.ts` super-call variant stripping the prefix for
  `terraformResourceType`.
- `hcl2cdk` conversion of `ephemeral {}` blocks: follow-up, tracked not built.

### Phase 2 — provider-defined functions (generator + core)

- Schema `functions` entries share the `FunctionSignature` shape that
  `tools/generate-function-bindings/scripts/generate.ts` already consumes —
  reuse its parameter/return-type mapping to emit one
  `provider-functions.ts` per provider package:
  `TimeProviderFunctions.rfc3339Parse(ts)` →
  `${provider::time::rfc3339_parse(...)}`. The `provider::<local-name>::`
  namespace is the provider's **local name** in `required_providers`; the
  generated static methods default it to the provider's registry short name
  and accept an override parameter for renamed providers (documented edge
  case — aliases don't change the namespace, local names do).
- Usage flows through the same chokepoint pattern as `Fn.*`
  (`helpers.ts:160-165`): record into the existing usage registry under a
  product-constraint of `providerFeatureConstraints.providerFunctions`. Note
  the asymmetry the dataset surfaced: the **usage** constraint for OpenTofu is
  `>=1.7.0` (language support) even though schema **emission** starts at
  1.8.0 — generation and validation deliberately use different boundaries.

### Phase 3 — write-only attributes (generator + core)

- Map `write_only` onto `AttributeModel` (`attribute-model.ts:23-36`, which
  today doesn't even model `sensitive`). Setter stays; the getter is emitted
  `@deprecated` with a doc comment stating the protocol contract (providers
  always return `null` for write-only attributes — there is nothing to read).
  Removing the getter outright is the right end state but is JSII-breaking
  for regenerated/prebuilt providers, so: deprecate now, remove at the next
  prebuilt major.
- Setting any write-only attribute registers feature usage
  (`writeOnlyAttributes` constraints) — synth fails for projects whose
  targets admit `terraform <1.11` / `opentofu <1.11`, with the standard
  upgrade-or-narrow-targets message.

### Phase 4 — explicitly deferred

- **Resource identity**: consume `resource_identity_schemas` to type
  import-by-identity (`generateConfigForImport`,
  `resource-emitter.ts:59-80`). The ecosystem is further along than the
  utility providers suggest — aws 6.14.1 ships identity on 475 resources and
  both products emit it from 1.12 — so this is the first Phase 4 item to
  promote; schema plumbing from Phase 0 already carries it.
- **List resources / actions / state stores**: Terraform-only, ecosystem
  thin (actions: 5 in aws 6.14.1 plus `local` ≥ 2.6.0; list resources: 4 in
  aws; state stores not GA). Re-evaluate when OpenTofu's position is known
  (opentofu/opentofu#3787) — adding a Terraform-only construct family to a
  JSII surface consumed by both communities is a product decision, not just
  codegen.

### targetVersions threading into `cdktn get`

Today the generator never sees the project config: `handlers.ts:307-360`
reads `cdktf.json` (so `config.targetVersions` is in scope) but forwards only
language options; `GetOptions`
(`provider-generator/src/get/constructs-maker.ts:247-260`) has no config.
Thread `targetVersions` through `Get` props → cli-core `get()` →
`ConstructsMaker` — **not to filter codegen** (see guiding decision) but to:

1. drive the Phase 0 fetch-time warning (targets vs fetching-CLI capability),
2. stamp the generated package (`versions.json` / header comment) with the
   targets and fetching CLI it was generated under, for diagnostics and cache
   debugging.

### Testing

- Generator: snapshot tests against committed real-schema fragments from the
  sweep fixtures (`random` ephemeral, `time` functions, `vault` `*_wo`
  attributes) — no network.
- Core: mirror `packages/cdktn/test/validations.test.ts` — targets that
  admit/exclude each feature, both products, hint text for product-exclusive
  cases.
- Integration: a `typescript/synth-app`-style test using ephemeral
  `random_password`, gated on a CI Terraform ≥ 1.10.

### Rollout / PR split (constitution: reviewable < 30 min each)

1. `chore:` this directory — dataset, report, proposal (no behavior change).
2. `feat(lib):` `providerFeatureConstraints` map + `TerraformEphemeralResource`
   + validation wiring + tests.
3. `feat(provider-generator):` Phase 0 schema types/sanitizer/cache-key +
   fetch-time warning.
4. `feat(provider-generator):` ephemeral resource codegen + snapshots.
5. `feat(provider-generator):` provider function bindings + usage validation.
6. `feat(provider-generator):` `write_only` handling (deprecated getter).
7. `feat(cli):` targetVersions threading into `cdktn get` + package stamping.

No feature flag is needed for Phases 1-2: the generated classes/methods are
new API surface, so no existing project can break by their existence, and the
synth-time validation only fires on use. Phase 3's getter deprecation is the
only behavior change to existing generated code and rides the prebuilt-major
train instead of a flag.

## Why not validate at plan time / leave it to Terraform?

Same rationale as the function-availability proposal: the user's binary error
arrives at `terraform plan`, far from the CDK construct that caused it, and
only for the binary they happen to run — not for the range their project
declares to support. `targetVersions` exists precisely so a library/module
author can say "this must work on Terraform 1.9 *and* OpenTofu 1.8"; only a
synth-time check against the declared range catches "works on my machine,
breaks for the OpenTofu half of my users" before release.

## Maintenance

New CLI minors append to the dataset the same way `pnpm
update-function-matrix` does for functions: one `providers schema -json` run
per new release against the pinned fixture (`scripts/sweep.sh` is idempotent —
existing digests are skipped). The documented overlay in
`scripts/build-matrix.py` only needs touching when a *new* protocol capability
ships, and `build-matrix.py` fails loudly if observation ever contradicts the
overlay (e.g. OpenTofu ships list resources — the `!!` sanity check fires and
the matrix must be re-verified before regeneration).
