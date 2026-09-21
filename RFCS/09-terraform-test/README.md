# terraform-test

Dataset, research notes and proposal for extending the CDKTN testing library
with TypeScript-authored `terraform test` / `tofu test` suites ("synth and
test", next to today's "synth and plan" Jest/Vitest matchers), a `cdktn test`
CLI command, and the custom-condition ("validator") fixes those tests depend
on — sibling of `04-provider-feature-availability`, but sweeping
`<binary> test -json` instead of `providers schema -json`.

| File | Purpose |
| --- | --- |
| `PROPOSAL.md` | Design: code-only test constructs, synthesizer coordination, `targetVersions` gating of engine-exclusive features, prerequisites, phases 1-3, OpenTofu follow-up, long-term `@cdktn/integ` goal |
| `MATRIX.md` | Generated feature × product table (first supporting version, regressions, failure messages) |
| `test-features-matrix.json` | Machine-readable form of the same matrix (source for `testFeatureConstraints`) |
| `data/probes-*.json` | Committed per-CLI-version probe results |
| `fixture/module/main.tf.json` | `cdk.tf.json`-style JSON root module (`random` provider; variable validation, output precondition, check block) |
| `fixture/probes/<nn>-<feature>/` | One test-framework feature per probe: `tests/` (test files), optional `root/` (extra module files), `module/` (replacement root module), `flags`, `expect-file`, `expect-status` |
| `research/terratest.md` | Terratest capability audit, the `tcons/base/integ` real-world suite, and the translation table behind the long-term goal |

## Rebuild

```bash
scripts/sweep.sh                      # downloads CLI binaries, runs every probe (idempotent; SWEEP_PARALLELISM=4)
scripts/sweep.sh opentofu 1.13.0      # single-version mode
python3 scripts/build-matrix.py      # -> test-features-matrix.json + MATRIX.md
```

No credentials and no cloud resources: the only provider is `hashicorp/random`
and probe 22 uses the built-in `terraform_remote_state`. Each binary gets a
private plugin cache because `TF_PLUGIN_CACHE_DIR` is not concurrency-safe.
Terraform 1.6.0 can no longer install providers ("openpgp: key expired"), so
the 1.6 column uses 1.6.6.

Reading the matrix: only probes that test mocking itself (06-10, 16, 17, 22)
use `mock_provider` / `override_*`; every other probe applies the real
`random` provider, so its floor is the feature's own and not the mocking
floor (Terraform 1.7 / OpenTofu 1.8). `SWEEP_BIN_CACHE=<dir>` keeps the
downloaded binaries for re-sweeps after a probe change.

Adding a feature = adding a directory under `fixture/probes/` plus a label in
`scripts/build-matrix.py`, then deleting `data/` digests (or sweeping only the
new versions) and rebuilding.
