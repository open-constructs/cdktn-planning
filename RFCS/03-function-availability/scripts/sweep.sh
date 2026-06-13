#!/usr/bin/env bash
# Baseline script that produced the initial function-availability dataset.
#
# Downloads every stable Terraform (>= 1.5.7) and OpenTofu release binary for
# the current machine, runs `<binary> metadata functions -json`, and stores the
# output as data/functions-<product>-<version>.json next to this directory.
#
# Only needed for a full regeneration of the dataset; incremental updates for
# new releases use `pnpm update-function-matrix` in tools/generate-function-bindings.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/data"
WORK="${TMPDIR:-/tmp}/tf-func-matrix-work"
mkdir -p "$DATA" "$WORK"

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) ARCH=amd64 ;;
  aarch64) ARCH=arm64 ;;
esac
export OS ARCH

terraform_versions() {
  curl -fsSL https://releases.hashicorp.com/terraform/index.json | python3 -c "
import json,sys,re
data = json.load(sys.stdin)
def vkey(v): return tuple(int(x) for x in v.split('.'))
stable = [v for v in data['versions'] if re.fullmatch(r'\d+\.\d+\.\d+', v) and vkey(v) >= (1,5,7)]
stable.sort(key=vkey)
print('\n'.join(stable))
"
}

opentofu_versions() {
  curl -fsSL https://get.opentofu.org/tofu/api.json | python3 -c "
import json,sys,re
data = json.load(sys.stdin)
stable = [v['id'] for v in data['versions'] if re.fullmatch(r'\d+\.\d+\.\d+', v['id'])]
stable.sort(key=lambda v: tuple(int(x) for x in v.split('.')))
print('\n'.join(stable))
"
}

process_one() {
  local product="$1" version="$2"
  local out="$DATA/functions-${product}-${version}.json"
  if [ -s "$out" ]; then
    echo "SKIP $product $version (exists)"
    return 0
  fi

  local url bin zip dir
  dir="$WORK/${product}-${version}"
  mkdir -p "$dir"
  zip="$dir/pkg.zip"

  if [ "$product" = "terraform" ]; then
    url="https://releases.hashicorp.com/terraform/${version}/terraform_${version}_${OS}_${ARCH}.zip"
    bin="$dir/terraform"
  else
    url="https://github.com/opentofu/opentofu/releases/download/v${version}/tofu_${version}_${OS}_${ARCH}.zip"
    bin="$dir/tofu"
  fi

  if ! curl -fsSL -o "$zip" "$url"; then
    echo "FAIL-DOWNLOAD $product $version"
    rm -rf "$dir"
    return 1
  fi
  if ! unzip -oq "$zip" -d "$dir"; then
    echo "FAIL-UNZIP $product $version"
    rm -rf "$dir"
    return 1
  fi
  if ! "$bin" metadata functions -json > "$out.tmp" 2>"$dir/stderr.log"; then
    echo "FAIL-METADATA $product $version: $(head -c 200 "$dir/stderr.log")"
    rm -f "$out.tmp"
    rm -rf "$dir"
    return 1
  fi
  mv "$out.tmp" "$out"
  rm -rf "$dir"
  echo "OK $product $version"
}

export -f process_one
export DATA WORK

{
  terraform_versions | sed 's/^/terraform /'
  opentofu_versions | sed 's/^/opentofu /'
} | xargs -n 2 -P 6 bash -c 'process_one "$0" "$1"'

echo "DONE: $(ls "$DATA" | wc -l | tr -d ' ') data files in $DATA"
