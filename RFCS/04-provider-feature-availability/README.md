# 04-provider-feature-availability

Dataset, comparison report and proposal for supporting the newer provider
plugin-protocol features (provider-defined functions, ephemeral resources,
write-only attributes, resource identity, list resources, actions, state
stores) in CDKTN — sibling of [`../03-function-availability`](../03-function-availability/)
(whose matrix cdk-terrain copies to
`tools/generate-function-bindings/function-availability/`), but sweeping
`providers schema -json` instead of `metadata functions -json`. It also
carries the [CLI command/flag surface sweep](#cli-commandflag-surface-sweep)
(`<binary> [cmd [sub]] -help`, the Go flag parsers and a binary probe across
versions).

| File | Purpose |
| --- | --- |
| `PROPOSAL.md` | Design: schema parsing, codegen, and synth-time validation against `targetVersions` |
| `features-matrix.json` | Merged matrix: sweep observations + source-verified CLI serializer history |
| `report.html` | Self-contained interactive report (open in a browser) |
| `data/schema-digest-*.json` | Committed per-CLI-version digests of `providers schema -json` output (`aws-` prefix = aws fixture) |
| `data/raw/` | Full schema dumps (gitignored, rebuildable; aws dumps >100 MB are never retained) |
| `fixture/main.tf.json` | Pinned small providers exercising each feature (all CLI versions) |
| `fixture/aws.tf.json` | `hashicorp/aws` 6.14.1 — sole fixture for identity / list resources / cloud actions (CLI ≥ 1.12 only) |
| `cli-matrix.json` | CLI surface matrix: per command × flag a `listed` (help) and an `accepted` (parser) span plus a per-version status string, product-only items, an allowlist preview, and the flags cdktn emits |
| `cli-report.html` | Self-contained interactive CLI surface report (linked from `report.html`) |
| `data/cli-surface-<product>-<version>.json` | Committed per-version parse of the binary's `-help` pages |
| `data/cli-source-check-<product>-<version>.json` | Committed per-version flag-parser registrations (Go source) of every command, compared with help |
| `data/cli-probe-<product>-<version>.json` | Committed per-version binary probe: accepted / rejected per command × candidate flag |

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

## CLI command/flag surface sweep

Enumerates every command, subcommand and flag that `terraform` / `tofu`
document in their `-help` output (**listed**) and that their flag parsers
register (**accepted**), per version, to answer "which flags can a caller
pass to which binary at which version" (input for the cdk-terrain
unknown-option work in PR #513 — see `PROPOSAL.md`, "CLI command/flag
surface"). Help is not a reliable proxy for acceptance in either direction,
so every "since" / product-only claim and the allowlist preview use the
accepted data; a binary probe checks it.

### How to re-run

```bash
RFCS/04-provider-feature-availability/scripts/cli-sweep.sh          # installs CLIs via mise, parses -help, source check, probe (idempotent)
python3 -I RFCS/04-provider-feature-availability/scripts/build-cli-matrix.py
python3 -I RFCS/04-provider-feature-availability/scripts/build-cli-report.py
```

- **Version selection:** the first *and* last stable patch of every minor
  line, Terraform ≥ 1.5.7 and OpenTofu ≥ 1.6.0, from the same indexes as
  `sweep.sh` (`releases.hashicorp.com/terraform/index.json`,
  `get.opentofu.org/tofu/api.json`). New commands/flags ship in minors, but
  both products have changed CLI surface in patches (e.g. Terraform
  `providers lock -test-directory` arrived in a 1.14.x patch: listed at
  1.14.9, absent at 1.14.0), so
  the last patch of each line catches patch-level additions and removals at
  ~2 binaries per minor (24 Terraform + 16 OpenTofu today) instead of every
  release. A new patch therefore replaces nothing — it adds a column and the
  previous "last patch" stays. Terraform 1.6.0 is swept as is: its
  expired-key problem only breaks provider installs, not `-help`.
- **Binaries:** `mise install <product>@<v>`, then the binary path is
  resolved once with `mise exec <product>@<v> -- sh -c 'command -v <exe>'`
  and run directly for the ~50 `-help` calls per version (cwd is an empty dir
  under `$TMPDIR/cli-surface-sweep`, so neither the repo `mise.toml` nor any
  configuration applies; `CHECKPOINT_DISABLE=1`, every `TF_*` / `TOFU_*`
  variable dropped, `HOME` / `TF_CLI_CONFIG_FILE` / `TF_DATA_DIR` in a
  throwaway dir, and that `HOME` rewritten to `~` in the captured help, so
  the dumps do not depend on who runs the sweep).
  `MISE_DATA_DIR` defaults to `$TMPDIR/cli-surface-sweep/mise`; zip download
  fallback logs `MISE-FALLBACK`. `SWEEP_PARALLELISM` defaults to 4 (no shared
  plugin cache is involved). A full run from a warm mise cache takes ~25 s.
- **Walk:** `<bin> -help` → every listed command ("Main commands" and "All
  other commands") → `<bin> <cmd> -help` → every "Subcommands:" entry,
  recursively (depth ≤ 3: `state *`, `workspace *`, `providers *`,
  `metadata *`). `stacks` (Terraform ≥ 1.13) is recorded but not walked: its
  help downloads and runs the separately versioned HCP Terraform stacks
  plugin.
- **Parser (`scripts/cli_help.py`):** explicit and line-oriented — column-0
  lines are section headings; indented `-flag[=X| X]  description` lines at
  the section's flag indent are flags (`switch` / `bool` when shown as
  `=true|false` / `value`), comma-separated flag tokens are aliases, deeper
  lines are continuations, `deprecated` / `legacy` / `will be removed` in
  the description are deprecation markers, and flags that appear only in the
  usage line (`providers schema -json`) are recorded with section `Usage`.
  A bracketed all-caps tag after the name (`-state-provider-lock-file
  [EXPERIMENTAL]`) is a description prefix, not a placeholder. Terraform's
  prose line "-state, state-out, and -backup are legacy options …"
  (`import`, `refresh`, `taint`, `untaint`, `state mv`,
  `state replace-provider`) declares those three flags (`"from":
  "legacy-prose"`; `via: legacy-prose` in the matrix). Help-derived value
  kinds are overridden by the source registration kind in the matrix
  (`init -plugin-dir` shows no placeholder but takes a path).
  Two help-delegation patterns are modelled: apply/destroy pages that say
  "see `terraform plan -help`" inherit the plan page's "Plan Customization
  Options", and Terraform's destroy page ("alias for: terraform apply
  -destroy") inherits apply's flags (`via` = `plan-reference` /
  `apply-reference` in the matrix). Every other unmatched line is logged as
  `UNPARSED <product> <version> '<cmd>': …` and kept in the JSON's
  `unparsed` map; the remaining ones are prose ("see terraform plan -help",
  OpenTofu `show`'s "-state is the default").
- **Source check (`scripts/cli-source-check.py`), every swept version:**
  reads `commands.go` (Terraform) / `cmd/tofu/commands.go` (OpenTofu) for
  all registered and experimental-only commands, `HiddenCommands` and each
  entry's `&command.<Type>{…}` literal (`Destroy: true`, `AliasCommand`
  targets), then walks every command from `(*<Type>).Run` through
  `arguments.Parse*/Bind*`, the package flag-set helpers
  (`extendedFlagSet`, `defaultFlagSet`, `ParseView`, OpenTofu `Bind*`/
  `bind*`, 1.11–1.12 `ViewOptions.AddFlags` / `Backend.Add*Flag`), `Meta`
  flag sets and `setup*` helpers, `Meta.process` (`-no-color` strip) and
  OpenTofu ≥ 1.13 `RunCommand(<X>Commander())`, collecting every
  `<fs>.<Kind>Var(…, "<name>", …)`, `case "-x":` and
  `-deprecation=module:` prefix match. Guards are evaluated where possible
  (`if state != nil` against the caller's arguments, OpenTofu bit masks,
  literal booleans, command struct fields); `ApplyCommand`'s apply/destroy
  dispatch is resolved by name. Each flag records `takes_value` from its
  registration kind. Files come from one `git cat-file --batch` per tag;
  `cli-sweep.sh` first prefetches all needed blobs in one `git fetch
  --filter=blob:none --stdin` (a blobless clone otherwise fetches blob by
  blob). Needs the reference clones (`REF_TERRAFORM`, `REF_OPENTOFU`,
  default `~/cdktn/ref-terraform` / `~/cdktn/ref-opentofu`); skipped when
  absent.
