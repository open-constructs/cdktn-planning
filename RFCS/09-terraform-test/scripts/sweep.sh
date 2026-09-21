#!/usr/bin/env bash
# Builds the `terraform test` / `tofu test` feature availability dataset.
#
# For every minor-boundary release of Terraform and OpenTofu (>= 1.6, where the
# test framework went GA) plus the overall latest patch of each product:
#   1. download the CLI binary,
#   2. run every fixture/probes/* (one test-framework feature each) through
#      scripts/run-probes.py -> data/probes-<product>-<version>.json.
#
# Same shape as ../04-provider-feature-availability/scripts/sweep.sh. Each
# binary gets a private plugin cache: TF_PLUGIN_CACHE_DIR is not concurrency
# safe (hashicorp/terraform#31964) and the only provider is the ~5 MB `random`.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/data"
WORK="${SWEEP_WORKDIR:-${TMPDIR:-/tmp}/terraform-test-sweep}"
mkdir -p "$DATA" "$WORK"

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) ARCH=amd64 ;;
  aarch64) ARCH=arm64 ;;
esac
export OS ARCH ROOT DATA WORK

select_versions() {
  python3 -c "
import sys, re
from collections import defaultdict
floor = tuple(int(x) for x in sys.argv[1].split('.'))
versions = [l.strip() for l in sys.stdin if re.fullmatch(r'\d+\.\d+\.\d+', l.strip())]
def vkey(v): return tuple(int(x) for x in v.split('.'))
stable = sorted({v for v in versions if vkey(v) >= floor}, key=vkey)
by_minor = defaultdict(list)
for v in stable:
    by_minor[v.rsplit('.', 1)[0]].append(v)
chosen = {vs[0] for vs in by_minor.values()} | {stable[-1]}
print('\n'.join(sorted(chosen, key=vkey)))
" "$1"
}

terraform_versions() {
  # 1.6.0 cannot install providers anymore ("openpgp: key expired"); 1.6.6 stands in
  curl -fsSL https://releases.hashicorp.com/terraform/index.json \
    | python3 -c "import json,sys; print('\n'.join(json.load(sys.stdin)['versions']))" \
    | select_versions 1.6.0 | sed 's/^1\.6\.0$/1.6.6/'
}

opentofu_versions() {
  curl -fsSL https://get.opentofu.org/tofu/api.json \
    | python3 -c "import json,sys; print('\n'.join(v['id'] for v in json.load(sys.stdin)['versions']))" \
    | select_versions 1.6.0
}

process_one() {
  local product="$1" version="$2"
  local out="$DATA/probes-${product}-${version}.json"
  if [ -s "$out" ]; then
    echo "SKIP $product $version (exists)"
    return 0
  fi
  local url bin dir="$WORK/${product}-${version}"
  rm -rf "$dir"
  mkdir -p "$dir/plugin-cache" "$dir/work"
  if [ "$product" = "terraform" ]; then
    url="https://releases.hashicorp.com/terraform/${version}/terraform_${version}_${OS}_${ARCH}.zip"
    bin="$dir/terraform"
  else
    url="https://github.com/opentofu/opentofu/releases/download/v${version}/tofu_${version}_${OS}_${ARCH}.zip"
    bin="$dir/tofu"
  fi
  # SWEEP_BIN_CACHE=<dir> keeps binaries across runs (probe changes re-sweep every version)
  local kept="${SWEEP_BIN_CACHE:+$SWEEP_BIN_CACHE/${product}-${version}}"
  if [ -n "$kept" ] && [ -x "$kept" ]; then
    cp "$kept" "$bin"
  elif ! curl -fsSL -o "$dir/pkg.zip" "$url" || ! unzip -oq "$dir/pkg.zip" -d "$dir"; then
    echo "FAIL-DOWNLOAD $product $version"
    return 1
  elif [ -n "$kept" ]; then
    mkdir -p "$SWEEP_BIN_CACHE" && cp "$bin" "$kept"
  fi
  if ! python3 "$ROOT/scripts/run-probes.py" "$bin" "$product" "$version" "$dir/work" "$dir/plugin-cache" > "$out.tmp"; then
    echo "FAIL-PROBES $product $version"
    rm -f "$out.tmp"
    return 1
  fi
  mv "$out.tmp" "$out"
  rm -rf "$dir"
  echo "OK $product $version"
}
export -f process_one

# single-version mode: sweep.sh <product> <version> [...]
if [ "$#" -ge 2 ]; then
  while [ "$#" -ge 2 ]; do
    process_one "$1" "$2"
    shift 2
  done
  exit 0
fi

{
  terraform_versions | sed 's/^/terraform /'
  opentofu_versions | sed 's/^/opentofu /'
} | xargs -n 2 -P "${SWEEP_PARALLELISM:-4}" bash -c 'process_one "$0" "$1"'

echo "DONE: $(ls "$DATA" | grep -c '^probes-') digests in $DATA"
