# function-availability

Dataset, comparison report and proposal for validating built-in Terraform /
OpenTofu function usage against the selected CLI product and version.
Built from `<binary> metadata functions -json` run against every stable
release of both products.

| File | Purpose |
| --- | --- |
| `PROPOSAL.md` | Design: generated availability map + synth-time validation |
| `functions-matrix.json` | Committed matrix: per function and product, `introduced` / `removed` / `gaps` / `count`, plus the full swept version list and a canonical signature |
| `report.html` | Self-contained interactive report (open in a browser) |
| `data/functions-<product>-<version>.json` | Raw `metadata functions -json` dumps (gitignored, rebuildable) |

A copy of `functions-matrix.json` lives in cdk-terrain at
`tools/generate-function-bindings/function-availability/`, where
`pnpm update-function-matrix` appends newer releases (forward-only: it skips
patch releases of older minors, e.g. OpenTofu 1.11.x backports shipped after
1.12.0) and `pnpm generate-function-availability` regenerates the bindings'
availability map. This directory is the full-sweep source of truth; copy the
refreshed matrix over after a re-run here.

## How to re-run

Requirements: `bash`, `python3`, `curl`, [`mise`](https://mise.jdx.dev)
(`unzip` only for the fallback path).

```bash
RFCS/03-function-availability/scripts/sweep.sh       # fetch metadata for new releases
python3 RFCS/03-function-availability/scripts/build-matrix.py
python3 RFCS/03-function-availability/scripts/build-report.py
```

- **Version selection:** every stable `X.Y.Z` release from the official
  indexes — `https://releases.hashicorp.com/terraform/index.json` (>= 1.5.7)
  and `https://get.opentofu.org/tofu/api.json` (all, i.e. >= 1.6.0).
  Pre-releases are ignored; backports to older minors are included.
- **Binaries:** each version is installed with
  `mise install terraform@<v>` / `mise install opentofu@<v>` and run as
  `mise exec terraform@<v> -- terraform metadata functions -json` (or
  `opentofu@<v> -- tofu ...`) from a work dir under
  `$TMPDIR/tf-func-matrix-work`, outside the repo, so the repo `mise.toml`
  does not apply. `MISE_DATA_DIR` defaults to `$TMPDIR/tf-func-matrix-work/mise`
  so installs don't touch your normal mise cache; set `MISE_DATA_DIR` to
  reuse it instead. If mise cannot install a version, the script logs
  `MISE-FALLBACK` and downloads the release zip for that version only. Runs
  6 versions in parallel.
- **Caching / SKIP:** `data/` is gitignored, so a fresh checkout has no raw
  dumps. A version is skipped when `data/functions-<product>-<version>.json`
  exists *or* it is already listed in the committed `functions-matrix.json`.
  `build-matrix.py` then reconstructs per-version presence for those
  matrix-only versions from `introduced` / `removed` / `gaps` (lossless; a
  rebuild with an empty `data/` reproduces the committed matrix
  byte-for-byte) and merges in the fresh dumps. Signatures come from the
  newest dump per product (Terraform wording wins when both have the
  function).
- **Full regeneration:** `FULL=1 scripts/sweep.sh` and
  `FULL=1 python3 scripts/build-matrix.py` ignore the committed matrix and
  sweep every release (~150 binaries).
- **Committed:** `functions-matrix.json` and `report.html`. Afterwards update
  the delta table in `PROPOSAL.md` from the `build-matrix.py` console summary
  (introduced-later / product-exclusive / removed / gaps).
