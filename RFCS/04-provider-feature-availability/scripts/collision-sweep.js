#!/usr/bin/env node
// Sweeps every prebuilt provider (the cdktn-repository-manager catalog, plus
// pending prebuilt requests) for the generation hard-fails introduced by
// cdktn-io/cdk-terrain PR #296: `provider-generator` now throws instead of
// silently overwriting a name collision when
//   - two provider-defined functions sanitize to the same generated method
//     name, or one sanitizes to a member `ProviderFunctionsEmitter` already
//     puts on every wrapper class ("constructor" / "providerLocalName"),
//   - two parameters of the same function sanitize to the same generated
//     parameter name, or
//   - a provider's own config schema has an attribute that generates the
//     property name "functions", colliding with the generated `functions`
//     getter on the provider class.
//
// This script does NOT reimplement those rules: it requires the *compiled*
// sanitizers straight out of `@cdktn/provider-generator`'s build output
// (`buildProviderFunctionsModel`, `assertNoFunctionsGetterCollision`) and the
// real `ResourceParser` used to turn a provider's config schema into the
// exact generated attribute names, then calls them per provider. A provider
// only shows up as a "collision" if the actual generator code would abort on
// it today.
//
// Usage:
//   CDKTN_REPO=/path/to/cdk-terrain/worktree \
//   SCHEMA_DIR=/path/to/raw/schemas \
//     node collision-sweep.js
//
// Inputs (see README.md "Re-running the sweep" for how to produce them):
//   SCHEMA_DIR/<name>.json        `terraform providers schema -json` output,
//                                 one file per provider (exactly one entry
//                                 under `provider_schemas` each).
//   VERSIONS_DIR/<name>.lock.hcl  the `.terraform.lock.hcl` written by the
//                                 `terraform init` that produced the schema
//                                 (or VERSIONS_DIR/<name>.json with a
//                                 `{"registry.terraform.io/...": "x.y.z"}`
//                                 override, for schemas reused from a cache
//                                 instead of freshly fetched - see aws).
//   MANIFEST_INPUT                {name: {source, constraint}} - the parsed
//                                 cdktn-repository-manager provider.json
//                                 catalog plus any pending prebuilt requests.
//
// Outputs (written to OUT_DIR, default ../data relative to this script):
//   collision-sweep-results.json   per-provider verdict + counts
//   collision-sweep-manifest.json  per-provider pinned {source, version}
"use strict";

const fs = require("fs");
const path = require("path");

const CDKTN_REPO =
  process.env.CDKTN_REPO ||
  "/Users/vincentsmet/cdktn/cdk-terrain/.claude/worktrees/pr-296";
const SCRIPT_DIR = __dirname;
const SCHEMA_DIR =
  process.env.SCHEMA_DIR || path.join(SCRIPT_DIR, "..", "data", "raw");
const VERSIONS_DIR = process.env.VERSIONS_DIR || SCHEMA_DIR;
const MANIFEST_INPUT =
  process.env.MANIFEST_INPUT ||
  path.join(SCRIPT_DIR, "..", "data", "collision-sweep-manifest-input.json");
const OUT_DIR = process.env.OUT_DIR || path.join(SCRIPT_DIR, "..", "data");

const GENERATOR_BUILD = path.join(
  CDKTN_REPO,
  "packages/@cdktn/provider-generator/build/get/generator",
);

const {
  buildProviderFunctionsModel,
  assertNoFunctionsGetterCollision,
} = require(path.join(GENERATOR_BUILD, "models/provider-function-model.js"));
const { ResourceParser } = require(
  path.join(GENERATOR_BUILD, "resource-parser.js"),
);

function loadJSON(p) {
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

// Resolves the exact provider version pinned by the `terraform init` that
// produced SCHEMA_DIR/<name>.json: prefers a `.terraform.lock.hcl` (real
// `terraform init` output), falls back to a hand-written
// VERSIONS_DIR/<name>.json override (used for schemas reused from an
// existing cache instead of being freshly fetched, e.g. aws).
function resolveVersion(name, fqpn) {
  const lockPath = path.join(VERSIONS_DIR, `${name}.lock.hcl`);
  if (fs.existsSync(lockPath)) {
    const text = fs.readFileSync(lockPath, "utf8");
    const providerBlockRe = new RegExp(
      `provider "${fqpn.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}" \\{([^}]*)\\}`,
    );
    const block = providerBlockRe.exec(text);
    if (block) {
      const versionMatch = /version\s*=\s*"([^"]+)"/.exec(block[1]);
      if (versionMatch) return { version: versionMatch[1], source: "terraform.lock.hcl" };
    }
  }
  const overridePath = path.join(VERSIONS_DIR, `${name}.json`);
  if (fs.existsSync(overridePath)) {
    const doc = loadJSON(overridePath);
    if (doc[fqpn]) {
      return {
        version: doc[fqpn],
        source: doc.note || "version override file",
      };
    }
  }
  return { version: null, source: "unresolved" };
}

function countParams(fn) {
  return fn.parameters.length + (fn.variadicParameter ? 1 : 0);
}

