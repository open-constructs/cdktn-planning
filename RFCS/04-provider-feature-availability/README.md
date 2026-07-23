# provider-feature-availability

Dataset, comparison report and proposal for supporting the newer provider
plugin-protocol features (provider-defined functions, ephemeral resources,
write-only attributes, resource identity, list resources, actions, state
stores) in CDKTN — sibling of
`tools/generate-function-bindings/function-availability`, but sweeping
`providers schema -json` instead of `metadata functions -json`.

| File | Purpose |
| --- | --- |
| `PROPOSAL.md` | Design: schema parsing, codegen, and synth-time validation against `targetVersions` |
| `features-matrix.json` | Merged matrix: sweep observations + source-verified CLI serializer history |
| `report.html` | Self-contained interactive report (open in a browser) |
| `data/schema-digest-*.json` | Committed per-CLI-version digests of `providers schema -json` output (`aws-` prefix = aws fixture) |
| `data/raw/` | Full schema dumps (gitignored, rebuildable; aws dumps >100 MB are never retained) |
| `fixture/main.tf.json` | Pinned small providers exercising each feature (all CLI versions) |
| `fixture/aws.tf.json` | `hashicorp/aws` 6.14.1 — sole fixture for identity / list resources / cloud actions (CLI ≥ 1.12 only) |

## Rebuild

```bash
scripts/sweep.sh           # downloads CLI binaries, inits fixture, digests schemas (idempotent)
python3 scripts/build-matrix.py
python3 scripts/build-report.py
```

The sweep covers every minor-boundary release (first stable patch of each
minor) of Terraform ≥ 1.5.7 and OpenTofu ≥ 1.6.0 plus the overall latest patch
of each product — `providers schema -json` keys are fixed struct fields per
CLI minor, so patches cannot change emission. One substitution: the Terraform
1.6 column uses **1.6.6**, because 1.6.0 can no longer install any provider
(`openpgp: key expired`, fixed in later 1.6.x patches). Single versions can be
(re)swept with `scripts/sweep.sh <product> <version>`; `SWEEP_PARALLELISM`
defaults to 1 because a shared `TF_PLUGIN_CACHE_DIR` is not safe for
concurrent `init` (parallel first runs corrupt the cache).

## Prebuilt-provider collision sweep

`cdk-terrain` PR #296 makes `provider-generator` throw instead of silently
overwriting when a real provider schema would produce:

- two provider-defined functions that sanitize to the same generated method
  name,
- a provider-defined function that sanitizes to a name
  `ProviderFunctionsEmitter` already puts on every wrapper class
  (`constructor` / `providerLocalName`),
- two parameters of the same function that sanitize to the same generated
  parameter name, or
- a provider config attribute that generates the property name `functions`,
  colliding with the generated `functions` getter used to invoke
  provider-defined functions.

`scripts/collision-sweep.js` proves (or disproves) that these hard-fails are
purely theoretical for the providers cdktn actually prebuilds, by running the
real, compiled sanitizers from `@cdktn/provider-generator`'s build output
(`buildProviderFunctionsModel`, `assertNoFunctionsGetterCollision`, and the
real `ResourceParser` that turns a provider's config schema into the exact
generated attribute names) against every provider in the
[`cdktn-repository-manager` `provider.json`](https://raw.githubusercontent.com/cdktn-io/cdktn-repository-manager/refs/heads/main/provider.json)
catalog, plus two pending prebuilt requests
([issue #27](https://github.com/cdktn-io/cdktn-repository-manager/issues/27)
grafana/grafana,
[issue #20](https://github.com/cdktn-io/cdktn-repository-manager/issues/20)
mongodb/mongodbatlas) — 31 providers total.

| File | Purpose |
| --- | --- |
| `scripts/collision-sweep.js` | Runs the real compiled sanitizers against every provider's raw schema |
| `data/collision-sweep-manifest-input.json` | Parsed `provider.json` catalog (name → source/version-constraint) plus the two pending requests |
| `data/collision-sweep-manifest.json` | Pinned output: name → exact registry/source/version/fqpn resolved during the sweep |
| `data/collision-sweep-results.json` | Per-provider verdict (`clean`/`collision`/`unfetched`), function/parameter counts, and the exact thrown error on any collision |

**Result (2026-07-19): 31/31 clean, 0 collisions, 0 unfetched.** No provider
in the prebuilt catalog (or the two pending requests) trips any of PR #296's
hard-fails today. 26 provider-defined functions / 32 parameters were
exercised across the corpus; `aws`, `azurerm`, `google`, `google-beta`,
`grafana`, `kubernetes`, `local` and `time` are the only providers in the
corpus that declare provider-defined functions at all.

### Re-running the sweep

```bash
# 1. Fetch raw `terraform providers schema -json` output per provider into
#    SCHEMA_DIR/<name>.json (one minimal `required_providers` block per
#    provider) and the resolved version into VERSIONS_DIR/<name>.lock.hcl
#    (the `.terraform.lock.hcl` written by that init). Use
#    `mise x terraform@1.15.7 -- terraform ...` (schemas need CLI >= 1.8).
#    A large provider's schema can be reused instead of refetched by dropping
#    a VERSIONS_DIR/<name>.json override of the form
#    {"registry.terraform.io/<ns>/<name>": "<version>", "note": "..."} -
#    see how `aws` is pinned in collision-sweep-manifest.json.
#
# 2. Build (or rebuild) the provider-generator whose compiled sanitizers the
#    sweep imports:
#    cd <cdk-terrain worktree> && pnpm nx build @cdktn/provider-generator
#
# 3. Run the sweep:
CDKTN_REPO=/path/to/cdk-terrain/worktree \
SCHEMA_DIR=/path/to/raw/schemas \
VERSIONS_DIR=/path/to/raw/schemas \
MANIFEST_INPUT=RFCS/04-provider-feature-availability/data/collision-sweep-manifest-input.json \
OUT_DIR=RFCS/04-provider-feature-availability/data \
  node RFCS/04-provider-feature-availability/scripts/collision-sweep.js
```

Raw schema dumps are not committed (they're large and fully rebuildable);
only the manifest and results digests are.
