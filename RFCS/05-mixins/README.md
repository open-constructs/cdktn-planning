# mixins

Audit and adoption proposal for the `constructs` 10.6 **Mixins** primitive
(`IMixin` + `Construct.with(...mixins)`) that CDKTN inherited transitively via
the `constructs@^10.6.0` peer bump — shipping since the **v0.23.0** release
([cdk-terrain#164](https://github.com/open-constructs/cdk-terrain/pull/164), via
the JSII dependency upgrade [cdk-terrain#20](https://github.com/open-constructs/cdk-terrain/pull/20)),
though only surfaced in the docs later while refreshing the API reference
([cdk-terrain-docs#22](https://github.com/open-constructs/cdk-terrain-docs/pull/22)).

Unlike RFCs 03/04, this is a **code/architecture audit**, not a binary sweep —
there is no `data/` dataset or `report.html`. The evidence is source read
directly in three places (CDKTN core, the `tcons/base` construct library, and
the published `cdktn@0.23.4` JSII assembly).

| File | Purpose |
| --- | --- |
| `PROPOSAL.md` | Findings (what constructs 10.6 ships, what we inherited, the constructs↔aws-cdk-lib split, and an audit of every existing Aspect in CDKTN core and `tcons/base`), the mixin-vs-aspect decision rule, sample mixins, and an adoption plan |

## Key conclusions

- CDKTN ships `IMixin` + `.with()` today with **zero code of its own** — an
  undocumented public API worth adopting intentionally.
- The `Mixin` base class, `Mixins.of()` aggregator and `ConstructSelector` are
  **aws-cdk-lib-only** (not in constructs), so scope-wide `.apply()` would
  require a CDKTN port.
- The AWS "Mixins configure / Aspects validate" framing is revisionist: **every**
  real Aspect in CDKTN core and `tcons/base` mutates, and AWS's own `Tags` is a
  mutating aspect. The correct axis is **scope + timing**, not mutate-vs-validate.
- Proposed first-party mixin: **`PreventDestroy`** (provider-agnostic, core).
