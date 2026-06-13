# Research: Concrete local recipe for the bundle E2E validation

**Date**: 2026-06-10
**Context**: The v10-e2e note ([`2026-06-08-v10-e2e-validation.md`](2026-06-08-v10-e2e-validation.md)) defined a layered strategy and named "L3 bundle E2E" as the high-confidence delivery proof, but left it as "heavier, needs a special build." This spike makes L3 **concrete and runnable locally** — a copy-pasteable recipe a developer (or CI job) can execute to prove the real shipped bundle constructs, bakes, and **flushes** telemetry on exit, with no Sentry SaaS dependency.
**Time-box**: 40 minutes

## Question

What are the exact, runnable steps to validate — against the real esbuild bundle, locally — that (a) usage metrics are delivered and flushed before the short-lived CLI exits, (b) error reporting still delivers, and (c) nothing egresses to HashiCorp?

## Findings

### Finding 1: The local bundle is directly runnable — no Verdaccio/dist dance needed (CONFIDENCE: high)

The CI integration suite (`test/run-against-dist` + Verdaccio) is overkill for a Sentry-validation recipe. Building just the CLI bundle is enough:

- `cd packages/cdktn-cli && yarn build` → `tsc --noEmit` + `postbuild: node build.js` (the compiled `build.ts`) → emits `packages/cdktn-cli/bundle/bin/cdktn` (`package.json` scripts; `bin.cdktn = bundle/bin/cdktn`).
- That binary is runnable directly: `./packages/cdktn-cli/bundle/bin/cdktn <cmd>` (matches the in-bundle tests, which `execa(path.resolve(__dirname,"../../../bundle/bin/cdktn"), …)` — `packages/cdktn-cli/src/test/cmds/init.test.ts:8`).
- **DSN bake**: `build.ts:96-97` esbuild-`define`s `process.env.SENTRY_DSN` from the **build-time** env. So building with a local-sink DSN bakes it into the bundle.

### Finding 2: A dependency-free SUCCESS trigger exists — `cdktn convert` (CONFIDENCE: high)

The load-bearing new behavior is the **success-path bounded flush** (today only the error path flushes, `cdktn.ts:184`). To exercise it we need a command that (i) succeeds, (ii) inits Sentry, (iii) emits a usage metric, (iv) needs no provider `dist`.

- `cdktn convert` reads HCL from **stdin**, calls `initializErrorReporting` (handlers), and emits `sendTelemetry("convert", …)` on success (`handlers.ts:169`). It needs `hcl2json` (bundled) but **no provider dist**. Deterministic.
- → `echo '<hcl>' | cdktn convert --language typescript` is the minimal success trigger. Post-feature it emits a `cli.command.invoked` metric whose delivery depends entirely on the new success-path flush. **If the sink stays empty, the bounded flush is missing/broken** — exactly the regression we must catch.

A complementary **ERROR** trigger needs no dist either: `cdktn synth --app "node -e 'process.exit(1)'"` → synth fails → `synthErrorTelemetry()` emits `cli.command.error` (`synth-stack.ts:293-295`) AND the error propagates to the existing `Sentry.close(4000)` flush (`cdktn.ts:184`). Proves bundle/DSN/sink plumbing + error delivery even on the *current* v7 bundle (good for de-risking the recipe before the v10 work lands).

### Finding 3: A ~30-line Node server is a complete local Sentry sink (CONFIDENCE: high)

Sentry DSN `http://<key>@<host>:<port>/<projectId>` → the SDK POSTs envelopes to `http://<host>:<port>/api/<projectId>/envelope/` (older plain events may use `/store/`). The body is newline-delimited JSON: envelope header, then `(itemHeader, itemPayload)` pairs; the **item header `type`** distinguishes `event` / `transaction` / `trace_metric` / `log`. A sink only needs to 200 every POST and record item types.

### Finding 4: Consent + env must be set or telemetry silently no-ops (CONFIDENCE: high)

For the bundle to init Sentry and emit, all must hold at run time: baked DSN present (Finding 1); consent true (`sendUsageTelemetry`/`sendCrashReports` in `cdktf.json`, or pass `--enable-crash-reporting=true` where supported); **`CHECKPOINT_DISABLE` unset** (CI sets it — must clear for the metric/egress assertions to be meaningful); not silently in CI consent-skip. Post-v10 also confirm `enableMetrics !== false` in `Sentry.init`.

## The recipe (copy-pasteable)

### 1. Local Sentry sink — `tools/sentry-sink.mjs`
```js
// Minimal Sentry envelope recorder. Usage: node tools/sentry-sink.mjs [port]
import http from "node:http";
const port = Number(process.argv[2] || 9999);
const items = [];                       // collected item headers (with names for metrics)
const server = http.createServer((req, res) => {
  let body = "";
  req.on("data", (c) => (body += c));
  req.on("end", () => {
    if (req.url.includes("/envelope/") || req.url.includes("/store/")) {
      const lines = body.split("\n").filter(Boolean);
      // line 0 = envelope header; then alternating itemHeader / itemPayload
      for (let i = 1; i < lines.length; i += 2) {
        try {
          const h = JSON.parse(lines[i]);
          const p = lines[i + 1] ? JSON.parse(lines[i + 1]) : {};
          items.push({ type: h.type, name: p.name, payload: p });
          console.log("ENVELOPE ITEM:", h.type, p.name ?? "");
        } catch {}
      }
    }
    res.writeHead(200, { "content-type": "application/json" });
    res.end("{}");
  });
});
server.listen(port, () => console.log(`sentry-sink on :${port}`));
process.on("SIGUSR2", () => { console.log("SUMMARY", JSON.stringify(items)); }); // dump on demand
```

