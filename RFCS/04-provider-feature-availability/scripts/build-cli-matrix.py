#!/usr/bin/env python3
"""Builds cli-matrix.json from data/cli-surface-*.json (+ cli-source-check-*.json).

Per command and per (command, flag) and per global option, for each product:
  present        swept versions where help lists it
  first_seen     first swept version that lists it
  introduced_after  the swept version before first_seen (null if first_seen
                 is the oldest swept version) — the item shipped in
                 (introduced_after, first_seen]
  last_seen / removed_in  last swept version that lists it / the next swept
                 version (null while still present at the newest version)
  gaps           swept versions between first_seen and last_seen that do
                 not list it
  via            "listed" or "plan-reference" (apply/destroy help pages that
                 delegate their plan options to `plan -help`; the plan page's
                 "Plan Customization Options" then count as present)
plus `only` ("terraform" / "opentofu" when the other product never lists it),
and `hidden_in_source` from the source cross-check (flags/commands that the
newest version accepts but its help does not list).

`cdktn` section: every terraform/tofu flag the cdktn CLI emits today
(cdk-terrain main, see CDKTN_EMITTED) with its availability per product.

Usage: python3 -I scripts/build-cli-matrix.py
"""
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "cli-matrix.json")
PRODUCTS = ["terraform", "opentofu"]

# Terraform/tofu invocations built by cdk-terrain (open-constructs/cdk-terrain
# main @ c65bf2f27, 2026-10). The cdktn CLI never forwards arbitrary user
# flags: every flag below is a fixed literal or is derived from a declared
# cdktn option (see PROPOSAL.md "Relation to cdk-terrain PR #513").
CDKTN_EMITTED = [
    ("init", "-upgrade", "cli-core terraform-cli.ts init() (needsUpgrade)"),
    ("init", "-no-color", "cli-core terraform-cli.ts init() (--no-color)"),
    ("init", "-migrate-state", "cli-core terraform-cli.ts init() (--migrate-state)"),
    ("providers lock", "-platform", "cli-core terraform-cli.ts init() (needsLockfileUpdate)"),
    ("providers lock", "-no-color", "cli-core terraform-cli.ts init() (--no-color)"),
    ("plan", "-input", "cli-core terraform-cli.ts plan() (always -input=false)"),
    ("plan", "-generate-config-out", "cli-core terraform-cli.ts plan() (stack has import blocks)"),
    ("plan", "-out", "cli-core terraform-cli.ts plan() (non-cloud stacks)"),
    ("plan", "-destroy", "cli-core terraform-cli.ts plan() (cdktn diff for destroy)"),
    ("plan", "-refresh-only", "cli-core terraform-cli.ts plan() (--refresh-only)"),
    ("plan", "-parallelism", "cli-core terraform-cli.ts plan() (--terraform-parallelism)"),
    ("plan", "-no-color", "cli-core terraform-cli.ts plan() (--no-color)"),
    ("plan", "-var", "cli-core terraform-cli.ts plan() (--var)"),
    ("plan", "-var-file", "cli-core terraform-cli.ts plan() (--var-file)"),
    ("apply", "-auto-approve", "cli-core deploy-machine.ts (--auto-approve)"),
    ("apply", "-refresh-only", "cli-core deploy-machine.ts (--refresh-only)"),
    ("apply", "-no-color", "cli-core deploy-machine.ts (--no-color)"),
    ("apply", "-parallelism", "cli-core deploy-machine.ts (--terraform-parallelism)"),
    ("apply", "-var", "cli-core deploy-machine.ts (--var)"),
    ("apply", "-var-file", "cli-core deploy-machine.ts (--var-file)"),
    ("destroy", "-auto-approve", "cli-core deploy-machine.ts (--auto-approve)"),
    ("destroy", "-no-color", "cli-core deploy-machine.ts (--no-color)"),
    ("destroy", "-parallelism", "cli-core deploy-machine.ts (--terraform-parallelism)"),
    ("destroy", "-var", "cli-core deploy-machine.ts (--var)"),
    ("destroy", "-var-file", "cli-core deploy-machine.ts (--var-file)"),
    ("output", "-json", "cli-core terraform-cli.ts output()"),
    ("providers schema", "-json", "provider-schema provider-schema.ts"),
    ("version", "-json", "provider-schema provider-schema.ts"),
]

