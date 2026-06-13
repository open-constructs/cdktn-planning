# CDK Terrain Planning

This repository tracks RFCs and proposals for the CDK Terrain framework, and
isolates the Spec Driven Development (SpecLedger) artifacts out of the
[`cdk-terrain`](https://github.com/open-constructs/cdk-terrain) monorepo.

Keeping planning here means PRs against `cdk-terrain` stay small, code-only, and
easy to review — and contributors stay free to pick their own LLM framework and
planning tools without forcing any of it into the source repo's history.

## Layout

| Path                | Contents                                                              |
| ------------------- | -------------------------------------------------------------------- |
| `.agents/commands/` | SpecLedger slash-commands (`specledger.*.md`) — source of truth      |
| `.agents/skills/`   | SpecLedger skills (`sl-*`)                                            |
| `specledger/`       | Per-feature SpecLedger workspace (`spec.md`, `plan.md`, `tasks.md`…) |
| `.specledger/`      | SpecLedger steering files (constitution, templates)                  |
| `RFCS/`             | RFCs and proposals                                                   |
| `reports/`          | Generated reports & handover notes                                   |
| `scripts/`          | `sl-mount` / `sl-unmount` onboarding scripts                         |
| `mise.toml`         | Declares the SpecLedger CLI (`sl`) via mise                          |

## Onboarding — mount the tooling into your `cdk-terrain` checkout

The planning artifacts live here, but the SpecLedger tooling needs to run from
your `cdk-terrain` checkout. `sl-mount` wires the two together with symlinks
that are **ignored locally** (via `.git/info/exclude`) so they can never be
committed to `cdk-terrain`.

```bash
# from this repo:
./scripts/sl-mount /path/to/cdk-terrain      # omit the path to be prompted

cd /path/to/cdk-terrain
mise install                                 # fetches the `sl` CLI
sl --version
```

What `sl-mount` does (idempotent — safe to re-run after the artifacts change):

1. Symlinks each `.agents/commands/specledger.*.md` → `<cdk-terrain>/.claude/commands/`
2. Symlinks each `.agents/skills/sl-*` → `<cdk-terrain>/.claude/skills/`
3. Symlinks `specledger/` and `.specledger/` → `<cdk-terrain>/` (whole dirs), so
   `sl` and the commands read/write **here** while you work in `cdk-terrain`
4. Writes `<cdk-terrain>/mise.local.toml` (untracked) providing the `sl` CLI
5. Adds every linked path to `<cdk-terrain>/.git/info/exclude` — a local,
   never-committed ignore file

It links the individual `specledger.*` / `sl-*` entries only — never the
`.claude/commands` or `.claude/skills` folders — so any commands/skills already
checked into `cdk-terrain` are preserved, and it refuses to overwrite a real
file of the same name (it reports a conflict and skips instead).

To remove everything it placed:

```bash
./scripts/sl-unmount /path/to/cdk-terrain
```

> **Note:** the `sl` CLI is the [SpecLedger](https://github.com/specledger/specledger)
> binary, pinned in `mise.toml` here and mirrored into the generated
> `mise.local.toml`. `.claude/commands` and `.claude/skills` are the
> [Claude Code](https://claude.com/claude-code) layout; point `sl-mount` at a
> different framework's directory by adjusting the script if you use another tool.
