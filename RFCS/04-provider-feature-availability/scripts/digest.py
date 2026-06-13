#!/usr/bin/env python3
"""Reduces a full `providers schema -json` dump to a small committable digest.

Usage: digest.py <schema.json> <version.json> <product> <version>

The digest records, per provider: which top-level schema sections the CLI
emitted, the names inside each new-protocol section (functions, ephemeral
resources, identity, list resources, actions, state stores) and every
attribute carrying the `write_only` flag (searched recursively through
nested blocks/attributes).
"""
import json
import sys

# Large providers (aws) have hundreds of entries per feature family; cap the
# name lists so digests stay small enough to commit. Totals live in `counts`.
CAP = 50


def cap_list(names):
    names = sorted(names)
    if len(names) <= CAP:
        return names
    return names[:CAP] + [f"... (+{len(names) - CAP} more)"]


def short_name(fqpn):
    # registry.terraform.io/hashicorp/random and
    # registry.opentofu.org/hashicorp/random -> hashicorp/random
    parts = fqpn.split("/")
    return "/".join(parts[-2:]) if len(parts) >= 3 else fqpn


def walk_write_only(block, path=""):
    """Yields attribute paths flagged write_only anywhere in a schema block."""
    if not isinstance(block, dict):
        return
    for name, att in (block.get("attributes") or {}).items():
        p = f"{path}{name}"
        if isinstance(att, dict):
            if att.get("write_only"):
                yield p
            nested = att.get("nested_type")
            if nested:
                yield from walk_write_only(nested, p + ".")
    for name, bt in (block.get("block_types") or {}).items():
        yield from walk_write_only(bt.get("block") or {}, f"{path}{name}.")


def main():
    schema_path, version_path, product, version = sys.argv[1:5]
    with open(schema_path) as f:
        doc = json.load(f)
    try:
        with open(version_path) as f:
            version_doc = json.load(f)
    except (OSError, json.JSONDecodeError):
        version_doc = {}

    providers = {}
    for fqpn, p in (doc.get("provider_schemas") or {}).items():
        write_only = {}
        wo_attr_total = 0
        for rtype, rschema in (p.get("resource_schemas") or {}).items():
            paths = sorted(walk_write_only((rschema or {}).get("block") or {}))
            if paths:
                write_only[rtype] = paths
                wo_attr_total += len(paths)
        wo_resource_total = len(write_only)
        if wo_resource_total > CAP:
            write_only = dict(sorted(write_only.items())[:CAP])
            write_only[f"... (+{wo_resource_total - CAP} more resources)"] = []
        families = {
            "functions": (p.get("functions") or {}).keys(),
            "ephemeral_resources": (p.get("ephemeral_resource_schemas") or {}).keys(),
            "resource_identity": (p.get("resource_identity_schemas") or {}).keys(),
            "list_resources": (p.get("list_resource_schemas") or {}).keys(),
            "actions": (p.get("action_schemas") or {}).keys(),
            "state_stores": (p.get("state_store_schemas") or {}).keys(),
        }
        providers[short_name(fqpn)] = {
            "top_level_keys": sorted(p.keys()),
            "resource_count": len(p.get("resource_schemas") or {}),
            "data_source_count": len(p.get("data_source_schemas") or {}),
            **{k: cap_list(v) for k, v in families.items()},
            "write_only_attributes": write_only,
            "counts": {
                **{k: len(v) for k, v in families.items()},
                "write_only_resources": wo_resource_total,
                "write_only_attributes": wo_attr_total,
            },
        }

    digest = {
        "product": product,
        "version": version,
        "format_version": doc.get("format_version"),
        "provider_selections": {
            short_name(k): v
            for k, v in (version_doc.get("provider_selections") or {}).items()
        },
        "providers": dict(sorted(providers.items())),
    }
    json.dump(digest, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
