#!/usr/bin/env bash
# Sweeps the CLI command / flag surface of Terraform and OpenTofu.
#
# For the first and the last stable patch of every minor line — Terraform
# >= 1.5.7, OpenTofu >= 1.6.0, from the same release indexes as sweep.sh —
# this script:
#   1. installs the CLI via mise (`mise install terraform@<v>` /
#      `opentofu@<v>`; zip download fallback) and resolves the binary once via
#      `mise exec <product>@<v> -- sh -c 'command -v <exe>'`,
#   2. runs scripts/cli_help.py against it, which walks `<bin> -help`, every
#      listed command's `<bin> <cmd> -help` and every listed subcommand
#      (state *, workspace *, providers *, metadata *, ...) and parses
#      commands, flags, value kinds, aliases and deprecation markers,
#   3. writes data/cli-surface-<product>-<version>.json (committed).
# Afterwards it runs scripts/cli-source-check.py at every swept version of
# each product (needs the reference clones, see below) and writes
# data/cli-source-check-<product>-<version>.json: the flags the parser
# accepts, per command, which is what "accepted since" and any allowlist
# must be based on (help only says what is listed).
#
# Why first + last patch per minor: new commands and flags ship in minor
# releases, but both products have backported or patch-level CLI changes
# (and the occasional removal), so the last patch of each minor line catches
# anything a .0-only selection would miss, at ~2 binaries per minor instead of
# every release. Help output does not need providers, so — unlike sweep.sh —
# Terraform 1.6.0 is swept as is (its expired-key problem only affects
# provider installation).
#
# Unparsed help lines are printed as `UNPARSED <product> <version> '<cmd>':`
# and kept in each JSON's "unparsed" map; review them after a run.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/data"
WORK="${TMPDIR:-/tmp}/cli-surface-sweep"
mkdir -p "$DATA" "$WORK"
# CLI binaries are installed by mise into a throwaway data dir under $WORK
# (override with MISE_DATA_DIR to share an existing mise install cache)
export MISE_DATA_DIR="${MISE_DATA_DIR:-$WORK/mise}"
# reference source clones for the source cross-check (blobless clones are fine)
REF_TERRAFORM="${REF_TERRAFORM:-$HOME/cdktn/ref-terraform}"
REF_OPENTOFU="${REF_OPENTOFU:-$HOME/cdktn/ref-opentofu}"

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) ARCH=amd64 ;;
  aarch64) ARCH=arm64 ;;
esac
export OS ARCH ROOT DATA WORK

# Prints the first and the last stable patch of every minor line >= floor.
select_versions() {
  python3 -I -c "
import sys, re
from collections import defaultdict
floor = tuple(int(x) for x in sys.argv[1].split('.'))
versions = [l.strip() for l in sys.stdin if re.fullmatch(r'\d+\.\d+\.\d+', l.strip())]
def vkey(v): return tuple(int(x) for x in v.split('.'))
stable = sorted({v for v in versions if vkey(v) >= floor}, key=vkey)
by_minor = defaultdict(list)
for v in stable:
    by_minor[v.rsplit('.', 1)[0]].append(v)
chosen = {vs[0] for vs in by_minor.values()} | {vs[-1] for vs in by_minor.values()}
print('\n'.join(sorted(chosen, key=vkey)))
" "$1"
}

terraform_versions() {
  curl -fsSL https://releases.hashicorp.com/terraform/index.json \
    | python3 -I -c "import json,sys; print('\n'.join(json.load(sys.stdin)['versions']))" \
    | select_versions 1.5.7
}

opentofu_versions() {
  curl -fsSL https://get.opentofu.org/tofu/api.json \
    | python3 -I -c "import json,sys; print('\n'.join(v['id'] for v in json.load(sys.stdin)['versions']))" \
    | select_versions 1.6.0
}

process_one() {
  local product="$1" version="$2"
  local out="$DATA/cli-surface-${product}-${version}.json"
  if [ -s "$out" ]; then
    echo "SKIP $product $version (exists)"
    return 0
  fi

  local url exe zip dir bin
  dir="$WORK/${product}-${version}"
  rm -rf "$dir"
  mkdir -p "$dir/cwd"
  zip="$dir/pkg.zip"
  if [ "$product" = "terraform" ]; then
    url="https://releases.hashicorp.com/terraform/${version}/terraform_${version}_${OS}_${ARCH}.zip"
    exe=terraform
  else
    url="https://github.com/opentofu/opentofu/releases/download/v${version}/tofu_${version}_${OS}_${ARCH}.zip"
    exe=tofu
  fi

  # install with mise; resolve the real binary once so cli_help.py can run
  # ~50 `-help` invocations without a mise round-trip each. cwd=$dir (outside
  # the repo), so no project mise.toml applies.
  if mise install -q "${product}@${version}" > "$dir/mise.log" 2>&1 \
     && bin="$(cd "$dir" && mise exec "${product}@${version}" -- sh -c "command -v $exe")" \
     && [ -x "$bin" ]; then
    :
  else
    echo "MISE-FALLBACK $product $version: $(tail -c 200 "$dir/mise.log")"
    if ! curl -fsSL -o "$zip" "$url"; then
      echo "FAIL-DOWNLOAD $product $version"
      return 1
    fi
    if ! unzip -oq "$zip" -d "$dir"; then
      echo "FAIL-UNZIP $product $version"
      return 1
    fi
    bin="$dir/$exe"
  fi

  # empty cwd: no configuration, no .terraform dir, no -chdir surprises
  if ! CLI_SWEEP_CWD="$dir/cwd" python3 -I "$ROOT/scripts/cli_help.py" "$bin" "$product" "$version" \
       > "$out.tmp" 2> "$dir/parse.log"; then
    echo "FAIL-PARSE $product $version: $(tail -c 300 "$dir/parse.log")"
    rm -f "$out.tmp"
    return 1
  fi
  grep -E '^(UNPARSED|NO-USAGE)' "$dir/parse.log" || true
  mv "$out.tmp" "$out"
  rm -rf "$dir"
  echo "OK $product $version $(python3 -I -c "import json,sys; print(json.load(open(sys.argv[1]))['counts'])" "$out")"
}

