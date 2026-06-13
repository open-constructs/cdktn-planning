# Proposal: Validate Terraform function usage against the selected CLI product/version

Status: **implemented** (usage registry, `ValidateFunctionVersionSupport`,
`validateFunctionVersions` feature flag, generated availability map, and
`pnpm update-function-matrix` delta updater) · Generated from a sweep of
`<binary> metadata functions -json` across every stable Terraform release
(1.5.7 → latest) and every stable OpenTofu release (1.6.0 → latest). Raw data
(gitignored, rebuildable via `scripts/sweep.sh`) and the interactive report
live next to this file.

## Problem

`Fn.*` bindings in `packages/cdktn/src/functions/terraform-functions.generated.ts`
are generated from a **single** Terraform version's `metadata functions -json`
output (currently a pre-1.8 snapshot with 115 functions). Users, however, run
synth output against whatever `terraform`/`tofu` binary they have:

- A user on Terraform 1.7 can call `Fn.issensitive(...)` (added in TF 1.8) and
  only finds out at `terraform plan` time, with an HCL-level error far removed
  from their CDK code.
- Terraform and OpenTofu have **diverged**: OpenTofu added `base64gunzip`,
  `cidrcontains`, `urldecode` (1.7) which Terraform doesn't have; Terraform
  added `convert` (1.15) which OpenTofu doesn't have. `templatestring`,
  `issensitive` and `ephemeralasnull` exist in both but were introduced at
  different versions (TF 1.9/1.8/1.10 vs OpenTofu 1.7/1.7/1.11).
- The same divergence applies to features the bindings will grow when
  `functions.json` is regenerated from a newer binary.

`ValidateTerraformFeatureVersion` (added in #237,
`packages/cdktn/src/validations/validate-terraform-feature-version.ts`) already
solves the general shape of this problem — product detection via
`parseTerraformCliVersion` + per-product semver constraint matrix — but is
currently only wired to explicit features, not to function usage.

## Data: function availability matrix

The sweep results (see `functions-matrix.json` / `report.html` in this
directory) show the function surface is extremely stable; only the delta from
the baseline needs encoding:

| Function | Terraform | OpenTofu |
| --- | --- | --- |
| 115 baseline functions | ≥ 1.5.7 (all scanned) | ≥ 1.6.0 (all scanned) |
| `issensitive` | ≥ 1.8.0 | ≥ 1.7.0 |
| `templatestring` | ≥ 1.9.0 | ≥ 1.7.0 |
| `ephemeralasnull` | ≥ 1.10.0 | ≥ 1.11.0 |
| `convert` | ≥ 1.15.0 | — |
| `base64gunzip` | — | ≥ 1.7.0 |
| `cidrcontains` | — | ≥ 1.7.0 |
| `urldecode` | — | ≥ 1.7.0 |

(`core::` namespaced aliases — TF ≥ 1.8 / OpenTofu ≥ 1.7 mirror every builtin —
are folded out; CDKTN does not generate bindings for them.)

No function has ever been removed in either product within the scanned range,
so constraints can be simple `>=x.y.z` ranges rather than full version sets.

## Design

### 1. Generate an availability map alongside the bindings

Extend `tools/generate-function-bindings` with a sweep script (productionized
version of the temp-dir sweep used to produce this data) that emits:

```ts
// packages/cdktn/src/functions/function-availability.generated.ts
export const functionVersionConstraints: Record<
  string,
  { terraform?: string; opentofu?: string }
> = {
  issensitive: { terraform: ">=1.8.0", opentofu: ">=1.7.0" },
  templatestring: { terraform: ">=1.9.0", opentofu: ">=1.7.0" },
  ephemeralasnull: { terraform: ">=1.10.0", opentofu: ">=1.11.0" },
  convert: { terraform: ">=1.15.0" },
  base64gunzip: { opentofu: ">=1.7.0" },
  cidrcontains: { opentofu: ">=1.7.0" },
  urldecode: { opentofu: ">=1.7.0" },
};
```

Key property: **only non-baseline functions are listed**. A function absent
from the map is treated as universally available — no validation runs for it.
This keeps the generated file tiny and means zero behavior change for the 115
baseline functions. A missing product key means "not supported by this product
at any version" (mirrors `TerraformFeatureVersionConstraints` semantics, which
already produces the right error message for that case).

The sweep does **not** need to run 120 binaries in CI on every regen: the
committed `functions-matrix.json` is the source of truth and only needs
appending when a new minor of either product ships (a single
`metadata functions -json` run against the new release).

### 2. Record `Fn.*` usage at call time

Every generated binding funnels through `terraformFunction(name, validators)`
in `packages/cdktn/src/functions/helpers.ts`, which calls `call(name, args)`
(`tfExpression.ts:386`). Add a module-level usage registry there:

```ts
// functions/usage-registry.ts
const usedFunctions = new Set<string>();
export function recordFunctionUsage(name: string) { usedFunctions.add(name); }
export function getUsedFunctions(): ReadonlySet<string> { return usedFunctions; }
```