- **Binary probe (`scripts/cli-probe.py`), every swept version:** for every
  flag-parsing command, runs each candidate flag — every flag any help page
  lists or any source check registers for that command, in either product
  at any version — as `<bin> <cmd> -flag[=value] <dummy positionals>` in a
  fresh empty directory (throwaway `HOME`, empty CLI config, stdin
  `/dev/null`), next to a baseline with `-zzz-probe-bogus`. Output equal to
  the baseline with the bogus name replaced by the flag name means
  "rejected"; anything else means the parser got past the flag. `login`,
  `logout`, `push`, `stacks`, `rpcapi` and parent commands are skipped.
  `build-cli-matrix.py` compares every verdict with the source check and
  prints `!!` on disagreement (`summary.probe`). ~4 s per version.
- **Caching / SKIP:** a version is skipped when its
  `data/cli-surface-<product>-<version>.json` exists; the source check and
  the probe likewise skip existing outputs. Delete files or use
  single-version mode (`scripts/cli-sweep.sh <product> <version> [...]`) to
  re-sweep; after a parser change delete all outputs of that stage.
- **Committed:** `data/cli-surface-*.json`, `data/cli-source-check-*.json`,
  `data/cli-probe-*.json`, `cli-matrix.json`, `cli-report.html`.
  `build-cli-matrix.py` prints the product-only lists (with accepted-since
  and listed-since) used in `PROPOSAL.md`; `CDKTN_EMITTED` in it lists the
  flags cdk-terrain passes to the binary (update it when cli-core changes).
- **Limits:** "accepted" means the flag parser takes it; a few accepted
  flags are refused later at runtime in release builds (Terraform
  `-allow-deferral`, `test -junit-xml` 1.8–1.11). Version sampling is per
  minor (first + last patch), so an item first seen at `X.Y.0` shipped in
  `(previous swept version, X.Y.0]`.

**Result (Terraform 1.5.7–1.17.0, OpenTofu 1.6.0–1.13.2):** 54 commands and
724 command × flag pairs accepted or listed (570 listed in help at some
version). Product-only: 5 Terraform-only commands (`query`, `modules`,
`stacks`, `state identities`, hidden `rpcapi`) and 3 OpenTofu-only hidden
aliases (`state ls` / `move` / `remove`); by accepted-or-listed, 40
Terraform-only and 77 OpenTofu-only command × flag pairs once OpenTofu's
"view" flags (`-concise`, `-consolidate-*`, `-deprecation`, `-json-into`,
`-lint`, `-show-sensitive`, …, listed on every command since 1.13) are set
aside (48 / 373 including them). At the newest versions 102 Terraform and
136 OpenTofu command × flag pairs are accepted but not in help; three are
listed but rejected (`state replace-provider -state-out` in both products,
OpenTofu 1.13 `destroy -lint`). 24,175 probe runs agree with the source
check without exception. Every flag cdktn emits is accepted by every swept
version of both products.

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
