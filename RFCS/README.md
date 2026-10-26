# CDKTN RFCs

Data backed Proposals for improvements to the CDK Terrain framework.

## CDKTN Rename

[`01-cdktn-rename/`](01-cdktn-rename/)

- [x] Proposal implemented and released.

## CI Optimizations for hcl2cdk

[`02-ci-optimizations/`](02-ci-optimizations/)

- [x] Proposal implemented and released.

## Function Availability

[`03-function-availability/`](03-function-availability/) — the Function availability matrix was built from data sweeps on all binary releases
(Terraform 1.5.7 → 1.17.0, OpenTofu 1.6.0 → 1.13.2; re-run steps in its README).

- [x] Report made available at [cdktn.io/function-matrix](https://cdktn.io/function-matrix.html).
- [x] Proposal implemented in [cdk-terrain#268](https://github.com/open-constructs/cdk-terrain/pull/268).


## Provider Feature Availability

[`04-provider-feature-availability/`](04-provider-feature-availability/) — the Provider Feature availability matrix was built from data sweeps on
every minor-boundary binary release; the same directory carries the CLI
command/flag surface sweep (`cli-matrix.json`, `cli-report.html`) comparing
Terraform and OpenTofu commands and flags across versions — both what help
lists and what each version's flag parser accepts (read from source,
verified by probing the binaries).

- [x] Report made available at [cdktn.io/provider-feature-matrix](https://cdktn.io/provider-feature-matrix.html).
- [ ] Proposal implemention pending
- [ ] CLI surface: input for cdk-terrain#513 (reject unknown options) — see `PROPOSAL.md` "CLI command/flag surface"

## Mixins

Adoption audit for the `constructs` 10.6 Mixins primitive (`IMixin` +
`Construct.with(...mixins)`) inherited via `cdktn@0.23.4`, and the correct
mixin-vs-aspect model. Code/architecture audit (no binary sweep).

- [ ] Proposal ([`05-mixins/PROPOSAL.md`](05-mixins/PROPOSAL.md)) — proposed; ship `PreventDestroy` core mixin + Mixins concept doc pending
