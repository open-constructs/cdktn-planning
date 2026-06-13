#!/usr/bin/env bash
# Builds the provider-protocol feature availability dataset.
#
# For every minor-boundary release of Terraform (>= 1.5.7) and OpenTofu
# (>= 1.6.0) plus the overall latest patch of each product, this script:
#   1. downloads the CLI binary,
#   2. runs `<binary> init` against fixture/main.tf.json (small providers that
#      exercise provider functions, ephemeral resources, write-only attributes
#      and actions),
#   3. runs `<binary> providers schema -json`,
#   4. reduces the (large) schema JSON to a small committed digest via
#      scripts/digest.py -> data/schema-digest-<product>-<version>.json.
#
# Raw schema dumps land in data/raw/ (gitignored). Digests are committed so
# build-matrix.py / build-report.py work without re-running the sweep.
#
# Minor-boundary releases suffice: the `providers schema -json` keys are fixed
# struct fields per CLI minor (see PROPOSAL.md), patches never add keys.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/data"
RAW="$DATA/raw"
WORK="${TMPDIR:-/tmp}/provider-feature-sweep"
CACHE="$WORK/plugin-cache"
mkdir -p "$DATA" "$RAW" "$WORK" "$CACHE"

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) ARCH=amd64 ;;
  aarch64) ARCH=arm64 ;;
esac
export OS ARCH ROOT DATA RAW WORK CACHE

# Prints the minor-boundary selection (first stable patch of each minor within
# range, normally X.Y.0) plus the overall latest stable release.
select_versions() {
  python3 -c "
import json, sys, re
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
  curl -fsSL https://releases.hashicorp.com/terraform/index.json \
    | python3 -c "import json,sys; print('\n'.join(json.load(sys.stdin)['versions']))" \
    | select_versions 1.5.7
}

opentofu_versions() {
  curl -fsSL https://get.opentofu.org/tofu/api.json \
    | python3 -c "import json,sys; print('\n'.join(v['id'] for v in json.load(sys.stdin)['versions']))" \
    | select_versions 1.6.0
}

process_one() {
  local product="$1" version="$2"
  # FIXTURE selects the workspace definition: "core" (fixture/main.tf.json,
  # small providers, all versions) or "aws" (fixture/aws.tf.json — the only
  # fixture exhibiting resource identity, list resources and cloud actions;
  # swept from 1.12 only, where those families start being emitted).
  local fixture="${FIXTURE:-core}" prefix=""
  [ "$fixture" != "core" ] && prefix="${fixture}-"
  local out="$DATA/schema-digest-${prefix}${product}-${version}.json"
  if [ -s "$out" ]; then
    echo "SKIP $product $version (exists)"
    return 0
  fi

  local url bin zip dir
  dir="$WORK/${product}-${version}"
  rm -rf "$dir"
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
    return 1
  fi
  if ! unzip -oq "$zip" -d "$dir"; then
    echo "FAIL-UNZIP $product $version"
    return 1
  fi

  if [ "$fixture" = "core" ]; then
    cp "$ROOT/fixture/main.tf.json" "$dir/main.tf.json"
  else
    cp "$ROOT/fixture/${fixture}.tf.json" "$dir/main.tf.json"
  fi
  # one retry: registry flakes / plugin-cache races
  local attempt
  for attempt in 1 2; do
    if (cd "$dir" && TF_PLUGIN_CACHE_DIR="$CACHE" TF_IN_AUTOMATION=1 \
        "$bin" init -backend=false -input=false -no-color > init.log 2>&1); then
      break
    fi
    if [ "$attempt" = 2 ]; then
      echo "FAIL-INIT $product $version: $(tail -c 300 "$dir/init.log")"
      return 1
    fi
    sleep 2
  done

  local raw_schema="$dir/schema.json"
  if ! (cd "$dir" && "$bin" providers schema -json > "$raw_schema" 2> schema-err.log); then
    echo "FAIL-SCHEMA $product $version: $(tail -c 300 "$dir/schema-err.log")"
    return 1
  fi
  (cd "$dir" && "$bin" version -json > version.json 2>/dev/null) || echo '{}' > "$dir/version.json"

  if ! python3 "$ROOT/scripts/digest.py" "$raw_schema" "$dir/version.json" "$product" "$version" > "$out.tmp"; then
    echo "FAIL-DIGEST $product $version"
    rm -f "$out.tmp"
    return 1
  fi
  mv "$out.tmp" "$out"
  # keep raw dumps only when small enough to be useful on disk (the aws
  # fixture's dump is >100 MB per version — the digest is the durable record)
  local raw_keep_limit="${RAW_KEEP_LIMIT_BYTES:-8000000}"
  if [ "$(wc -c < "$raw_schema")" -le "$raw_keep_limit" ]; then
    mv "$raw_schema" "$RAW/schema-${prefix}${product}-${version}.json"
  fi
  rm -rf "$dir"
  echo "OK $fixture $product $version"
}

export -f process_one

# single-version mode: [FIXTURE=aws] sweep.sh <product> <version> [...]
# (used for incremental updates and for substituting a broken release, e.g.
# terraform 1.6.0 cannot init at all anymore — "openpgp: key expired" on every
# provider install, fixed in later 1.6.x patches — so the 1.6 column uses 1.6.6)
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
} | FIXTURE=core xargs -n 2 -P "${SWEEP_PARALLELISM:-1}" bash -c 'process_one "$0" "$1"'

# Second pass: the aws fixture, only at CLI versions >= 1.12 — resource
# identity emission starts at 1.12 in both products and list resources /
# actions at Terraform 1.14, so older columns cannot add signal and would just
# burn ~700 MB of provider install each.
aws_versions() {
  curl -fsSL https://releases.hashicorp.com/terraform/index.json \
    | python3 -c "import json,sys; print('\n'.join(json.load(sys.stdin)['versions']))" \
    | select_versions 1.12.0 | sed 's/^/terraform /'
  curl -fsSL https://get.opentofu.org/tofu/api.json \
    | python3 -c "import json,sys; print('\n'.join(v['id'] for v in json.load(sys.stdin)['versions']))" \
    | select_versions 1.12.0 | sed 's/^/opentofu /'
}
aws_versions | FIXTURE=aws xargs -n 2 -P "${SWEEP_PARALLELISM:-1}" bash -c 'process_one "$0" "$1"'

echo "DONE: $(ls "$DATA" | grep -c '^schema-digest-') digests in $DATA"
