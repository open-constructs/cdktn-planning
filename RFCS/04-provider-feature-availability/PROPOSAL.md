# Proposal: Support newer provider plugin-protocol features with targetVersions-aware codegen

Status: **proposed** · Companion dataset (`features-matrix.json`), interactive
report (`report.html`) and sweep tooling (`scripts/`) live next to this file —
the same shape as [`../03-function-availability`](../03-function-availability/)
(copied into cdk-terrain as `tools/generate-function-bindings/function-availability`),
but sweeping `<binary> providers schema -json` instead of
`metadata functions -json`. A second dataset (`cli-matrix.json`,
`cli-report.html`) covers the CLI command/flag surface — see
[CLI command/flag surface](#cli-commandflag-surface).

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

`scripts/sweep.sh` installs (via mise) every minor-boundary release of both
products plus each product's latest patch (Terraform 1.5.7 → 1.17.0,
OpenTofu 1.6.0 → 1.13.2), runs `init` + `providers schema -json` against two
fixtures, and commits compact digests under `data/`:

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
5. **The October 2026 refresh (Terraform 1.16.0 / 1.17.0, OpenTofu
   1.13.0 / 1.13.2) changes no boundary.** Both new Terraform minors emit the
   same per-provider top-level keys and aws counts as 1.15.6; OpenTofu 1.13
   still emits no `list_resource_schemas`, `action_schemas` or
   `state_store_schemas` (aws 6.14.1: 0 list resources / 0 actions vs 4 / 5
   under Terraform). Terraform 1.16's computed nested blocks
   (hashicorp/terraform#38305) are a `configschema` change only — the
   `jsonprovider` block struct has no computed flag through 1.17.0, so it is
   not visible in `providers schema -json`. The floating `vault ~> 5.0` pin
   resolved to 5.13.0 for the new columns (5.9.0 before).

## Design

**Foundation (landed, PR #269).** The `targetVersions` config field,
`resolveTargetVersions()`, the `ValidateFeatureTargetSupport` validation, and
the `TerraformFeatureVersionConstraints` type already exist in
`packages/cdktn/src/validations/`. They are **internal by design** — consumed
by cdktn's own base classes via relative import, and by `@cdktn/commons` via
the `cdktn/lib/validations` subpath, *not* re-exported from the package root.
Generated bindings reach this machinery by **extending cdktn base classes**
(e.g. `TerraformEphemeralResource`, below), never by calling the validator
directly, so the validation never crosses the jsii contract and no public/jsii
validation surface is required. (Public export was considered and deliberately
deferred — revisit only if a third-party, non-cdktn construct author needs to
validate a novel feature the matrix below does not cover.) `cdktn` remains the
single canonical owner of the `providerFeatureConstraints` matrix and the
validators; the generator carries no version knowledge of its own.

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
   wiring the **existing** `ValidateFeatureTargetSupport` (landed in #269) into
   the base-class constructor + tests. The validation primitive itself is done.
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

## CLI command/flag surface

`scripts/cli-sweep.sh` builds three per-version datasets at the first and
last stable patch of every minor line (24 Terraform binaries 1.5.7 → 1.17.0,
16 OpenTofu binaries 1.6.0 → 1.13.2):

- **listed** (`data/cli-surface-*.json`): what `<binary> [cmd [sub]] -help`
  documents, parsed by `scripts/cli_help.py`.
- **accepted** (`data/cli-source-check-*.json`): what the flag parser
  registers, read from the Go source of the same tag by
  `scripts/cli-source-check.py`, for **every** registered command (it walks
  `(*<Type>).Run` → `arguments.Parse*/Bind*` → flag-set helpers, `Meta`
  flag sets, `Meta.process` and OpenTofu ≥ 1.13 `*Commander`).
- **probed** (`data/cli-probe-*.json`): `scripts/cli-probe.py` runs every
  candidate flag (any flag either product lists or registers for that
  command, at any version) against the real binary and compares the output
  with a baseline run that uses a flag no version defines. 24,175 runs at all
  40 versions: **0 disagreements** with the source check
  (`cli-matrix.json` → `summary.probe`).

`build-cli-matrix.py` merges them into `cli-matrix.json`; every
command × flag has a `listed` span, an `accepted` span and one status letter
per swept version (`cells`: L listed+accepted, R accepted via a help
reference, H accepted but not listed, X listed but rejected, - neither).
`build-cli-report.py` renders `cli-report.html`. Method, parser rules and
caveats are in `README.md` ("CLI command/flag surface sweep").

How to read the numbers:

- **"Since" means accepted since.** Every "since" below is the first swept
  version whose parser accepts the flag (listed-since is given separately
  where it differs). Help is not a reliable proxy: Terraform has always
  accepted `import -parallelism`, `refresh -replace/-destroy/-refresh-only`
  and `state push -ignore-remote-version` without listing them; OpenTofu
  accepts `apply -concise` from 1.7.0 but lists it from 1.10.0. Because
  versions are sampled per minor (first + last patch), an item first seen at
  `X.Y.0` shipped in `(previous swept version, X.Y.0]`.
- **Accepted ≠ usable.** The parser accepts some flags that the command then
  refuses in release builds: Terraform `-allow-deferral` ("only valid in
  experimental builds"), `test -junit-xml` 1.8–1.11 ("available only in
  alpha releases"). These count as accepted (the flag parses) and are
  marked by being accepted but never listed.
- **"View family".** OpenTofu registers its output/diagnostic flags
  (`-no-color`, `-compact-warnings`, `-concise`, `-consolidate-warnings`,
  `-consolidate-errors`, `-deprecation`, `-json`, `-json-into`, `-lint`,
  `-show-sensitive`, `-input`) through one view helper (`ParseView`, then
  `BindView` in 1.13) and, since 1.13, lists them on nearly every command.
  They are tagged `family: "view"` and counted separately.

### Totals

| | Terraform | OpenTofu |
| --- | --- | --- |
| swept versions (help + source + probe) | 24 | 16 |
| product-only commands | 5 (`query` 1.14, `modules` 1.10, `stacks` 1.13 — external plugin, `state identities` 1.12, hidden `rpcapi`) | 3 hidden aliases (`state ls`, `state move`, `state remove`, 1.7) |
| command × flag pairs accepted or listed | 724 (570 listed in help at some version) | |
| product-only pairs, by accepted-or-listed | 48 (40 excl. view family) | 373 (77 excl. view family) |
| product-only pairs, by help listing alone | 28 | 331 |
| flags accepted but not listed (newest version, all commands) | 102 | 136 |
| flags listed but rejected by the parser | `state replace-provider -state-out` (all versions) | `state replace-provider -state-out` (all versions), `destroy -lint` (1.13) |
| commands registered but hidden from help | 7 (`env *`, `push`, `rpcapi`) + experimental-build-only `cloud`, `state migrate`, `test cleanup` | 9 (`env *`, `push`, `state ls/move/remove`) |
| global options | `-chdir`, `-help`, `-version` (both) | + `-install-autocomplete`, `-uninstall-autocomplete` listed (Terraform accepts both too via `mitchellh/cli` `Autocomplete: true` in `main.go`, unlisted) |

### Key product-only commands and flags

Terraform-only (accepted by no swept OpenTofu version):

| Command / flag | Accepted since | Listed since / note |
| --- | --- | --- |
| `query` (+ `-generate-config-out`, `-json`, `-var`, `-var-file`), `validate -query` | 1.14.0 | list resources / `.tfquery.hcl` |
| `query -policies` | 1.16.0 | listed 1.17.0 |
| `plan` / `apply` / `destroy` / `refresh` `-minimal-refresh` | 1.17.0 | refresh: not listed; apply/destroy via the plan-options reference |
| `console -scope`, `graph -format` | 1.16.0 | |
| `init -state-provider-lock-file` | 1.16.0 | pluggable state storage |
| `init -enable-pluggable-state-storage-experiment` | 1.14.0 | listed 1.15.0; experimental |
| `init -create-default-workspace` | 1.15.x only | rejected again from 1.16.0 |
| `state identities` (`-id`, `-state`, `-json`) | 1.12.0 | resource identity |
| `modules` (`-json`; `-var`/`-var-file` 1.15) | 1.10.0 | `-json` ships with the command |
| `test -parallelism` 1.12, `test -cloud-run` 1.6, `test -junit-xml` 1.5.7 | | `-junit-xml` alpha-only at runtime 1.8–1.11 |
| `console -plan` | 1.7.0 | |
| `providers lock -enable-plugin-cache` 1.8, `providers mirror -lock-file` 1.9, `providers lock -test-directory` 1.14.x patch (accepted at 1.14.9, not 1.14.0) | | |
| never listed: `plan`/`apply`/`destroy`/`refresh` `-allow-deferral` (1.9, experimental builds only), `-invoke` (actions, 1.14); `plan`/`apply`/`destroy`/`init` `-policies` (1.16); `test -run-parallelism` 1.13, `-repair` 1.14 | | accepted, not in help |

OpenTofu-only (accepted by no swept Terraform version; excluding the view
family):

| Command / flag | Accepted since | Listed since / note |
| --- | --- | --- |
| `plan`/`apply`/`destroy`/`refresh` `-exclude` | 1.9.0 | |
| `plan`/`apply`/`destroy`/`refresh` `-exclude-file`, `-target-file` | 1.10.0 | refresh: listed 1.13.0 |
| `apply`/`destroy` `-suppress-forget-errors` | 1.12.0 | `removed` blocks with `destroy = false` |
| `show -state`/`-plan` (explicit target selection) 1.10, `show -config` 1.11, `show -module` 1.11 | | `show -module` listed 1.13.0 |
| `providers lock -oci-mirror` | 1.13.0 | OCI registry mirrors |
| `console -lock`, `-lock-timeout` | 1.12.0 | |
| `-var` / `-var-file` on `output`, `force-unlock`, `untaint`, `state list/show`, `workspace delete/list/new/select` | 1.8.0 | early static evaluation; Terraform 1.15 added `-var` to most other commands (`get`, `graph`, `providers *`, `state mv/pull/push/rm/replace-provider`, `taint`, `validate`, hidden on `show`) but not to these |
| `-exclude` on `console`, `import`, `init`, `login`, `workspace show` (and the `workspace`/`env` parents) | 1.9.0 – 1.11.x | never listed; dropped from those parsers in 1.12.0 together with `-target` (Terraform still accepts `-target` there) |
| `version -chdir` | 1.13.2 | never listed |
| view family: `-concise` (plan listed 1.7; apply accepted 1.7, listed 1.10), `-consolidate-warnings`/`-errors` (1.9), `-show-sensitive` (plan/apply 1.9), `-deprecation` (1.10; until 1.12 only in the form `-deprecation=module:…`), `-json-into` (1.12), `-lint` (1.13) | | listed on most commands from 1.13 |

**Not product-only** (the previous, help-only revision of this table
labelled them OpenTofu-only since 1.13.0): `refresh -destroy`, `-refresh`,
`-refresh-only`, `-replace`; `import -parallelism`; `state push
-ignore-remote-version`. Both products accept them at every swept version;
OpenTofu 1.13 merely started listing them.

### Notable recent changes

- **Terraform 1.16:** `console -scope`, `graph -format`,
  `init -state-provider-lock-file`, hidden `-policies` on plan/apply/destroy/
  init/query; `init -create-default-workspace` (1.15) is rejected again.
- **Terraform 1.17:** `plan`/`apply`/`destroy`/`refresh -minimal-refresh`
  (listed on plan only, apply/destroy via the plan reference, refresh not at
  all); `query -policies` becomes listed.
- **OpenTofu 1.12:** `console -lock`/`-lock-timeout`,
  `-suppress-forget-errors`, `-json-into`; `-exclude` and `-target` are no
  longer accepted by `init`, `console`, `import`, `login`, `workspace show`
  (Terraform still accepts `-target` on all of them).
- **OpenTofu 1.13:** help is generated from the flag definitions — every
  command now documents the view family and its real operation flags
  (e.g. `refresh` lists `-target-file`/`-exclude-file`/`-replace`, accepted
  since 1.6–1.10), `destroy` lists its own flags instead of pointing at
  `plan -help`, and the legacy `-state`/`-state-out`/`-backup` flags vanish
  from help (`SetHidden(true)`; still accepted — cells `H`). New: `-lint`,
  `providers lock -oci-mirror`, `version -chdir` (hidden, 1.13.2).

### Help vs source disagreements

- **Listed but rejected** (cells `X`): `state replace-provider -state-out`
  — both products' help says "-state, state-out, and -backup are legacy
  options", but the parser registers only `-state` and `-backup` (probe:
  "flag provided but not defined: -state-out") at every swept version.
  OpenTofu 1.13 `destroy` help (generated) lists `-lint`, but
  `BindApplyDestroy` calls `bindApply(cli, false)`, which drops the lint
  view flag — `tofu destroy -lint` is rejected.
- **Accepted, never listed** (newest versions): Terraform `plan`/`apply`/
  `destroy` `-json`, `-invoke`, `-allow-deferral`, `-policies`, plan
  `-state-out`/`-backup`; `init -cloud`, `-compact-warnings`, `-policies`,
  `-target`; `import -parallelism`/`-target`; `refresh` operation flags;
  `state push -ignore-remote-version`; `-no-color` on every legacy command
  (`Meta.process`); `version -v`/`-version`. OpenTofu: legacy
  `-state`/`-state-out`/`-backup` (hidden since 1.13), `init -cloud`,
  `graph -verbose`, `version -chdir`.
- Terraform's `import`, `refresh`, `taint`, `untaint`, `state mv` and
  `state replace-provider` name their legacy flags only in prose ("-state,
  state-out, and -backup are legacy options"); the parser now records them
  from that line (`via: legacy-prose`), so they appear as listed.

### Relation to cdk-terrain PR #513 (reject unknown options)

[open-constructs/cdk-terrain#513](https://github.com/open-constructs/cdk-terrain/pull/513)
(open, fixes #168) adds `rejectUnknownOptions`
(`packages/cdktn-cli/src/bin/unknown-options.ts`) as a global yargs
middleware: it compares the parsed `argv` keys with the current command's
`getOptions().key` and aliases (kebab and camel case), always accepts
`--color`/`--no-color`/`--get-yargs-completions`, ignores keys that only
came from `CDKTF_*` environment variables (the CLI calls `.env("CDKTF")`,
which is why `.strictOptions()` was not usable), skips the `*` catch-all
command, and throws `Errors.Usage("Unknown argument: …")` before the handler
runs. It drops the per-command `.strict()` on `init`/`login` in favour of
the middleware and declares the previously undeclared
`synth --show-performance-info`.

**How cdktn passes options to terraform/tofu today** (cdk-terrain `main`):
there is no pass-through. The binary is `TERRAFORM_BINARY_NAME` (default
`terraform`); every flag is a literal built in `@cdktn/cli-core`
(`models/terraform-cli.ts`, `models/deploy-machine.ts`) or
`@cdktn/provider-schema`, mostly derived from declared cdktn options:

| cdktn option / situation | Binary invocation |
| --- | --- |
| `deploy`/`diff`/`destroy` `--migrate-state`; provider upgrades | `init [-upgrade] [-no-color] [-migrate-state]` |
| lock-file update (unless `--skip-provider-lock`) | `providers lock -platform=linux_amd64 [-no-color]` |
| `diff` | `plan -input=false [-generate-config-out=…] [-out plan] [-destroy] [-refresh-only] [-parallelism=N] [-no-color] -var=… -var-file=…` |
| `deploy` | `apply [-auto-approve] [-refresh-only] [-no-color] [-parallelism=N] -var=… -var-file=…` |
| `destroy` | `destroy [-auto-approve] [-no-color] [-parallelism=N] -var=… -var-file=…` |
| `--terraform-parallelism` | `-parallelism=N` on plan/apply/destroy |
| `output` / `deploy --outputs-file` | `output -json` |
| `get` | `init`, `providers schema -json`, `version -json`, `get` |

`createAndStartDeployService` / `createAndStartDestroyService` accept an
`extraOptions: string[]` that is spread into the argv, but no caller sets it
(always `[]`). `cli-matrix.json` → `cdktn_emitted` checks each emitted flag:
**all 28 are accepted by every swept version of both products**
(`providers lock -no-color` is source-verified — help lists it only on
OpenTofu ≥ 1.13), so the CLI needs no per-version gating today.

**What #513 rejects, per product and version.** Because nothing is
forwarded, #513 cannot reject a flag that used to reach the binary. Every
terraform-style flag a user types was already ignored before #513 — the
footgun from #168 — and is now an error:

| User types | Before #513 | After #513 | Would the binary accept it? (parser, probe-verified) |
| --- | --- | --- | --- |
| `cdktn deploy --target=aws_instance.a` | silently applies **everything** | `Unknown argument: target` | both, all versions (apply via plan reference) |
| `cdktn deploy --replace=…` | silently ignored | rejected | both, all versions |
| `cdktn deploy --exclude=…` | ignored | rejected | OpenTofu ≥ 1.9 only |
| `cdktn diff --minimal-refresh` | ignored | rejected | Terraform ≥ 1.17 only |
| `cdktn deploy --lock-timeout=60s` | ignored | rejected | both, all versions |
| `cdktn deploy --concise` / `--show-sensitive` | ignored | rejected | OpenTofu only (apply: `-concise` ≥ 1.7, listed in help from 1.10; `-show-sensitive` ≥ 1.9) |
| `cdktn deploy -target=aws_instance.a` (single dash) | ignored, **and `--app` silently set to `""`** | `Unknown arguments: t, r, g, e` | — |
| `cdktn deploy -- -target=…` | the token becomes a stack name | unchanged | — (never forwarded) |

The single-dash row: yargs 17.7.3 (cdk-terrain's version) reads `-target=x`
as the short-option group `-t -a -r -g -e`, with the `=x` value attached to
the last letter seen as taking one. Parsed with `deploy`'s declared options
(`--app` alias `-a`, `--output` alias `-o`) it yields
`{t: [true, "aws_instance.a"], a: "", app: "", r: true, g: true, e: true}`.
`a` is a declared alias, so #513 does not report it: the error is
`Unknown arguments: t, r, g, e`, and `app` has already been overwritten
with `""` (likewise `o`/`--output` when the token contains an `o`, e.g.
`-lock-timeout=60s`; `-replace=…` also hits `a`). Before #513 that empty
`app` replaced the `app` command from `cdktf.json` without any message; #513
turns it into an error, which is the right outcome even though the message
names the wrong letters.

So "falsely rejected" pass-through flags do not exist today, and nothing is
"falsely accepted" either: the only accepted options are cdktn's own, all
of which map onto flags every swept binary accepts. The real escape hatch is
untouched by #513: `TF_CLI_ARGS` / `TF_CLI_ARGS_plan` / `TF_CLI_ARGS_apply`
(honoured by both products; cli-core forwards `process.env`), e.g.
`TF_CLI_ARGS_apply="-target=aws_instance.a" cdktn deploy`. That path is
validated by nobody — a flag the selected binary does not know fails inside
the binary after synth.

**Recommendation.**

1. Merge #513 as is; it is correct for cdktn's own option surface. Two small
   follow-ups: (a) when an unknown key matches a terraform/tofu flag of the
   mapped command in `cli-matrix.json`, say so in the error: "`--target` is
   a Terraform flag; cdktn does not forward binary flags — use
   `TF_CLI_ARGS_apply`"; (b) detect the single-dash spelling from the raw
   argv token (`process.argv` entry matching `^-[a-z][a-z-]+(=|$)`), not from
   the reported letters: letters that are aliases of declared options (`a`
   → `--app`, `o` → `--output`, …) are consumed silently and missing from
   the unknown list, so `t, r, g, e` alone cannot be mapped back to
   `-target`. The hint should name the token ("`-target=aws_instance.a`
   looks like a Terraform flag") and note that it also set `--app`; (c) keep
   the catch-all and env-var exemptions.
2. Do not add a generic pass-through. If one is added (wiring the unused
   `extraOptions`, or forwarding argv after `--`), or for the
   `TF_CLI_ARGS_*` env vars, validate against a **generated allowlist**:
   `build-cli-matrix.py` → `terraform-cli-flags.generated.ts` in
   `@cdktn/cli-core`, `{ [command]: { [flag]: { terraform?: ">=1.5.7",
   opentofu?: ">=1.9.0", takesValue, hidden? } } }` — the same shape and
   regeneration flow as `function-availability.generated.ts`
   (`pnpm update-cli-matrix` appending new releases forward-only). Build it
   from the **accepted** sets (source check, verified by the binary probe),
   not the help-listed ones: help omits flags both parsers accept
   (`import -parallelism`, `refresh -replace` on Terraform; legacy
   `-state*` on OpenTofu 1.13) and lists two that are rejected
   (`state replace-provider -state-out`, OpenTofu 1.13 `destroy -lint`).
   `cli-matrix.json` → `allowlist_preview` is that table today
   (e.g. `refresh -replace: {terraform: "*", opentofu: "*"}`,
   `apply -concise: {opentofu: ">=1.7.0"}`); `hidden: true` marks flags no
   help lists, `takesValue` comes from the registration kind.
3. **When to validate:** at command start, before synth (the point of #168
   is not to pay for a synth on a typo), against the binary detected by the
   existing `terraformCli()` probe (`@cdktn/commons/src/terraform.ts`, name +
   version).
   - **error** when the detected product/version is known and the flag is
     not in its accepted set (it would fail in the binary anyway, but after
     synth and with a less clear message). Only accepted sets make this
     safe: with help-listed sets this rule would wrongly reject
     `terraform import -parallelism` or `terraform refresh -replace`;
   - **warn** when the flag is accepted by the detected binary but not
     across the project's `targetVersions` range (portability, mirroring the
     RFC-03 function check), or when it is `hidden` (accepted but
     undocumented; some are refused later at runtime in release builds, e.g.
     Terraform `-allow-deferral`);
   - **warn only** (never block) when the probe fails or the binary is newer
     than the matrix — a new minor may add the flag.
4. Prefer first-class, gated cdktn options for the frequently requested
   flags over a pass-through: `--target` and `--replace` (both products, all
   supported versions), `--exclude` (OpenTofu ≥ 1.9: error on Terraform),
   `--minimal-refresh` (Terraform ≥ 1.17: error on OpenTofu or older
   Terraform), `--lock-timeout`. Each one is a one-line lookup in the
   generated allowlist.

## Maintenance

New CLI minors append to the dataset the same way `pnpm
update-function-matrix` does for functions: one `providers schema -json` run
per new release against the pinned fixture (`scripts/sweep.sh` is idempotent —
existing digests are skipped). The documented overlay in
`scripts/build-matrix.py` only needs touching when a *new* protocol capability
ships, and `build-matrix.py` fails loudly if observation ever contradicts the
overlay (e.g. OpenTofu ships list resources — the `!!` sanity check fires and
the matrix must be re-verified before regeneration).

The CLI surface dataset is maintained the same way: `scripts/cli-sweep.sh`
skips versions that already have their `data/cli-surface-*.json`,
`data/cli-source-check-*.json` and `data/cli-probe-*.json`, so a new patch
or minor adds one help dump, one source check and one probe per product;
re-run `build-cli-matrix.py` (it prints `!!` for any probe/source
disagreement) and `build-cli-report.py`, and review any `UNPARSED` lines in
the sweep log.