function sweepProvider(name, entry) {
  const schemaPath = path.join(SCHEMA_DIR, `${name}.json`);
  if (!fs.existsSync(schemaPath)) {
    return {
      name,
      source: entry.source,
      constraint: entry.constraint,
      verdict: "unfetched",
      error: `no schema file at ${schemaPath}`,
    };
  }

  let doc;
  try {
    doc = loadJSON(schemaPath);
  } catch (e) {
    return {
      name,
      source: entry.source,
      constraint: entry.constraint,
      verdict: "unfetched",
      error: `failed to parse schema JSON: ${e.message}`,
    };
  }

  const providerSchemas = doc.provider_schemas || {};
  const fqpns = Object.keys(providerSchemas);
  if (fqpns.length === 0) {
    return {
      name,
      source: entry.source,
      constraint: entry.constraint,
      verdict: "unfetched",
      error: "schema file has no provider_schemas entries",
    };
  }
  // Each schema was fetched from a single-provider `required_providers`
  // block, so there should be exactly one entry; if a provider ever pulls in
  // more (shouldn't happen for `terraform providers schema -json`), fall
  // back to matching the manifest's namespace/name suffix.
  const fqpn =
    fqpns.length === 1
      ? fqpns[0]
      : fqpns.find((k) => k.toLowerCase().endsWith(entry.source.toLowerCase())) ||
        fqpns[0];
  const provider = providerSchemas[fqpn];

  const { version, source: versionSource } = resolveVersion(name, fqpn);

  const functionNames = Object.keys(provider.functions || {});
  const functionCount = functionNames.length;

  const result = {
    name,
    fqpn,
    source: entry.source,
    constraint: entry.constraint,
    version,
    versionSource,
    functionCount,
    verdict: "clean",
  };

  // 1) buildProviderFunctionsModel: method-name collisions, reserved wrapper
  //    member collisions (constructor/providerLocalName), parameter-name
  //    collisions - all thrown from inside the real compiled sanitizer.
  let functionsModel;
  try {
    functionsModel = buildProviderFunctionsModel(name, provider.functions);
  } catch (e) {
    result.verdict = "collision";
    result.collisionStage = "buildProviderFunctionsModel";
    result.error = e.message;
    return result;
  }

  result.paramCount = functionsModel
    ? functionsModel.functions.reduce((sum, fn) => sum + countParams(fn), 0)
    : 0;

  // 2) assertNoFunctionsGetterCollision: only meaningful (and only run by the
  //    real generator) when the provider actually declares functions - a
  //    provider with none never emits the `functions` getter, so its own
  //    config schema can freely have an attribute named `functions`.
  if (functionsModel && provider.provider) {
    let providerResource;
    try {
      const parser = new ResourceParser();
      providerResource = parser.parse(
        fqpn,
        "provider",
        provider.provider,
        "provider",
        undefined,
      );
    } catch (e) {
      result.verdict = "unfetched";
      result.error = `ResourceParser failed to parse provider config schema: ${e.message}`;
      return result;
    }

    result.providerConfigAttributeCount = providerResource.attributes.length;

    try {
      assertNoFunctionsGetterCollision(
        name,
        providerResource.attributes.map((att) => att.name),
      );
    } catch (e) {
      result.verdict = "collision";
      result.collisionStage = "assertNoFunctionsGetterCollision";
      result.error = e.message;
      return result;
    }
  } else if (provider.provider) {
    // No functions declared: still record the attribute count for the
    // summary, but there is nothing to assert.
    try {
      const parser = new ResourceParser();
      const providerResource = parser.parse(
        fqpn,
        "provider",
        provider.provider,
        "provider",
        undefined,
      );
      result.providerConfigAttributeCount = providerResource.attributes.length;
    } catch (e) {
      // Non-fatal for providers with no functions: this path exists purely
      // for the summary's attribute count, and functions-getter collisions
      // are impossible without functions.
      result.providerConfigAttributeCountError = e.message;
    }
  }

  return result;
}

function main() {
  const manifestInput = loadJSON(MANIFEST_INPUT);
  const names = Object.keys(manifestInput).sort();

  const results = names.map((name) => sweepProvider(name, manifestInput[name]));

  const manifest = {};
  for (const r of results) {
    manifest[r.name] = {
      source: r.source,
      registry: "registry.terraform.io",
      fqpn: r.fqpn || null,
      constraint: r.constraint,
      version: r.version || null,
      versionSource: r.versionSource || null,
    };
  }

  const summary = {
    total: results.length,
    clean: results.filter((r) => r.verdict === "clean").length,
    collision: results.filter((r) => r.verdict === "collision").length,
    unfetched: results.filter((r) => r.verdict === "unfetched").length,
    totalFunctions: results.reduce((s, r) => s + (r.functionCount || 0), 0),
    totalParams: results.reduce((s, r) => s + (r.paramCount || 0), 0),
  };

  fs.mkdirSync(OUT_DIR, { recursive: true });
  fs.writeFileSync(
    path.join(OUT_DIR, "collision-sweep-results.json"),
    JSON.stringify(
      {
        generatedAt: new Date().toISOString(),
        generatorSource: GENERATOR_BUILD,
        summary,
        providers: results,
      },
      null,
      2,
    ) + "\n",
  );
  fs.writeFileSync(
    path.join(OUT_DIR, "collision-sweep-manifest.json"),
    JSON.stringify(manifest, null, 2) + "\n",
  );

  console.log(JSON.stringify(summary, null, 2));
  for (const r of results) {
    if (r.verdict !== "clean") {
      console.log(`${r.verdict.toUpperCase()} ${r.name}: ${r.error}`);
    }
  }
}

main();