export -f process_one

# single-version mode: cli-sweep.sh <product> <version> [<product> <version> ...]
if [ "$#" -ge 2 ]; then
  while [ "$#" -ge 2 ]; do
    process_one "$1" "$2"
    shift 2
  done
else
  {
    terraform_versions | sed 's/^/terraform /'
    opentofu_versions | sed 's/^/opentofu /'
  } | xargs -n 2 -P "${SWEEP_PARALLELISM:-4}" bash -c 'process_one "$0" "$1"'
fi

# Source cross-check at EVERY swept version: what the parser accepts (the
# basis for "accepted since" and for any allowlist), not only what help
# lists. The needed blobs (commands.go + internal/command{,/arguments}/*.go
# at every swept tag) are prefetched in one batch first: a blobless clone
# otherwise fetches each blob in its own round trip (~1 s each).
prefetch_blobs() {
  local ref="$1" cmdfile="$2"; shift 2
  local v
  for v in "$@"; do
    git -C "$ref" ls-tree -r "v$v" -- "$cmdfile" internal/command/ 2>/dev/null \
      | awk -v cf="$cmdfile" '$4 ~ /\.go$/ && $4 !~ /_test\.go$/ && ($4 == cf || $4 ~ /^internal\/command\/[^\/]+$/ || $4 ~ /^internal\/command\/arguments\/[^\/]+$/) {print $3}'
  done | sort -u > "$WORK/oids-wanted.txt"
  git -C "$ref" cat-file --batch-all-objects --batch-check='%(objectname)' 2>/dev/null | sort -u > "$WORK/oids-have.txt"
  comm -23 "$WORK/oids-wanted.txt" "$WORK/oids-have.txt" > "$WORK/oids-missing.txt"
  if [ -s "$WORK/oids-missing.txt" ]; then
    echo "PREFETCH $(wc -l < "$WORK/oids-missing.txt" | tr -d ' ') blobs into $ref"
    git -C "$ref" -c fetch.negotiationAlgorithm=noop fetch origin --no-tags --no-write-fetch-head \
      --recurse-submodules=no --filter=blob:none --stdin < "$WORK/oids-missing.txt" > /dev/null 2>&1 \
      || echo "PREFETCH-FAIL $ref (blobs are then fetched one by one)"
  fi
}

for product in terraform opentofu; do
  versions="$(ls "$DATA" | sed -n "s/^cli-surface-${product}-\([0-9.]*\)\.json$/\1/p" | sort -t. -k1,1n -k2,2n -k3,3n)"
  [ -n "$versions" ] || continue
  ref="$REF_TERRAFORM"; cmdfile=commands.go
  [ "$product" = opentofu ] && { ref="$REF_OPENTOFU"; cmdfile=cmd/tofu/commands.go; }
  if [ ! -d "$ref" ]; then
    echo "SKIP source-check $product (no reference clone at $ref)"
    continue
  fi
  todo=()
  for v in $versions; do
    [ -s "$DATA/cli-source-check-${product}-${v}.json" ] || todo+=("$v")
  done
  [ "${#todo[@]}" -gt 0 ] || { echo "SKIP source-check $product (all exist)"; continue; }
  prefetch_blobs "$ref" "$cmdfile" "${todo[@]}"
  for v in "${todo[@]}"; do
    check="$DATA/cli-source-check-${product}-${v}.json"
    python3 -I "$ROOT/scripts/cli-source-check.py" "$ref" "$product" "$v" \
      "$DATA/cli-surface-${product}-${v}.json" > "$check.tmp" \
      && mv "$check.tmp" "$check" && echo "OK source-check $product $v" \
      || { echo "FAIL source-check $product $v"; rm -f "$check.tmp"; }
  done
done

# Binary probe at every swept version: runs each candidate flag against the
# real binary (scripts/cli-probe.py) as ground truth for the source check;
# build-cli-matrix.py reports any disagreement with `!!`.
for product in terraform opentofu; do
  exe=terraform; [ "$product" = opentofu ] && exe=tofu
  for v in $(ls "$DATA" | sed -n "s/^cli-source-check-${product}-\([0-9.]*\)\.json$/\1/p" | sort -t. -k1,1n -k2,2n -k3,3n); do
    probe="$DATA/cli-probe-${product}-${v}.json"
    [ -s "$probe" ] && continue
    mkdir -p "$WORK/probe"
    if ! bin="$(cd "$WORK/probe" && mise exec "${product}@${v}" -- sh -c "command -v $exe")" || [ ! -x "$bin" ]; then
      echo "SKIP probe $product $v (mise exec failed; run the sweep for it first)"
      continue
    fi
    python3 -I "$ROOT/scripts/cli-probe.py" "$bin" "$product" "$v" "$DATA" > "$probe.tmp" \
      && mv "$probe.tmp" "$probe" && echo "OK probe $product $v" \
      || { echo "FAIL probe $product $v"; rm -f "$probe.tmp"; }
  done
done

echo "DONE: $(ls "$DATA" | grep -c '^cli-surface-') CLI surface dumps in $DATA"
