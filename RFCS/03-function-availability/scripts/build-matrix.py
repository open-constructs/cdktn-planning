#!/usr/bin/env python3
"""Builds functions-matrix.json from per-version `metadata functions -json` dumps.

For each function we compute, per product (terraform / opentofu):
  - introduced: first stable version where the function appears
  - removed: first version after which it disappears (None if still present)
  - versions: the exact set of versions where it is present (as ranges)
"""
import json
import os
import re
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "functions-matrix.json")


def vkey(v):
    return tuple(int(x) for x in v.split("."))


def main():
    # product -> sorted version list
    versions = defaultdict(list)
    # product -> version -> set of function names
    funcs = defaultdict(dict)
    # function name -> product -> (version key, signature) of numerically
    # newest version seen for that product
    product_signatures = defaultdict(dict)

    for fname in sorted(os.listdir(DATA)):
        m = re.fullmatch(r"functions-(terraform|opentofu)-(\d+\.\d+\.\d+)\.json", fname)
        if not m:
            continue
        product, version = m.group(1), m.group(2)
        with open(os.path.join(DATA, fname)) as f:
            doc = json.load(f)
        sigs = doc.get("function_signatures", {})
        versions[product].append(version)
        # `core::` aliases (terraform >= 1.8, opentofu >= 1.7) mirror every
        # builtin 1:1 — fold them out, they add rows without signal
        funcs[product][version] = {k for k in sigs.keys() if "::" not in k}
        for name, sig in sigs.items():
            if "::" in name:
                continue
            known = product_signatures[name].get(product)
            if known is None or vkey(version) > known[0]:
                product_signatures[name][product] = (vkey(version), sig)

    for p in versions:
        versions[p].sort(key=vkey)

    # canonical signature: terraform's newest wording wins when the function
    # exists in terraform, otherwise opentofu's (update-function-matrix.ts
    # follows the same precedence)
    signatures = {
        name: (by_product.get("terraform") or by_product["opentofu"])[1]
        for name, by_product in product_signatures.items()
    }

    all_names = sorted({n for p in funcs for v in funcs[p] for n in funcs[p][v]})

    matrix = {}
    for name in all_names:
        entry = {"signature": {
            "description": signatures[name].get("description", ""),
            "return_type": signatures[name].get("return_type"),
            "parameters": signatures[name].get("parameters", []),
            "variadic_parameter": signatures[name].get("variadic_parameter"),
        }, "products": {}}
        for product in ("terraform", "opentofu"):
            vs = versions[product]
            present = [v for v in vs if name in funcs[product][v]]
            if not present:
                entry["products"][product] = None
                continue
            introduced = present[0]
            # find gaps / removal
            present_set = set(present)
            after_intro = [v for v in vs if vkey(v) >= vkey(introduced)]
            missing_after = [v for v in after_intro if v not in present_set]
            last = present[-1]
            removed = None
            if last != vs[-1]:
                # disappeared: first version after `last` where it's absent
                idx = vs.index(last)
                removed = vs[idx + 1]
            entry["products"][product] = {
                "introduced": introduced,
                "removed": removed,
                "gaps": missing_after if missing_after and removed is None else (
                    [v for v in missing_after if vkey(v) < vkey(last)] if removed else missing_after
                ),
                "count": len(present),
            }
        matrix[name] = entry

    out = {
        "generated_note": "function availability matrix from `metadata functions -json` sweeps",
        "versions": {p: versions[p] for p in ("terraform", "opentofu")},
        "functions": matrix,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
        f.write("\n")

    # quick console summary
    tf_v, tofu_v = versions["terraform"], versions["opentofu"]
    print(f"terraform versions: {len(tf_v)} ({tf_v[0]}..{tf_v[-1]})")
    print(f"opentofu versions: {len(tofu_v)} ({tofu_v[0]}..{tofu_v[-1]})")
    print(f"total functions: {len(all_names)}")

    base_tf = {n for n, e in matrix.items() if e["products"]["terraform"] and e["products"]["terraform"]["introduced"] == tf_v[0]}
    base_tofu = {n for n, e in matrix.items() if e["products"]["opentofu"] and e["products"]["opentofu"]["introduced"] == tofu_v[0]}
    print(f"baseline terraform {tf_v[0]}: {len(base_tf)}")
    print(f"baseline opentofu {tofu_v[0]}: {len(base_tofu)}")
    print("\n-- introduced later (terraform) --")
    for n, e in sorted(matrix.items()):
        p = e["products"]["terraform"]
        if p and p["introduced"] != tf_v[0]:
            print(f"  {n}: {p['introduced']}" + (f" (removed {p['removed']})" if p["removed"] else ""))
    print("\n-- introduced later (opentofu) --")
    for n, e in sorted(matrix.items()):
        p = e["products"]["opentofu"]
        if p and p["introduced"] != tofu_v[0]:
            print(f"  {n}: {p['introduced']}" + (f" (removed {p['removed']})" if p["removed"] else ""))
    print("\n-- product-exclusive --")
    for n, e in sorted(matrix.items()):
        tf, tofu = e["products"]["terraform"], e["products"]["opentofu"]
        if tf and not tofu:
            print(f"  {n}: terraform only")
        if tofu and not tf:
            print(f"  {n}: opentofu only")
    print("\n-- removed --")
    for n, e in sorted(matrix.items()):
        for prod in ("terraform", "opentofu"):
            p = e["products"][prod]
            if p and p["removed"]:
                print(f"  {n}: {prod} removed at {p['removed']}")
    print("\n-- gaps (non-contiguous availability) --")
    for n, e in sorted(matrix.items()):
        for prod in ("terraform", "opentofu"):
            p = e["products"][prod]
            if p and p["gaps"]:
                print(f"  {n}: {prod} gaps {p['gaps']}")


if __name__ == "__main__":
    main()
