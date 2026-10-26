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

## How to re-run

Requirements: `bash`, `python3`, `curl`, [`mise`](https://mise.jdx.dev),
network access to the Terraform and OpenTofu registries (`unzip` only for
the fallback path).

```bash
RFCS/04-provider-feature-availability/scripts/sweep.sh   # installs CLIs, inits fixtures, digests schemas (idempotent)
python3 RFCS/04-provider-feature-availability/scripts/build-matrix.py
python3 RFCS/04-provider-feature-availability/scripts/build-report.py
```

- **Version selection:** from the official indexes
  (`https://releases.hashicorp.com/terraform/index.json`,
  `https://get.opentofu.org/tofu/api.json`), every minor-boundary release
  (first stable patch of each minor, normally `X.Y.0`) of Terraform ≥ 1.5.7
  and OpenTofu ≥ 1.6.0, plus the overall latest stable patch of each product.
  `providers schema -json` keys are fixed struct fields per CLI minor, so
  patches cannot change emission. A new minor line therefore adds its `.0`
  column, and a new latest patch adds a column; earlier "latest" columns
  (e.g. Terraform 1.15.6) stay as committed digests. One substitution: the
  Terraform 1.6 column uses **1.6.6**, because 1.6.0 can no longer install any
  provider (`openpgp: key expired`, fixed in later 1.6.x patches) — the
  full-mode selection maps 1.6.0 → 1.6.6 automatically.
- **Two passes:** the `core` fixture (`fixture/main.tf.json`, small providers)
  at every selected version, then the `aws` fixture (`fixture/aws.tf.json`,
  `hashicorp/aws` 6.14.1) only at selected versions ≥ 1.12.0. The core fixture
  pins exact versions except `vault ~> 5.0`; the resolved provider versions
  are recorded per digest (`provider_selections`).
- **Binaries:** each version is installed with
  `mise install terraform@<v>` / `mise install opentofu@<v>` and every command
  (`init`, `providers schema -json`, `version -json`) runs as
  `mise exec terraform@<v> -- terraform ...` (or `opentofu@<v> -- tofu ...`)
  from a per-version work dir under `$TMPDIR/provider-feature-sweep`, outside
  the repo, so the repo `mise.toml` does not apply. `MISE_DATA_DIR` defaults
  to `$TMPDIR/provider-feature-sweep/mise` (set it to reuse your normal mise
  cache). If mise cannot install a version, the script logs `MISE-FALLBACK`
  and downloads the release zip for that version only. Providers come from a
  shared `TF_PLUGIN_CACHE_DIR` (`$TMPDIR/provider-feature-sweep/plugin-cache`).
- **Caching / SKIP:** a version is skipped when its digest
  `data/schema-digest-[aws-]<product>-<version>.json` already exists, so a
  re-run only sweeps new columns. Delete a digest (or use single-version mode)
  to re-sweep it.
- **Single versions:** `[FIXTURE=aws] scripts/sweep.sh <product> <version> [...]`.
- **Parallelism:** `SWEEP_PARALLELISM` defaults to 1 because a shared
  `TF_PLUGIN_CACHE_DIR` is not safe for concurrent `init` (parallel first runs
  corrupt the cache).
- **Committed:** `data/schema-digest-*.json`, `features-matrix.json`,
  `report.html`. Raw dumps ≤ `RAW_KEEP_LIMIT_BYTES` (8 MB) go to `data/raw/`
  (gitignored); aws dumps are never kept. `build-matrix.py` uses only the
  digests; its `DOCUMENTED` overlay (source-verified emission boundaries) is
  hand-maintained and flags any observation that contradicts it.

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

The verdict depends on the provider catalog/versions and the cdk-terrain
sanitizers, not on the CLI release: any Terraform ≥ 1.8 only serializes the
provider's schema, and `internal/command/jsonprovider` is unchanged from
1.15 through 1.17.0. It is therefore not re-run when the CLI sweeps above
add columns (it was not re-run in the October 2026 refresh).

Raw schema dumps are not committed (they're large and fully rebuildable);
only the manifest and results digests are.
