#!/usr/bin/env python3
"""Builds cli-matrix.json from data/cli-surface-*.json (help, "listed"),
data/cli-source-check-*.json (parser registrations, "accepted") and
data/cli-probe-*.json (binary probe; must agree with the source check, any
disagreement is printed with `!!` and kept in summary.probe).

Per (command, flag), for each product:
  listed         span of swept versions whose -help lists the flag:
                 first_seen ("listed since"), introduced_after (the swept
                 version before first_seen; the listing appeared in
                 (introduced_after, first_seen]), last_seen, removed_in, gaps,
                 count, via ("listed", "legacy-prose", "plan-reference" /
                 "apply-reference" for apply/destroy help pages that delegate
                 to `plan -help` / `apply -help`)
  accepted       the same span over the versions whose flag parser
                 registers the flag ("accepted since"). This, not `listed`,
                 is what product-only labels, "since" claims and any
                 allowlist are based on.
  cells          one status letter per swept version (see "semantics")
  takes_value    from the source registration kind when one exists
                 (takes_value_from: "source"), else from help
  hidden_in_source  accepted but not listed at the newest swept version
`only` is "terraform" / "opentofu" when the other
product neither lists nor accepts the flag at any swept version
(`only_listed`: by help listing alone). Commands carry the listed span plus
`registered` (commands.go). `allowlist_preview` is the shape a generated
cdktn allowlist would take (see PROPOSAL.md).

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
    checks = {p: {} for p in PRODUCTS}
    for path in glob.glob(os.path.join(DATA, "cli-source-check-*.json")):
        m = re.match(r"cli-source-check-(terraform|opentofu)-(\d+\.\d+\.\d+)\.json$", os.path.basename(path))
        if m:
            with open(path) as f:
                checks[m.group(1)][m.group(2)] = json.load(f)
    probes = {p: {} for p in PRODUCTS}
    for path in glob.glob(os.path.join(DATA, "cli-probe-*.json")):
        m = re.match(r"cli-probe-(terraform|opentofu)-(\d+\.\d+\.\d+)\.json$", os.path.basename(path))
        if m:
            with open(path) as f:
                probes[m.group(1)][m.group(2)] = json.load(f)
    return surfaces, checks, probes


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


def constraint(rec, versions):
    """Semver-ish range over swept versions for an `accepted` span."""
    if not rec:
        return None
    if rec["gaps"]:
        return "in " + ",".join(v for v in versions if versions.index(rec["first_seen"]) <= versions.index(v)
                                <= versions.index(rec["last_seen"]) and v not in rec["gaps"])
    lo = ">=" + rec["first_seen"] if rec["introduced_after"] else "*"
    hi = "<" + rec["removed_in"] if rec["removed_in"] else None
    return " ".join(x for x in (lo, hi) if x and x != "*") or "*"


def main():
    surfaces, checks, probes = load()
    versions = {p: sorted(surfaces[p], key=vkey) for p in PRODUCTS}
    for p in PRODUCTS:
        missing = [v for v in versions[p] if v not in checks[p]]
        if missing:
            print(f"!! {p}: no source check for {missing}; 'accepted' data is incomplete "
                  "(run scripts/cli-sweep.sh with the reference clones)")

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
                    via = "legacy-prose" if f.get("from") == "legacy-prose" else "listed"
                    flag_present.setdefault((cmd, f["name"]), {}).setdefault(p, {})[v] = via
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

    # source-accepted sets, per version (cli-source-check.py)
    flag_accepted = {}  # (cmd, flag) -> product -> {v: source record}
    cmd_registered = {}  # cmd -> product -> [versions]
    checked_cmds = {p: {} for p in PRODUCTS}  # product -> v -> set(cmds with a flag walk)
    for p in PRODUCTS:
        for v in versions[p]:
            chk = checks[p].get(v)
            if not chk:
                continue
            for cmd in chk["commands"]["source"]:
                cmd_registered.setdefault(cmd, {}).setdefault(p, []).append(v)
            checked_cmds[p][v] = set()
            for cmd, e in chk["flags"].items():
                if "error" in e:
                    continue
                checked_cmds[p][v].add(cmd)
                for r in e["source"]:
                    flag_accepted.setdefault((cmd, r["name"]), {}).setdefault(p, {})[v] = r

    # binary probe (cli-probe.py) vs source: every probed (cmd, flag) must
    # agree with the source-accepted set of the same version
    probe_disagree = []
    probe_count = {p: 0 for p in PRODUCTS}
    for p in PRODUCTS:
        for v, pr in probes[p].items():
            for cmd, res in pr["commands"].items():
                for name, verdict in res.items():
                    probe_count[p] += 1
                    src = v in flag_accepted.get((cmd, name), {}).get(p, {})
                    if verdict not in ("accepted", "rejected") or (verdict == "accepted") != src:
                        probe_disagree.append(f"{p} {v} {cmd} {name}: probe={verdict} source={'accepted' if src else 'rejected'}")
    for x in probe_disagree:
        print("!! probe/source disagreement: " + x)

    # "view" family: output/diagnostic flags registered by the products'
    # shared view-argument helpers (Terraform arguments.ParseView; OpenTofu
    # arguments.ParseView / BindView). OpenTofu 1.13 generates help from flag
    # definitions and lists these on (nearly) every command, which would
    # otherwise dominate the OpenTofu-only counts.
    view_family = {p: set() for p in PRODUCTS}
    for (cmd, name), prods in flag_accepted.items():
        for p, per_v in prods.items():
            if any(r["origin"].endswith((":BindView", ":ParseView")) for r in per_v.values()):
                view_family[p].add(name)
    all_view = set().union(*view_family.values())

    def only_of(prod_map):
        have = [p for p in PRODUCTS if prod_map.get(p)]
        return have[0] if len(have) == 1 else None

    commands = {}
    for cmd in sorted(set(cmd_present) | set(cmd_registered)):
        prods = {}
        for p in PRODUCTS:
            pres = cmd_present.get(cmd, {}).get(p, [])
            rec = span(pres, versions[p])
            if rec:
                rec.update({k: v for k, v in cmd_meta[cmd][p].items() if v})
            reg = cmd_registered.get(cmd, {}).get(p, [])
            if reg:
                rec = rec or {}
                rec["registered"] = span(reg, versions[p])
                hidden_v = [v for v in reg if v not in pres]
                if hidden_v:
                    rec["hidden_in_source_versions"] = hidden_v
                if versions[p][-1] in hidden_v:
                    rec["hidden_in_source"] = versions[p][-1]
            prods[p] = rec
        commands[cmd] = {"products": prods, "only": only_of(prods)}

    flags = {}
    keys = set(flag_present) | set(flag_accepted)
    hidden_newest = {p: 0 for p in PRODUCTS}
    help_not_source = []
    for key in sorted(keys, key=lambda k: (k[0], k[1])):
        cmd, name = key
        prods = {}
        for p in PRODUCTS:
            pres = flag_present.get(key, {}).get(p, {})
            acc = flag_accepted.get(key, {}).get(p, {})
            vias = set(pres.values())
            listed = span(list(pres), versions[p],
                          via=(next(iter(vias)) if len(vias) == 1 else ("mixed" if vias else None)))
            accepted = span(list(acc), versions[p])
            if not listed and not accepted:
                prods[p] = None
                continue
            # per-version cell codes, aligned with versions[p]:
            #   L listed (and accepted), R accepted via a help reference,
            #   H accepted but not listed, X listed but NOT accepted by the
            #   parser, - neither, ? listed, command not source-checked
            cells = []
            for v in versions[p]:
                in_help, in_src = v in pres, v in acc
                checked = cmd in checked_cmds[p].get(v, set())
                if in_help and (in_src or not checked):
                    cells.append(("R" if pres[v].endswith("reference") else "L") if checked else "?")
                elif in_help:
                    cells.append("X")
                    help_not_source.append((p, v, cmd, name))
                elif in_src:
                    cells.append("H")
                else:
                    cells.append("-")
            rec = {"listed": listed, "accepted": accepted, "cells": "".join(cells)}
            meta = flag_meta.get(key, {}).get(p)
            src_latest = acc[max(acc, key=vkey)] if acc else None
            if meta:
                rec.update({
                    "kind": meta["kind"],
                    "placeholder": meta["placeholder"],
                    "aliases": meta["aliases"],
                    "deprecation_markers": meta["deprecation_markers"],
                    "section": meta["section"],
                    "desc": meta["desc"],
                })
            if src_latest:
                rec["takes_value"] = src_latest["takes_value"]
                rec["takes_value_from"] = "source"
                rec["source_kind"] = src_latest["kind"]
                if meta and meta["takes_value"] != src_latest["takes_value"]:
                    # help shows no placeholder (`init -plugin-dir`) or a tag
                    rec["help_kind"] = meta["kind"]
                    rec["kind"] = "value" if src_latest["takes_value"] else "switch"
            elif meta:
                rec["takes_value"] = meta["takes_value"]
                rec["takes_value_from"] = "help"
            newest = versions[p][-1]
            if newest in acc and newest not in pres:
                r = acc[newest]
                rec["hidden_in_source"] = {"version": newest, "origin": r["origin"], "guards": r["guards"],
                                           "hidden_attr": r["hidden"]}
                hidden_newest[p] += 1
            prods[p] = rec
        flags[f"{cmd} {name}"] = {"command": cmd, "flag": name, "products": prods, "only": only_of(
            {p: (r and r.get("accepted")) or (r and r.get("listed")) for p, r in prods.items()}),
            "only_listed": only_of({p: r and r.get("listed") for p, r in prods.items()}),
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
            acc = (r or {}).get("accepted") or {}
            lst = (r or {}).get("listed") or {}
            row["products"][p] = {
                "first_seen": lst.get("first_seen"),
                "accepted_first_seen": acc.get("first_seen"),
                "via": lst.get("via"),
                "all_swept_versions": bool(acc) and acc.get("count") == len(versions[p]),
                "listed_all_swept_versions": bool(lst) and lst.get("count") == len(versions[p]),
            }
        cdktn.append(row)

    # allowlist preview: what a generated `terraform-cli-flags.generated.ts`
    # would contain (source-accepted sets; see PROPOSAL.md)
    allowlist = {}
    for k, fl in flags.items():
        entry = {}
        for p in PRODUCTS:
            r = fl["products"][p]
            if r and r.get("accepted"):
                entry[p] = constraint(r["accepted"], versions[p])
        if not entry:
            continue
        anyr = next(fl["products"][p] for p in PRODUCTS if fl["products"][p] and fl["products"][p].get("accepted"))
        entry["takesValue"] = anyr.get("takes_value")
        if all(not (fl["products"][p] and fl["products"][p].get("listed")) for p in PRODUCTS):
            entry["hidden"] = True
        allowlist.setdefault(fl["command"], {})[fl["flag"]] = entry

    def count_only(items, prod, field="only"):
        return sum(1 for x in items.values() if x[field] == prod)

    listed_flags = {k: v for k, v in flags.items()
                    if any(v["products"][p] and v["products"][p].get("listed") for p in PRODUCTS)}
    summary = {
        "versions": {p: len(versions[p]) for p in PRODUCTS},
        "source_checked_versions": {p: len(checks[p]) for p in PRODUCTS},
        "commands_total": len(commands),
        "commands_only": {p: count_only(commands, p) for p in PRODUCTS},
        "flags_total": len(flags),
        "flags_listed_total": len(listed_flags),
        "flags_only": {p: count_only(flags, p) for p in PRODUCTS},
        "flags_only_listed": {p: count_only(listed_flags, p, "only_listed") for p in PRODUCTS},
        "flags_only_excluding_view_family": {
            p: sum(1 for x in flags.values() if x["only"] == p and not x["family"]) for p in PRODUCTS},
        "view_family": {p: sorted(view_family[p]) for p in PRODUCTS},
        "flags_hidden_in_source": hidden_newest,
        "flags_never_listed": {p: sum(1 for x in flags.values() if x["products"][p]
                                      and x["products"][p].get("accepted") and not x["products"][p].get("listed"))
                               for p in PRODUCTS},
        "listed_but_not_accepted": sorted({f"{p} {c} {n}" for p, v, c, n in help_not_source}),
        "commands_hidden_in_source": {p: sum(1 for c in commands.values()
                                             if (c["products"][p] or {}).get("hidden_in_source")) for p in PRODUCTS},
        "global_options_only": {p: count_only(global_options, p) for p in PRODUCTS},
        "probe": {"versions": {p: len(probes[p]) for p in PRODUCTS}, "runs": probe_count,
                  "disagreements_with_source": probe_disagree},
        "unparsed_lines": {p: {v: surfaces[p][v]["counts"]["unparsed_lines"] for v in versions[p]} for p in PRODUCTS},
    }

    out = {
        "generated_by": "scripts/cli-sweep.sh + scripts/build-cli-matrix.py",
        "selection": "first and last stable patch of every minor line; Terraform >= 1.5.7, OpenTofu >= 1.6.0",
        "semantics": {
            "listed": "span of swept versions whose -help lists the flag (first_seen = 'listed since')",
            "accepted": "span of swept versions whose flag parser registers the flag "
                        "(cli-source-check.py; first_seen = 'accepted since'); use this for allowlists",
            "cells": "per swept version: L listed+accepted, R accepted via help reference, H accepted but "
                     "not listed, X listed but not accepted, ? listed (command not source-checked), - neither",
            "only": "product-only by accepted-or-listed; only_listed: by help listing alone",
        },
        "versions": versions,
        "summary": summary,
        "global_options": global_options,
        "commands": commands,
        "flags": flags,
        # newest version only; per-version detail is in data/cli-source-check-*.json
        # and in each flag's `cells`
        "source_check": {p: {"version": versions[p][-1],
                             "commands": {k: checks[p][versions[p][-1]]["commands"][k] for k in
                                          ("in_source_not_in_help", "in_help_not_in_source",
                                           "experimental_only", "hidden_set")},
                             "flags": {k: {kk: vv for kk, vv in e.items() if vv and kk in
                                           ("in_source_not_in_help", "in_help_not_in_source", "unresolved_calls")}
                                       for k, e in checks[p][versions[p][-1]]["flags"].items()
                                       if e.get("in_source_not_in_help") or e.get("in_help_not_in_source")
                                       or e.get("unresolved_calls")}}
                         for p in PRODUCTS if versions[p] and versions[p][-1] in checks[p]},
        "allowlist_preview": allowlist,
        "cdktn_emitted": cdktn,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, sort_keys=False)
        f.write("\n")

    # console summary (used for PROPOSAL.md / README.md)
    print(f"wrote {OUT}")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("unparsed_lines", "view_family")}, indent=1))
    for p in PRODUCTS:
        print(f"\n== {p}-only commands:")
        for k, c in commands.items():
            if c["only"] == p:
                r = c["products"][p]
                print(f"  {k:28} first_seen={r.get('first_seen')} removed_in={r.get('removed_in')} hidden={r.get('hidden_in_source')}")
        print(f"== {p}-only flags (accepted or listed, excluding the view family):")
        for k, fl in flags.items():
            if fl["only"] == p and not fl["family"]:
                r = fl["products"][p]
                acc = r.get("accepted") or {}
                print(f"  {k:44} accepted_since={acc.get('first_seen')} listed_since={(r.get('listed') or {}).get('first_seen')} "
                      f"removed_in={acc.get('removed_in')} via={(r.get('listed') or {}).get('via')}")
    print("\n== listed in help but not accepted by the parser:")
    for x in summary["listed_but_not_accepted"]:
        print("  " + x)
    print("\n== cdktn-emitted flags not accepted everywhere:")
    for row in cdktn:
        for p in PRODUCTS:
            r = row["products"][p]
            if not r["all_swept_versions"]:
                print(f"  {p:10} {row['command']} {row['flag']}: accepted_first_seen={r['accepted_first_seen']}")


if __name__ == "__main__":
    main()