# Flags cdktn emits that some swept versions accept without listing them in
# help, verified in source (git show <tag>:internal/command/providers_lock.go).
CDKTN_SOURCE_VERIFIED = {
    ("providers lock", "-no-color"): {
        "terraform": "stripped by Meta.process() before flag parsing in every swept version "
                     "(v1.5.7 .. v1.17.0); never listed in help",
        "opentofu": "Meta.process() (1.6-1.11) / arguments.ParseView (1.12) / BindView (1.13); "
                    "listed in help only from 1.13.0",
    },
}


def vkey(v):
    return tuple(int(x) for x in v.split("."))


def load():
    surfaces = {p: {} for p in PRODUCTS}
    for path in glob.glob(os.path.join(DATA, "cli-surface-*.json")):
        m = re.match(r"cli-surface-(terraform|opentofu)-(\d+\.\d+\.\d+)\.json$", os.path.basename(path))
        if not m:
            continue
        with open(path) as f:
            surfaces[m.group(1)][m.group(2)] = json.load(f)
    checks = {}
    for path in glob.glob(os.path.join(DATA, "cli-source-check-*.json")):
        m = re.match(r"cli-source-check-(terraform|opentofu)-(\d+\.\d+\.\d+)\.json$", os.path.basename(path))
        if m:
            with open(path) as f:
                checks[m.group(1)] = json.load(f)
    return surfaces, checks


def span(present, versions, via=None):
    if not present:
        return None
    idx = [versions.index(v) for v in present]
    first, last = min(idx), max(idx)
    rec = {
        "first_seen": versions[first],
        "introduced_after": versions[first - 1] if first > 0 else None,
        "last_seen": versions[last],
        "removed_in": versions[last + 1] if last + 1 < len(versions) else None,
        "gaps": [versions[i] for i in range(first, last + 1) if versions[i] not in present],
        "count": len(present),
    }
    if via:
        rec["via"] = via
    return rec


