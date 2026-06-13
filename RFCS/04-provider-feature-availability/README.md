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
