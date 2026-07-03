# Proposal: Adopt `constructs` 10.6 Mixins for imperative per-construct composition

Status: **proposed** · This RFC is a code/architecture audit rather than a data
sweep — its "dataset" is the two source audits summarised under
[Findings](#findings) (CDKTN core Aspects and the `tcons/base` construct
library) plus the published `cdktn@0.23.4` JSII assembly. No `data/` or
`report.html` sibling is needed.

## Problem

The bump of the `constructs` peer dependency to `^10.6.0` — landed in the
**v0.23.0** release ([cdk-terrain#164][pr164]) via the JSII dependency upgrade
in [cdk-terrain#20][pr20] — **silently added a `with(...mixins)` method to every
CDKTN construct**. It has therefore been shipping, undocumented, since 0.23.0.
We only *noticed* it two releases later while refreshing the generated API
reference: the refresh (cdk-terrain-docs#22) shows `with()` on all 5 languages ×
every construct page — but only because the API reference had been stale since
0.23.2; the method was **not** new in 0.23.4. It is sourced entirely from
constructs, not from any CDKTN code.

[pr164]: https://github.com/open-constructs/cdk-terrain/pull/164
[pr20]: https://github.com/open-constructs/cdk-terrain/pull/20

Two things follow:

1. **We are now shipping an undocumented, un-blessed public API.** CDKTN has a
   Mixins capability whether or not we intended one. We should adopt it
   intentionally — document it, ship at least one first-party mixin, and decide
   how far to go — rather than let it sit as accidental surface area.
2. **The AWS CDK Mixins launch reframes the relationship between Mixins and
   Aspects** in a way that, taken literally, implies our existing Aspects are
   "misused." That claim needs auditing before we repeat it in our own docs.
   The AWS blog states:

   > Mixins and Aspects are complementary. Mixins apply features immediately to
   > specific constructs, while Aspects enforce rules broadly across a scope
   > during synthesis. A common pattern is to use Mixins to configure resources
   > and Aspects to validate that the configuration is correct.
   > — [Announcing AWS CDK Mixins][blog]

This proposal records what Mixins actually are in the constructs library, what
we inherited, how our Aspects are actually used today, the correct mental model
for when to reach for each, and a concrete adoption plan.

## Findings

### F1 — What `constructs` 10.6 actually ships

Inspected the `constructs@10.6.0` `.jsii` assembly directly. The Mixins
primitive is exactly two things:

- **`constructs.IMixin`** (`src/mixin.ts:7`) — *"a reusable piece of
  functionality that can be applied to constructs to add behavior, properties,
  or modify existing functionality without inheritance."* Two abstract methods:
  - `supports(construct: IConstruct): boolean` (`src/mixin.ts:11`) — *"Determines
    whether this mixin can be applied to the given construct."*
  - `applyTo(construct: IConstruct): void` (`src/mixin.ts:16`) — *"Applies the
    mixin functionality to the target construct."*
- **`Construct.with(...mixins: IMixin[]): IConstruct`** — variadic; *"Applies one
  or more mixins to this construct. Mixins are applied in order."*

That is the **entire** primitive. There is no base class, no aggregator, no
selector, no prebuilt mixin in the constructs library.

### F2 — What CDKTN inherited (since 0.23.0)

The published `cdktn@0.23.4` `.jsii` (the current latest; the peer bump landed
in 0.23.0, see [Problem](#problem)) contains **zero** references to `mixin` or
`IMixin` (verified by string search of the full assembly). Every `with()`
method on the API-reference pages is inherited from `constructs.Construct`.
CDKTN defines **no** mixins of its own. The feature is real and callable but
undocumented and untested by us.

CDKTN core already exposes all the hooks a mixin's `applyTo` needs (verified in
the same assembly):

- `TerraformResource.isTerraformResource(x)` — static type guard, ideal for
  `supports()`.
- `TerraformElement.addOverride(path, value)` — universal, provider-agnostic
  escape hatch.
- Mutable setters on `TerraformResource`: `lifecycle`, `provider`, `dependsOn`,
  `count`, `forEach`, `provisioners`.

### F3 — The package split: what we did *not* inherit

Per [aws-cdk-rfcs#0814][rfc0814], the Mixins feature is deliberately split
across two libraries:

| Symbol | Lives in | CDKTN has it? |
| --- | --- | --- |
| `IMixin` interface | `constructs` | ✅ (via 10.6) |
| `Construct.with(...mixins)` | `constructs` | ✅ (via 10.6) |
| abstract `Mixin` base class | `aws-cdk-lib` | ❌ |
| `Mixins.of(scope)` aggregator / `MixinApplicator` | `aws-cdk-lib` | ❌ |
| `ConstructSelector` (`byId`, `cfnResource`, `resourcesOfType`, `all`) | `aws-cdk-lib` | ❌ |
| `requireAll()` / `requireAny()` | `aws-cdk-lib` | ❌ |

RFC 0814 states verbatim: *"Note that `Mixins.of()` (aka the MixinApplicator)
and `ConstructSelector` are not included in the constructs module. Instead, they
are features provided by the AWS CDK Construct library."* So the ergonomic
"apply across a scope" story (`Mixins.of(stack).apply(...)`) is **not** ours for
free — it would need a CDKTN port, and `ConstructSelector`'s CFN-typed selectors
(`cfnResource`, `resourcesOfType` keyed on CloudFormation type strings) would
need Terraform re-modeling (select by `TerraformResource` / by
`terraformResourceType`).

### F4 — Existing Aspects in CDKTN core

The Aspects framework is ported from aws-cdk v2 and lives in
`packages/cdktn/src/aspect.ts` (`IAspect` at `aspect.ts:12-17`, `Aspects` class
at `aspect.ts:23-62`, exported via `index.ts:32`). Aspects run **at the start
of synthesis** — `invokeAspects(this.stack)` in
`synthesize/synthesizer.ts:125-166`, called from `synthesizer.ts:30` *before*
`runAllValidations()` (`synthesizer.ts:46`). Traversal is depth-first
pre-order with ancestor→descendant inheritance and per-node de-duplication;
there is **no numeric priority** (unlike newer aws-cdk).

Exactly **one** aspect ships in core:

| Aspect | File | Behaviour |
| --- | --- | --- |
| `MigrateIds` | `upgrade-id-aspect.ts:170-192` (exported `index.ts:43`) | **Mutating** for resources (`node.moveFromId(...)` to preserve state across the 0.17 id change); **annotating** for modules (`Annotations.of(node).addWarning(...)` telling the user to run `terraform state mv` manually) |

Two further aspects exist only as documentation examples:
`TagsAddingAspect` (`examples/typescript/documentation/aspect-tagging.ts:19-30`,
**mutating** — sets `node.tags`) and `ValidateS3IsPrefixed`
(`examples/typescript/documentation/aspect-validation.ts:10-25`, **validating**
— `Annotations.addError`).

### F5 — Existing Aspects in the `tcons/base` construct library

Audited `/Users/vincentdesmet/tcons/base`. Five concrete aspects; **all
mutate** — none is purely validating:

| Aspect | File | Mutate/validate | What it changes |
| --- | --- | --- | --- |
| `GridTags` | `src/construct-base.ts:63` (wired `:132`) | **Mutate** | sets `node.tags` — injects `grid:EnvironmentName`, `grid:UUID`, `Name` on every taggable resource |
| `AwsTag` (`Tags.of().add`) | `src/aws/aws-tags.ts:45` (wired `:117`) | **Mutate** | adds one key/value tag, with include/exclude filtering by `terraformResourceType` |
| `TerraformDependencyAspect` | `src/private/terraform-dependables-aspect.ts:26` (wired `src/stack-base.ts:239`) | **Mutate** | resolves construct-level deps to L1 resources across arbitrary subtrees and pushes them onto each resource's `dependsOn` |
| `InstanceRequireImdsv2Aspect` | `src/aws/compute/aspects/require-imdsv2-aspect.ts:76` (wired `src/aws/compute/instance.ts:769`) | **Mutate (injects a resource)** | creates a `LaunchTemplate` with `httpTokens:"required"` and rewires the instance; warns+skips if one already exists |
| `LaunchTemplateRequireImdsv2Aspect` | `src/aws/compute/aspects/require-imdsv2-aspect.ts:128` | **Mutate** | `putMetadataOptions({..., httpTokens:"required"})` |

(`RequireImdsv2Aspect`, `require-imdsv2-aspect.ts:24`, is an abstract base whose
`warn()` helper emits annotations for the two concrete subclasses.)

### F6 — The AWS "Mixins configure / Aspects validate" split is revisionist

Measured against the [blog][blog]'s rule, **every** real aspect above is
"wrong" — they mutate. But they did not violate any contract, for three
reasons:

1. **It is a post-Mixins retcon.** Before constructs 10.6, Aspects were the
   *only* cross-cutting mechanism, for mutation *and* validation. The rule
   describes a going-forward ideal enabled by the new tool, not a contract the
   old code broke.
2. **AWS's own canonical feature contradicts it.** In aws-cdk, `Tags.of(x).add()`
   is itself a **mutating Aspect** and stays one; our `AwsTag`/`Tags.of` and
   `GridTags` mirror it exactly (F5). If mutating aspects were misuse, AWS's
   flagship example would be the first offender.
3. **The real axis is scope + timing, not mutate-vs-validate.** Mutation and
   validation are orthogonal to the choice. See [The role Mixins
   play](#the-role-mixins-play).

## The role Mixins play

Mixins and Aspects are complementary, but the correct decision rule is about
**where** the effect applies and **when**, not whether it mutates:

- **Mixin** — imperative, applied *immediately* to a *specific construct you are
  holding*, with a type-safe `supports()` gate. Reach for it when you have the
  construct instance at authoring time and want to *opt it in* explicitly.
- **Aspect** — declarative, *deferred to synthesis*, applied across a *whole
  scope* including constructs you do **not** hold (nested, created by a library,
  or added later), with tree inheritance. Reach for it when you want blanket
  coverage of a subtree — for **mutation** (tagging, dependency propagation) *or*
  **validation**.

Applying this to the audit:

| Existing usage | Keep as Aspect? | Rationale |
| --- | --- | --- |
| `GridTags`, `AwsTag`/`Tags.of` | **Aspect** | inherently scope-wide; you don't hold every taggable resource, and future/nested resources must be covered. A mixin would be a regression. |
| `TerraformDependencyAspect` | **Aspect (cannot be a mixin)** | needs the *whole tree* at synth time to resolve construct deps into L1 `dependsOn`; a mixin only sees the one construct passed to `.with()`. |
| `MigrateIds` | **Aspect** | one-time, scope-wide state migration across all resources; you don't hold each one. |
| per-instance `requireImdsv2` opt-in (`instance.ts:769`) | **Mixin candidate** | it is wired because a *specific instance you are constructing* set `props.requireImdsv2` — you hold the construct, it's an immediate, type-safe, per-construct configuration. `instance.with(new RequireImdsv2())` models it more honestly. |

IMDSv2 is the clean illustration of the genuinely-complementary pattern: a
**mixin** to *configure* `requireImdsv2` on instances you create, plus an
**aspect** to *validate* — sweep the whole app and `addError` on any instance
(including ones from third-party libraries) that still allows IMDSv1.

## Design

### 1. Officially adopt `IMixin` + `.with()` and ship a first-party core mixin

Document the inherited primitive as a supported CDKTN capability and ship one
first-party mixin so the feature has a reference implementation and a test.
`PreventDestroy` (provider-agnostic, core-only) is the natural candidate — see
[Sample mixins](#sample-mixins) §A. It only `implements IMixin` (there is no
`Mixin` base class to extend, per F3).

### 2. Ship provider-agnostic + AWS example mixins in the docs

CDKTN is provider-agnostic, so the concept page leads with a provider-neutral
example (`PreventDestroy`) and keeps AWS-specific ones (S3 versioning,
cross-resource DataRecovery) as clearly-labelled provider examples. See
[Sample mixins](#sample-mixins) §B/§C.

### 3. Decide on porting the `aws-cdk-lib` layer (`Mixins.of` / `ConstructSelector`)

Out of scope for the first cut (YAGNI). The bare per-construct `.with()` covers
the "I hold this construct" case, and Aspects already own scope-wide
application. If a scope-wide `.apply()` is later wanted, port `Mixins.of` +
`ConstructSelector` with Terraform-native selectors (by `TerraformResource`, by
`terraformResourceType`) — tracked here, not built here.

### 4. Reclassify `requireImdsv2` in `tcons/base` as a Mixin (+ optional validating Aspect)

Follow-up in the `tcons/base` repo (not cdk-terrain core): expose
`RequireImdsv2` as a mixin for the per-instance opt-in, keep a thin validating
aspect for org-wide governance. Leave `GridTags`, `AwsTag`,
`TerraformDependencyAspect` as aspects (per [the decision rule](#the-role-mixins-play)).

### 5. Docs: position Mixins next to the existing Aspects concept page

Frame it with the decision rule above — **not** the blog's "mixins mutate,
aspects validate" line. Explicitly note that tagging and dependency propagation
are legitimately *mutating* aspects, so readers don't cargo-cult the rule and
try to rewrite `Tags` as a mixin.

## Sample mixins

All samples use only `constructs.IMixin` + `Construct.with()` (F1) and CDKTN
core hooks (F2). Cross-language note: `instanceof` is not JSII-portable — prefer
static guards (`TerraformResource.isTerraformResource`, generated `X.isConstruct`)
in `supports()` for multi-language mixins.

### A. `PreventDestroy` — core, provider-agnostic (proposed first-party mixin)

```ts
import { IConstruct, IMixin } from "constructs";
import { TerraformResource } from "cdktn";

export class PreventDestroy implements IMixin {
  supports(c: IConstruct): boolean {
    return TerraformResource.isTerraformResource(c); // F2 static guard
  }
  applyTo(c: IConstruct): void {
    const r = c as TerraformResource;
    r.lifecycle = { ...r.lifecycle, preventDestroy: true }; // F2 setter; spread-undefined is safe
  }
}

new S3Bucket(stack, "Data", { bucket: "my-data" }).with(new PreventDestroy());
```

### B. `EnableVersioning` — provider-specific (direct analog of the AWS blog example)

```ts
import { S3Bucket } from "@cdktf/provider-aws/lib/s3-bucket";

export class EnableVersioning implements IMixin {
  supports(c: IConstruct): boolean {
    return c instanceof S3Bucket;
  }
  applyTo(c: IConstruct): void {
    // version-agnostic escape hatch (F2); or a typed setter where the provider exposes one
    (c as S3Bucket).addOverride("versioning", { enabled: true });
  }
}
```

### C. `DataRecovery` — cross-resource (analog of the blog's `MyDataRecovery`)

```ts
export class DataRecovery implements IMixin {
  supports(c: IConstruct): boolean {
    return c instanceof S3Bucket || c instanceof DynamodbTable;
  }
  applyTo(c: IConstruct): void {
    if (c instanceof S3Bucket) c.addOverride("versioning", { enabled: true });
    if (c instanceof DynamodbTable) c.pointInTimeRecovery = { enabled: true };
  }
}
```

### D. `RequireImdsv2` mixin + `ValidateImdsv2` aspect — the complementary pattern

Configure with a mixin (you hold the instance); validate org-wide with an
aspect (covers instances you don't hold). This replaces the aspect-only
`InstanceRequireImdsv2Aspect` opt-in path (F5).

```ts
// Mixin — per-instance opt-in (imperative, immediate)
export class RequireImdsv2 implements IMixin {
  supports(c: IConstruct): boolean { return c instanceof Instance; }
  applyTo(c: IConstruct): void { /* attach launch template with httpTokens: "required" */ }
}
new Instance(stack, "Web", { /* ... */ }).with(new RequireImdsv2());

// Aspect — scope-wide governance (declarative, deferred, VALIDATING)
export class ValidateImdsv2 implements IAspect {
  visit(node: IConstruct): void {
    if (node instanceof Instance && allowsImdsv1(node)) {
      Annotations.of(node).addError("IMDSv2 is required (httpTokens: required)");
    }
  }
}
Aspects.of(app).add(new ValidateImdsv2());
```

## Requirements

Each requirement links to the source(s) it is grounded in.

1. **R1 — Ship `IMixin` + `.with()` as documented public API.** Grounded in the
   inherited primitive: `constructs@10.6.0` `mixin.ts:7/11/16` (F1) and the fact
   that CDKTN has re-exposed it with zero code of its own since 0.23.0 (F2,
   [cdk-terrain#164][pr164]); surfaced in the docs by cdk-terrain-docs#22.
2. **R2 — Provide a first-party `PreventDestroy` core mixin + test.** Uses only
   F1/F2 hooks (`TerraformResource.isTerraformResource`, `lifecycle` setter).
3. **R3 — Author a Mixins concept doc** positioned beside the existing Aspects
   page (`packages/cdktn/src/aspect.ts`, F4), using [the decision
   rule](#the-role-mixins-play), not the [blog][blog]'s dichotomy (F6).
4. **R4 — Do NOT reclassify scope-wide aspects.** `GridTags`
   (`construct-base.ts:63`), `AwsTag` (`aws-tags.ts:45`) and
   `TerraformDependencyAspect` (`terraform-dependables-aspect.ts:26`) stay
   aspects (F5, decision rule).
5. **R5 — Reclassify the per-instance IMDSv2 opt-in as a mixin** in `tcons/base`
   (`instance.ts:769` → `RequireImdsv2` mixin), keeping a validating aspect for
   governance (F5, §D).
6. **R6 — Defer the `aws-cdk-lib` layer.** `Mixins.of` / `ConstructSelector` /
   `Mixin` base class are not in constructs ([RFC 0814][rfc0814], F3); a CDKTN
   port with Terraform-native selectors is a separate, deferred effort (Design
   §3).

## Why intentional adoption, not "just leave it inherited"

Leaving `with()` inherited-but-undocumented means we ship public surface with no
contract, no test, and no guidance — and we have been doing so since 0.23.0.
Users will find it via the API reference (cdk-terrain-docs#22) and file bugs
against behaviour we never specified. Documenting the primitive, shipping one reference mixin, and stating
the mixin-vs-aspect rule is the minimum needed to own the surface we already
expose. It also pre-empts the common mistake the [blog][blog]'s wording invites
(rewriting mutating aspects like `Tags` as mixins).

## Effort

- **Docs (largest piece):** one concept page + provider-agnostic and AWS
  examples. No codegen, no data sweep.
- **Core:** `PreventDestroy` mixin (~15 lines) + one test. Only depends on
  already-exported symbols; no new dependency (constructs 10.6 is already the
  peer).
- **`tcons/base` (separate repo, follow-up):** extract `RequireImdsv2` mixin
  from the existing aspect; thin validating aspect. No change to `GridTags` /
  `AwsTag` / dependency propagation.
- **Deferred:** `Mixins.of` / `ConstructSelector` port — not in this RFC.

Fits the "< 30 min review" PR budget as: (1) core `PreventDestroy` + test,
(2) docs concept page, (3) `tcons/base` IMDSv2 reclassification.

## Sources

Code (read directly, file:line above):
- `constructs@10.6.0` `.jsii` — `IMixin` (`src/mixin.ts:7/11/16`), `Construct.with`
- Shipped in CDKTN 0.23.0 ([cdk-terrain#164][pr164]) via the constructs `^10.6.0`
  upgrade ([cdk-terrain#20][pr20])
- `cdktn@0.23.4` `.jsii` (current latest) — no mixin refs; `TerraformResource.isTerraformResource`,
  `TerraformElement.addOverride`, `TerraformResource` setters
- CDKTN core Aspects — `packages/cdktn/src/aspect.ts:12-62`,
  `synthesize/synthesizer.ts:30,46,125-166`, `upgrade-id-aspect.ts:170-192`
- `tcons/base` Aspects — `construct-base.ts:63`, `aws-tags.ts:45`,
  `private/terraform-dependables-aspect.ts:26`, `aws/compute/aspects/require-imdsv2-aspect.ts:24/76/128`
- Surfaced by: [cdk-terrain-docs#22](https://github.com/open-constructs/cdk-terrain-docs/pull/22)

External:
- [Announcing AWS CDK Mixins — AWS DevOps Blog][blog]
- [Mixins — AWS CDK v2 Developer Guide](https://docs.aws.amazon.com/cdk/v2/guide/mixins.html)
- [Aspects — AWS CDK v2 Developer Guide](https://docs.aws.amazon.com/cdk/v2/guide/aspects.html)
- [aws-cdk-rfcs #0814: CDK Mixins][rfc0814]

[blog]: https://aws.amazon.com/blogs/devops/announcing-aws-cdk-mixins-composable-abstractions-for-aws-resources/
[rfc0814]: https://github.com/aws/aws-cdk-rfcs/blob/main/text/0814-cdk-mixins.md
