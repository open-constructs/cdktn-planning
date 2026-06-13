#!/usr/bin/env python3
"""Builds features-matrix.json from the per-version schema digests.

Two layers are merged:
  - observed: what the sweep actually saw in `providers schema -json` output
    against the fixture providers (data/schema-digest-*.json)
  - documented: source-verified facts that the fixture cannot observe — the
    protocol minor that added the RPCs, the CLI minor whose
    internal/command/jsonprovider struct gained the JSON key, and GA status.
    A feature can be documented but unobserved when no small fixture provider
    implements it (resource identity, list resources, state stores).

Citations for the documented layer live in PROPOSAL.md next to this tool.
"""
import json
import os
import re
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "features-matrix.json")

# digest field -> feature key
EVIDENCE_FIELDS = {
    "provider_functions": "functions",
    "ephemeral_resources": "ephemeral_resources",
    "write_only_attributes": "write_only_attributes",
    "resource_identity": "resource_identity",
    "list_resources": "list_resources",
    "actions": "actions",
    "state_stores": "state_stores",
}

# Source-verified overlay. "emitted_from" = first CLI minor whose
# `providers schema -json` serializer has the field (verified by diffing
# internal/command/jsonprovider across release tags of both products).
# None = the product does not support the feature at all (as of TF 1.15.x /
# OpenTofu 1.12.x, June 2026).
DOCUMENTED = {
    "provider_functions": {
        "title": "Provider-defined functions",
        "schema_key": "functions",
        "protocol": "5.5 / 6.5",
        "plugin_go": "v0.20.0 (2023-12)",
        "terraform": {"emitted_from": "1.8.0", "ga": "1.8.0"},
        "opentofu": {"emitted_from": "1.8.0", "ga": "1.7.0"},
        "notes": "OpenTofu shipped provider::ns::fn() language support in 1.7.0 "
        "(before Terraform 1.8), but `tofu providers schema -json` only emits "
        "the `functions` key from 1.8.0.",
    },
    "ephemeral_resources": {
        "title": "Ephemeral resources",
        "schema_key": "ephemeral_resource_schemas",
        "protocol": "5.7 / 6.7",
        "plugin_go": "v0.25.0 (2024-10)",
        "terraform": {"emitted_from": "1.10.0", "ga": "1.10.0"},
        "opentofu": {"emitted_from": "1.11.0", "ga": "1.11.0"},
        "notes": "Same Schema shape as resource_schemas. OpenTofu 1.12 fixed "
        "ephemeral resources leaking into the plan file.",
    },
    "write_only_attributes": {
        "title": "Write-only attributes",
        "schema_key": 'attribute flag "write_only"',
        "protocol": "5.8 / 6.8",
        "plugin_go": "v0.26.0 (2025-01)",
        "terraform": {"emitted_from": "1.11.0", "ga": "1.11.0"},
        "opentofu": {"emitted_from": "1.11.0", "ga": "1.11.0"},
        "notes": "Attribute-level boolean (omitempty) on managed resource "
        "schemas only; must be paired with optional or required. Conventionally "
        "named *_wo with a *_wo_version companion.",
    },
    "resource_identity": {
        "title": "Resource identity",
        "schema_key": "resource_identity_schemas",
        "protocol": "5.9 / 6.9",
        "plugin_go": "v0.27.0 (2025-05)",
        "terraform": {"emitted_from": "1.12.0", "ga": "1.12.0"},
        "opentofu": {"emitted_from": "1.12.0", "ga": "1.12.0"},
        "notes": "Top-level map (resource type -> identity schema), not nested "
        "in the resource schema. No HashiCorp utility provider implements it "
        "(June 2026) — observed via the aws fixture instead: aws 6.14.1 ships "
        "identity on 475 resources, emitted identically by both products.",
    },
    "list_resources": {
        "title": "List resources / query",
        "schema_key": "list_resource_schemas",
        "protocol": "5.10 / 6.10",
        "plugin_go": "v0.29.0 (2025-09)",
        "terraform": {"emitted_from": "1.14.0", "ga": "1.14.0"},
        "opentofu": None,
        "notes": "Terraform-only (`terraform query`, *.tfquery.hcl). OpenTofu: "
        "open feature request opentofu/opentofu#3787, no milestone. Requires "
        "resource identity; observed via the aws fixture (4 list resources in "
        "aws 6.14.1); no small provider ships one yet (tfcoremock v0.6.0 "
        "unreleased).",
    },
    "actions": {
        "title": "Actions",
        "schema_key": "action_schemas",
        "protocol": "5.10 / 6.10",
        "plugin_go": "v0.29.0 (2025-09)",
        "terraform": {"emitted_from": "1.14.0", "ga": "1.14.0"},
        "opentofu": None,
        "notes": "Terraform-only `action` blocks (lifecycle-triggered or "
        "`terraform apply -invoke`). Fixture evidence: hashicorp/local >= 2.6.0 "
        "ships action local_command; aws 6.14.1 ships 5 actions (incl. "
        "aws_lambda_invoke, aws_cloudfront_create_invalidation).",
    },
    "state_stores": {
        "title": "Pluggable state stores",
        "schema_key": "state_store_schemas",
        "protocol": "6.11 only",
        "plugin_go": "v0.30.0 (2026-02)",
        "terraform": {"emitted_from": "1.15.0", "ga": None},
        "opentofu": None,
        "notes": "Protocol 6 only (no tfplugin5 counterpart). Terraform CLI "
        "serializer has the key from 1.15.0 but `state_store` is not GA in core "
        "through 1.15.x. OpenTofu has no equivalent (its differentiator is "
        "built-in state encryption, OpenTofu >= 1.7).",
    },
}