`terraformFunction()` records the name before returning the expression. Since
user code constructs all `Fn.*` expressions before `app.synth()` runs
validations, the registry is complete by validation time.

Trade-offs (acceptable, documented):

- The registry is process-global, not stack-scoped — an `Fn` result is a plain
  token that can be shared across stacks, so attribution is impossible anyway.
  The validation therefore runs once at App level (or on each stack with
  identical results, deduplicated by message).
- Raw escape hatches (`TerraformOverride`, string-built expressions) are not
  caught. Out of scope; same limitation as type checking.

### 3. Validate with a `ValidateTerraformFeatureVersion` derivative

Add `ValidateFunctionVersionSupport` to `packages/cdktn/src/validations/`:

```ts
export class ValidateFunctionVersionSupport implements IValidation {
  public validate(): string[] {
    const used = getUsedFunctions();
    const relevant = [...used].filter((f) => f in functionVersionConstraints);
    if (relevant.length === 0) return []; // no CLI invocation at all

    const cliVersion = detectCliVersion(); // shared with ValidateTerraformFeatureVersion
    return relevant.flatMap((fn) =>
      checkFeature(`Terraform function "${fn}"`, functionVersionConstraints[fn], cliVersion),
    );
  }
}
```

Refactor `ValidateTerraformFeatureVersion.validate()` to extract two pure
helpers it already implicitly contains, so both classes share one code path
and one set of error messages (the snapshots in
`packages/cdktn/test/validations.test.ts` stay unchanged):

- `detectCliVersion(versionCommand, binary)` → `TerraformCliVersion | error`
  (runs the CLI **once per synth**, memoized — today each
  `ValidateTerraformFeatureVersion` instance shells out independently)
- `checkFeature(featureName, constraints, cliVersion, hint?)` → `string[]`
  (the constraint-matrix logic of `validate-terraform-feature-version.ts:82-97`)

Error messages come out in the established format, e.g.:

```
Terraform function "templatestring" requires terraform >=1.9.0, but terraform version 1.7.5 was found.
Terraform function "cidrcontains" is not supported by terraform. It is available in opentofu >=1.7.0.
```

(The second message uses the existing "not supported by <product>" path with
the generated `hint` filled from the other product's constraint.)

### 4. Wiring and rollout

- `TerraformStack` (or `App.synth`) adds `ValidateFunctionVersionSupport`
  behind a **feature flag** in `packages/cdktn/src/features.ts`
  (`VALIDATE_FUNCTION_VERSIONS = "validateFunctionVersions"`, added to
  `FUTURE_FLAGS` so `cdktn init` enables it for new projects) — consistent
  with the existing flag rollout model and avoids surprising existing
  projects whose synth never invoked the CLI before (`skipValidation: true`
  remains the global escape hatch).
- The version command honors `TERRAFORM_BINARY_NAME` via the existing
  `terraformBinaryName` util, so OpenTofu users are detected exactly as in
  `ValidateTerraformFeatureVersion`.
- If the CLI is not installed, follow the existing behavior of
  `ValidateTerraformFeatureVersion` (it returns an error today). Since synth
  may legitimately run without a CLI (e.g. CI that only synthesizes),
  consider downgrading "binary not found" to an `Annotations.warn` for this
  validation only — to be decided in review.

### 5. Testing

Mirror `packages/cdktn/test/validations.test.ts` patterns — stub the version
command with `echo`:

```ts
new ValidateFunctionVersionSupport(`echo "Terraform v1.7.5\non darwin_arm64"`)
```

Cases: baseline-only usage (no CLI shell-out at all — assert via spy),
late-introduced function on old/new Terraform, product-exclusive function on
the wrong product (hint mentions the other product), OpenTofu detection,
unknown CLI output, registry reset between tests (expose
`resetFunctionUsageRegistry()` under `Testing`).

## Why not synthesized-JSON scanning?

An alternative is regex-scanning `cdk.tf.json` for `${fn(...)}` after synth.
It would also catch escape hatches, but: validations run before stacks are
rendered (would need a second synth pass or a post-synth hook), function names
inside string literals create false positives, and per-stack attribution still
fails for cross-stack tokens. Call-time recording is one line in an existing
chokepoint and keeps the validation a plain `IValidation`. YAGNI says start
there; JSON scanning can be added later as a `cdktn` CLI lint if escape-hatch
coverage proves necessary.

## Effort

- Generator: sweep script + availability emitter — the scripts in this
  directory are the prototype; productionizing is mostly file moves.
- Core: usage registry (≈10 lines), shared helpers refactor (pure extraction),
  new validation class (≈40 lines), feature flag, tests.
- Fits the "< 30 min review" PR budget split as: (1) refactor helpers out of
  `ValidateTerraformFeatureVersion` (no behavior change), (2) generated map +
  registry + validation + flag.
