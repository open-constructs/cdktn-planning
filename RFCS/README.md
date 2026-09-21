# CDKTN RFCs

Data backed Proposals for improvements to the CDK Terrain framework.

## CDKTN Rename

- [x] Proposal implemented and released.

## CI Optimizations for hcl2cdk

- [x] Proposal implemented and released.

## Function Availability

The Function availability matrix was built from data sweeps on all binary releases.

- [x] Report made available at [cdktn.io/function-matrix](https://cdktn.io/function-matrix.html).
- [x] Proposal implemented in [cdk-terrain#268](https://github.com/open-constructs/cdk-terrain/pull/268).


## Provider Feature Availability

The Provider Feature availability matrix was built from data sweeps on all binary releases.

- [x] Report made available at [cdktn.io/provider-feature-matrix](https://cdktn.io/provider-feature-matrix.html).
- [ ] Proposal implemention pending

## Mixins

Adoption audit for the `constructs` 10.6 Mixins primitive (`IMixin` +
`Construct.with(...mixins)`) inherited via `cdktn@0.23.4`, and the correct
mixin-vs-aspect model. Code/architecture audit (no binary sweep).

- [ ] Proposal ([`05-mixins/PROPOSAL.md`](05-mixins/PROPOSAL.md)) — proposed; ship `PreventDestroy` core mixin + Mixins concept doc pending

## Terraform Test ("synth and test")

TypeScript-authored `terraform test` / `tofu test` suites next to the Jest/Vitest
matchers, a `cdktn test` command, and the custom-condition fixes they depend on.
The test-framework feature matrix was built from probe sweeps on all binary
releases of both products.

- [ ] Proposal ([`09-terraform-test/PROPOSAL.md`](09-terraform-test/PROPOSAL.md)) — proposed; matrix in [`09-terraform-test/MATRIX.md`](09-terraform-test/MATRIX.md)
