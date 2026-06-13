#!/usr/bin/env bash
#
# _sl-common.sh — shared helpers for sl-mount / sl-unmount.
# Not executable on its own; sourced by the two wrappers.
#
# Planning artifacts (SpecLedger commands/skills, the specledger/ workspace,
# .specledger/ steering files) live in THIS cdktn-planning repo. The wrappers
# drop locally-ignored symlinks into a contributor's cdk-terrain checkout so the
# tooling works in place while staying out of cdk-terrain's git history.

PLANNING_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SL_VERSION="1.2.2"
MARKER="cdktn-planning/scripts/sl-mount"   # tag in generated mise.local.toml

note() { printf '  %s\n' "$*"; }
warn() { printf '  ⚠ %s\n' "$*" >&2; }

# resolve_target [PATH] — sets global TARGET (abs) and EXCLUDE; prompts if no arg.
resolve_target() {
  local t=${1:-}
  if [[ -z "$t" ]]; then
    read -rp "Path to your cdk-terrain checkout: " t
  fi
  t="${t/#\~/$HOME}"
  [[ -d "$t" ]] || { echo "error: not a directory: $t" >&2; exit 1; }
  t="$(cd "$t" && pwd)"
  [[ -e "$t/.git" ]] || { echo "error: $t is not a git repo" >&2; exit 1; }
  if [[ ! -d "$t/packages/cdktn" ]]; then
    echo "warning: $t doesn't look like cdk-terrain (no packages/cdktn). Continuing." >&2
  fi
  TARGET="$t"
  EXCLUDE="$t/.git/info/exclude"
}

# link_one SRC DEST — symlink SRC->DEST, never clobbering a real (non-symlink) file.
# Sets CONFLICTS=1 on a real-file collision.
link_one() {
  local src=$1 dest=$2
  if [[ -L "$dest" ]]; then
    if [[ "$(readlink "$dest")" == "$src" ]]; then note "ok      ${dest#"$TARGET"/}"; return; fi
    rm "$dest"; ln -s "$src" "$dest"; note "relink  ${dest#"$TARGET"/}"
  elif [[ -e "$dest" ]]; then
    warn "CONFLICT: real file at ${dest#"$TARGET"/} — left untouched"; CONFLICTS=1
  else
    ln -s "$src" "$dest"; note "link    ${dest#"$TARGET"/}"
  fi
}

# unlink_one DEST — remove DEST only if it's a symlink into this planning repo.
unlink_one() {
  local dest=$1
  if [[ -L "$dest" && "$(readlink "$dest")" == "$PLANNING_ROOT"/* ]]; then
    rm "$dest"; note "removed ${dest#"$TARGET"/}"
  fi
}

# _unlink_dest SRC DEST — adapter so for_each_* (which pass src+dest) can unlink.
_unlink_dest() { unlink_one "$2"; }

exclude_add() {
  local pat=$1
  grep -qxF "$pat" "$EXCLUDE" 2>/dev/null || printf '%s\n' "$pat" >> "$EXCLUDE"
}

# for_each_command CALLBACK — invokes CALLBACK with (src, dest) per specledger cmd.
for_each_command() {
  local cb=$1 f
  for f in "$PLANNING_ROOT"/.agents/commands/specledger.*.md; do
    [[ -e "$f" ]] || continue
    "$cb" "$f" "$TARGET/.claude/commands/$(basename "$f")"
  done
}

# for_each_skill CALLBACK — invokes CALLBACK with (src, dest) per sl-* skill.
for_each_skill() {
  local cb=$1 d
  for d in "$PLANNING_ROOT"/.agents/skills/sl-*; do
    [[ -d "$d" ]] || continue
    "$cb" "$d" "$TARGET/.claude/skills/$(basename "$d")"
  done
}