PRODUCTS = ("terraform", "opentofu")


def vkey(v):
    return tuple(int(x) for x in v.split("."))


def has_evidence(provider_digest, field):
    value = provider_digest.get(field)
    return bool(value)


def main():
    # (product, version) -> merged digest; fixtures (core + aws) sweeping the
    # same CLI version contribute providers to one cell. The version axis comes
    # from the core fixture, which covers every column; the aws fixture only
    # exists from 1.12 (see sweep.sh).
    digests = {}
    versions = defaultdict(list)
    for fname in sorted(os.listdir(DATA)):
        m = re.fullmatch(
            r"schema-digest-(?:([a-z0-9]+)-)?(terraform|opentofu)-(\d+\.\d+\.\d+)\.json",
            fname,
        )
        if not m:
            continue
        fixture, product, version = m.group(1) or "core", m.group(2), m.group(3)
        with open(os.path.join(DATA, fname)) as f:
            doc = json.load(f)
        cell = digests.setdefault(
            (product, version),
            {"providers": {}, "provider_selections": {}},
        )
        cell["providers"].update(doc.get("providers") or {})
        cell["provider_selections"].update(doc.get("provider_selections") or {})
        if fixture == "core":
            versions[product].append(version)
    for p in versions:
        versions[p].sort(key=vkey)

    features = {}
    for fkey, field in EVIDENCE_FIELDS.items():
        doc = DOCUMENTED[fkey]
        entry = {
            "title": doc["title"],
            "schema_key": doc["schema_key"],
            "protocol": doc["protocol"],
            "plugin_go": doc["plugin_go"],
            "notes": doc["notes"],
            "products": {},
            "evidence": {},
        }
        for product in PRODUCTS:
            doc_p = doc.get(product)
            observed = [
                v
                for v in versions[product]
                if any(
                    has_evidence(pd, field)
                    for pd in digests[(product, v)]["providers"].values()
                )
            ]
            entry["products"][product] = {
                "documented_emitted_from": doc_p["emitted_from"] if doc_p else None,
                "documented_ga": (doc_p or {}).get("ga"),
                "observed_introduced": observed[0] if observed else None,
                "observed_versions": observed,
            }
            if versions[product]:
                latest = versions[product][-1]
                ev = {}
                for pname, pd in digests[(product, latest)]["providers"].items():
                    if has_evidence(pd, field):
                        ev[pname] = pd[field]
                if ev:
                    entry["evidence"][product] = {"version": latest, "providers": ev}
        features[fkey] = entry

    # fixture provider resolution from the newest digest of each product
    fixture = {}
    for product in PRODUCTS:
        if versions[product]:
            latest = versions[product][-1]
            fixture[product] = digests[(product, latest)].get(
                "provider_selections", {}
            )

    out = {
        "generated_note": "provider-protocol feature availability from "
        "`providers schema -json` sweeps (observed) merged with source-verified "
        "CLI serializer history (documented); see PROPOSAL.md for citations",
        "versions": {p: versions[p] for p in PRODUCTS},
        "fixture_provider_selections": fixture,
        "features": features,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
        f.write("\n")

    # console summary
    for p in PRODUCTS:
        vs = versions[p]
        rng = f"{vs[0]}..{vs[-1]}" if vs else "none"
        print(f"{p}: {len(vs)} versions swept ({rng})")
    print()
    for fkey, e in features.items():
        cells = []
        for p in PRODUCTS:
            pr = e["products"][p]
            doc = pr["documented_emitted_from"] or "—"
            obs = pr["observed_introduced"] or "unobserved"
            cells.append(f"{p}: doc {doc} / obs {obs}")
        print(f"{fkey:24s} {' | '.join(cells)}")
        # sanity: observed must never precede documented
        for p in PRODUCTS:
            pr = e["products"][p]
            if pr["observed_introduced"] and pr["documented_emitted_from"]:
                if vkey(pr["observed_introduced"]) < vkey(
                    pr["documented_emitted_from"]
                ):
                    print(
                        f"  !! {p}: observed {pr['observed_introduced']} BEFORE "
                        f"documented {pr['documented_emitted_from']} — overlay is wrong"
                    )
            if pr["observed_introduced"] and not pr["documented_emitted_from"]:
                print(f"  !! {p}: observed but documented as unsupported")


if __name__ == "__main__":
    main()