def main():
    surfaces, checks = load()
    versions = {p: sorted(surfaces[p], key=vkey) for p in PRODUCTS}

    cmd_present = {}  # cmd -> product -> [versions]
    cmd_meta = {}
    flag_present = {}  # (cmd, flag) -> product -> {v: via}
    flag_meta = {}  # (cmd, flag) -> product -> latest flag record
    glob_present = {}
    glob_meta = {}

    for p in PRODUCTS:
        for v in versions[p]:
            s = surfaces[p][v]
            for g in s["global_options"]:
                glob_present.setdefault(g["name"], {}).setdefault(p, []).append(v)
                glob_meta.setdefault(g["name"], {})[p] = g
            for cmd, entry in s["commands"].items():
                cmd_present.setdefault(cmd, {}).setdefault(p, []).append(v)
                cmd_meta.setdefault(cmd, {})[p] = {
                    "listed_in": entry.get("listed_in"),
                    "not_swept": entry.get("not_swept"),
                    "usage": entry.get("usage"),
                }
                listed = {f["name"] for f in entry.get("flags", [])}
                for f in entry.get("flags", []):
                    flag_present.setdefault((cmd, f["name"]), {}).setdefault(p, {})[v] = "listed"
                    flag_meta.setdefault((cmd, f["name"]), {})[p] = f
                refers = entry.get("help_refers_to")
                if refers == "apply" and "apply" in s["commands"]:
                    for f in s["commands"]["apply"].get("flags", []):
                        if f["name"] not in listed:
                            listed.add(f["name"])
                            flag_present.setdefault((cmd, f["name"]), {}).setdefault(p, {})[v] = "apply-reference"
                            flag_meta.setdefault((cmd, f["name"]), {}).setdefault(p, f)
                    refers = s["commands"]["apply"].get("help_refers_to")
                if refers == "plan" and "plan" in s["commands"]:
                    for f in s["commands"]["plan"].get("flags", []):
                        if f["section"].lower().startswith("plan customization") and f["name"] not in listed:
                            flag_present.setdefault((cmd, f["name"]), {}).setdefault(p, {})[v] = "plan-reference"
                            flag_meta.setdefault((cmd, f["name"]), {}).setdefault(p, f)

    hidden_flags = {p: {} for p in PRODUCTS}
    hidden_cmds = {p: [] for p in PRODUCTS}
    for p, chk in checks.items():
        hidden_cmds[p] = chk["commands"]["in_source_not_in_help"]
        for cmd, e in chk["flags"].items():
            for name in e["in_source_not_in_help"]:
                src = next(r for r in e["source"] if r["name"] == name)
                hidden_flags[p][(cmd, name)] = {
                    "version": chk["version"],
                    "origin": src["origin"],
                    "guards": src["guards"],
                    "hidden_attr": src["hidden"],
                }

    # "view" family: output/diagnostic flags registered by the products'
    # shared view-argument helpers (Terraform arguments.ParseView; OpenTofu
    # arguments.BindView). OpenTofu 1.13 generates help from flag
    # definitions and lists these on (nearly) every command, which would
    # otherwise dominate the OpenTofu-only counts.
    view_family = {p: set() for p in PRODUCTS}
    for p, chk in checks.items():
        for e in chk["flags"].values():
            for r in e["source"]:
                if r["origin"].endswith((":BindView", ":ParseView")):
                    view_family[p].add(r["name"])
    all_view = set().union(*view_family.values())

    def only_of(prod_map):
        have = [p for p in PRODUCTS if prod_map.get(p)]
        return have[0] if len(have) == 1 else None

    commands = {}
    for cmd in sorted(set(cmd_present) | {c for p in PRODUCTS for c in hidden_cmds[p]}):
        prods = {}
        for p in PRODUCTS:
            pres = cmd_present.get(cmd, {}).get(p, [])
            rec = span(pres, versions[p])
            if rec:
                rec.update({k: v for k, v in cmd_meta[cmd][p].items() if v})
            if cmd in hidden_cmds[p]:
                rec = rec or {}
                rec["hidden_in_source"] = checks[p]["version"]
            prods[p] = rec
        commands[cmd] = {"products": prods, "only": only_of(prods)}

    flags = {}
    keys = set(flag_present) | {k for p in PRODUCTS for k in hidden_flags[p]}
    for key in sorted(keys, key=lambda k: (k[0], k[1])):
        cmd, name = key
        prods = {}
        for p in PRODUCTS:
            pres = flag_present.get(key, {}).get(p, {})
            vias = set(pres.values())
            rec = span(list(pres), versions[p],
                       via=(next(iter(vias)) if len(vias) == 1 else ("mixed" if vias else None)))
            meta = flag_meta.get(key, {}).get(p)
            if rec and meta:
                rec.update({
                    "kind": meta["kind"],
                    "takes_value": meta["takes_value"],
                    "placeholder": meta["placeholder"],
                    "aliases": meta["aliases"],
                    "deprecation_markers": meta["deprecation_markers"],
                    "section": meta["section"],
                    "desc": meta["desc"],
                })
            if key in hidden_flags[p]:
                rec = rec or {}
                rec["hidden_in_source"] = hidden_flags[p][key]
            prods[p] = rec
        flags[f"{cmd} {name}"] = {"command": cmd, "flag": name, "products": prods, "only": only_of(prods),
                                  "family": "view" if name in all_view else None}

    global_options = {}
    for name in sorted(glob_present):
        prods = {}
        for p in PRODUCTS:
            rec = span(glob_present[name].get(p, []), versions[p])
            if rec:
                g = glob_meta[name][p]
                rec.update({"kind": g["kind"], "placeholder": g["placeholder"], "desc": g["desc"]})
            prods[p] = rec
        global_options[name] = {"products": prods, "only": only_of(prods)}

    cdktn = []
    for cmd, flag, where in CDKTN_EMITTED:
        f = flags.get(f"{cmd} {flag}")
        row = {"command": cmd, "flag": flag, "emitted_by": where, "products": {}}
        for p in PRODUCTS:
            r = f["products"][p] if f else None
            row["products"][p] = {
                "first_seen": r.get("first_seen") if r else None,
                "via": r.get("via") if r else None,
                "all_swept_versions": bool(r) and r.get("count") == len(versions[p]),
            }
            note = CDKTN_SOURCE_VERIFIED.get((cmd, flag), {}).get(p)
            if note:
                row["products"][p]["source_verified_all_versions"] = note
        cdktn.append(row)

    def count_only(items, prod):
        return sum(1 for x in items.values() if x["only"] == prod)

    listed_flags = {k: v for k, v in flags.items()
                    if any(v["products"][p] and v["products"][p].get("count") for p in PRODUCTS)}
    summary = {
        "versions": {p: len(versions[p]) for p in PRODUCTS},
        "commands_total": len(commands),
        "commands_only": {p: count_only(commands, p) for p in PRODUCTS},
        "flags_total": len(listed_flags),
        "flags_only": {p: count_only(listed_flags, p) for p in PRODUCTS},
        "flags_only_excluding_view_family": {
            p: sum(1 for x in listed_flags.values() if x["only"] == p and not x["family"]) for p in PRODUCTS},
        "view_family": {p: sorted(view_family[p]) for p in PRODUCTS},
        "flags_hidden_in_source": {p: len(hidden_flags[p]) for p in PRODUCTS},
        "commands_hidden_in_source": {p: len(hidden_cmds[p]) for p in PRODUCTS},
        "global_options_only": {p: count_only(global_options, p) for p in PRODUCTS},
        "unparsed_lines": {p: {v: surfaces[p][v]["counts"]["unparsed_lines"] for v in versions[p]} for p in PRODUCTS},
    }

    out = {
        "generated_by": "scripts/cli-sweep.sh + scripts/build-cli-matrix.py",
        "selection": "first and last stable patch of every minor line; Terraform >= 1.5.7, OpenTofu >= 1.6.0",
        "versions": versions,
        "summary": summary,
        "global_options": global_options,
        "commands": commands,
        "flags": flags,
        "source_check": {p: {"version": c["version"], "commands": c["commands"],
                             "flags": {k: {kk: vv for kk, vv in e.items() if kk != "source"}
                                       for k, e in c["flags"].items()}}
                         for p, c in checks.items()},
        "cdktn_emitted": cdktn,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, sort_keys=False)
        f.write("\n")

    # console summary (used for PROPOSAL.md / README.md)
    print(f"wrote {OUT}")
    print(json.dumps({k: v for k, v in summary.items() if k != "unparsed_lines"}, indent=1))
    for p in PRODUCTS:
        print(f"\n== {p}-only commands:")
        for k, c in commands.items():
            if c["only"] == p:
                r = c["products"][p]
                print(f"  {k:28} first_seen={r.get('first_seen')} removed_in={r.get('removed_in')} hidden={r.get('hidden_in_source')}")
        print(f"== {p}-only flags (listed in help, excluding the view family):")
        for k, fl in listed_flags.items():
            if fl["only"] == p and not fl["family"]:
                r = fl["products"][p]
                print(f"  {k:44} first_seen={r.get('first_seen')} removed_in={r.get('removed_in')} via={r.get('via')}")
    print("\n== cdktn-emitted flags not available everywhere:")
    for row in cdktn:
        for p in PRODUCTS:
            r = row["products"][p]
            if not r["all_swept_versions"] and not r.get("source_verified_all_versions"):
                print(f"  {p:10} {row['command']} {row['flag']}: first_seen={r['first_seen']}")


if __name__ == "__main__":
    main()