### 2. Build the bundle with the local-sink DSN
```bash
# from repo root; bakes process.env.SENTRY_DSN into bundle/bin/cdktn
( cd packages/cdktn-cli && SENTRY_DSN="http://localkey@localhost:9999/1" yarn build )
```

### 3. Start the sink (separate shell)
```bash
node tools/sentry-sink.mjs 9999
```

### 4. Prepare a telemetry-enabled workdir, CHECKPOINT_DISABLE cleared
```bash
WORK=$(mktemp -d); cd "$WORK"
printf '{ "language": "typescript", "sendCrashReports": true, "sendUsageTelemetry": true }' > cdktf.json
unset CHECKPOINT_DISABLE
CDKTN=/home/vincent/cdktn/cdk-terrain/packages/cdktn-cli/bundle/bin/cdktn
```

### 5a. SUCCESS trigger — proves the NEW bounded flush (post-feature)
```bash
echo 'resource "null_resource" "x" {}' | "$CDKTN" convert --language typescript
# EXPECT in sink: an item  type=trace_metric  name=cli.command.invoked  (attributes.command=convert)
# If sink is EMPTY -> success-path flush is missing/broken (the regression to catch).
```

### 5b. ERROR trigger — proves DSN bake + sink + flush plumbing (works on current bundle too)
```bash
"$CDKTN" synth --app "node -e 'process.exit(1)'" || true
# EXPECT in sink: type=event (the error) AND (post-feature) type=trace_metric name=cli.command.error
```

### 6. No-HashiCorp-egress check (local)
```bash
# (a) artifact check: the shipped bundle must not reference the host post-feature
grep -c "checkpoint-api.hashicorp.com" packages/cdktn-cli/bundle/bin/cdktn   # expect 0 (copyright headers ok)
# (b) optional runtime catch-all: route egress through a recording proxy and assert
#     no connection to checkpoint-api.hashicorp.com  (HTTPS_PROXY=http://localhost:PORT cdktn …)
```

## Decisions

- **D1**: Ship the recipe as a **standalone script** (`tools/validate-sentry-e2e.sh` + `tools/sentry-sink.mjs`) for local use — no Verdaccio/dist dependency, fast, and usable by a human today against the current bundle. This is the "well-defined local validation recipe" asked for.
- **D2**: The **success trigger is `cdktn convert` from stdin** (Finding 2) — dependency-free and the only trigger that isolates the *new success-path flush* (the error trigger flushes via the pre-existing `Sentry.close`). The error trigger (`synth --app 'node -e process.exit(1)'`) is the complementary plumbing/de-risk check.
- **D3**: The **sink is the delivery oracle** (item `type=trace_metric` / `event`); reuse the same `sentry-sink.mjs` in (a) the local script and (b) an optional CI jest test that spawns `bundle/bin/cdktn` (gate behind `describeIfDistExists`/bundle-exists, build with the local DSN in a CI step). Do NOT duplicate sink logic.
- **D4**: **No-egress is enforced primarily by the L1/L2 in-process tests + an artifact grep** (Finding/recipe §6); the bundle E2E's unique value is *delivery + real-exit flush*, not egress interception (nock can't see the child; a recording proxy is optional heavy tooling).
- **D5**: Recipe is **runnable today** against the v7 bundle via the error trigger — so it can be landed and de-risked in Phase A, before the metric work, then extended with the success-metric assertion in Phase C.

## Recommendations

1. Add `tools/sentry-sink.mjs` + `tools/validate-sentry-e2e.sh` (steps 2-6) in Phase A; wire the success-metric assertion (5a) in Phase C.
2. Fold this recipe into `quickstart.md` Journey 6 (replace the abstract "build with local-sink DSN" line with the concrete commands) and reference it from `contracts/telemetry-contract.md` C5.
3. CI: a gated jest test that builds the bundle with `SENTRY_DSN=http://k@localhost:PORT/1`, starts the sink in-process, spawns `bundle/bin/cdktn convert` with `CHECKPOINT_DISABLE` unset, and asserts a `trace_metric` envelope item + that the process exited 0 (flush didn't hang).
4. Open items to confirm during implementation: exact envelope endpoint the v10 transport uses for metrics (`/envelope/` expected); the chosen flush timeout; whether `convert` honors `sendUsageTelemetry` outside a full project dir (else run inside the temp workdir with cdktf.json as in step 4).

## References

- Build/bake: `packages/cdktn-cli/build.ts:96-97`; scripts in `packages/cdktn-cli/package.json`; run path `packages/cdktn-cli/src/test/cmds/init.test.ts:8`
- Triggers: `handlers.ts:169` (convert telemetry); `synth-stack.ts:272-295` (synth/synthError telemetry); exit flush `packages/cdktn-cli/src/bin/cdktn.ts:184`
- Consent/env: `error-reporting.ts:23-32,77` (`sendCrashReports`/`SENTRY_DSN`); `environment.ts:14` / `checkpoint.ts:155` (`CHECKPOINT_DISABLE`)
- Sentry transport/envelope + flush: https://docs.sentry.io/platforms/javascript/configuration/transports/ , https://develop.sentry.dev/sdk/telemetry/metrics/ , https://docs.sentry.io/platforms/node/configuration/draining/
- Prior: [`2026-06-08-v10-e2e-validation.md`](2026-06-08-v10-e2e-validation.md), [`../quickstart.md`](../quickstart.md), [`../contracts/telemetry-contract.md`](../contracts/telemetry-contract.md)
