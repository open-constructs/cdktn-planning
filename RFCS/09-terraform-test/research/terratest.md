# Terratest → CDKTN translation research (for RFC-06 "long-term goal" section)

Sources: local clone `/Users/vincentsmet/cdktn/ref-terratest` (gruntwork-io/terratest, `main` @ `1b9d7ce`, 2026-09-19 — note this is the **v2 multi-module tree**, package paths `modules/<name>/v2`), `/Users/vincentsmet/cdktn/cdk-terrain`, and the real-world consumer `/Users/vincentsmet/tcons/base/integ`.

⚠️ **Repo-layout caveat up front**: the checked-out `main` is v2. Package `modules/test-structure` was renamed `modules/teststructure`, `http-helper`→`httphelper`, `dns-helper`→`dnshelper`, and `files`/`logger`/`random`/`retry`/`shell`/`testing` moved under `modules/core/`. **v2 also removed the non-`Context` variants** — `terraform.InitAndApply` no longer exists, only `terraform.InitAndApplyContext(t, ctx, opts)`. The RFC should cite v1 names (what people use today) and note the v2 rename.

---

## 1. Stages — `modules/teststructure`

**Files**: `/Users/vincentsmet/cdktn/ref-terratest/modules/teststructure/teststructure.go`, `.../save_test_data.go`, and the type-agnostic primitives in `/Users/vincentsmet/cdktn/ref-terratest/modules/core/teststate/teststate.go`.

### The stage runner
```go
const SkipStageEnvVarPrefix = "SKIP_"                       // teststructure.go:32
func RunTestStage(t testing.TestingT, stageName string, stage func())  // teststructure.go:35
func SkipStageEnvVarSet() bool                                          // teststructure.go:47
```
`RunTestStage` is ~8 lines: if `os.Getenv("SKIP_"+stageName) == ""` run the closure, else log and skip. That is the entire mechanism. Teardown stages are registered with `defer teststructure.RunTestStage(t, "cleanup_terraform", ...)`.

### The cross-stage store — this is the load-bearing part
`modules/core/teststate/teststate.go`:
```go
const DirName = ".test-data"                                       // teststate.go:29
func FormatPath(testFolder, filename string) string                // filepath.Join(testFolder, ".test-data", filename)
func Save(t, path string, overwrite bool, value any)               // json.Marshal → os.WriteFile(path, bytes, 0o600)
func SaveRedacted(t, path, overwrite, value)                       // same, but never logs the marshalled JSON (secrets)
func Load(t, path string, value any)                               // os.ReadFile → json.Unmarshal into a pointer
func IsPresent(t, path) bool                                       // exists AND non-empty-JSON
func IsEmptyJSON(t, bytes) bool                                    // "", null, false, 0, "", [], {} all count as empty
func Cleanup / CleanupFolder / CleanupFolderE
```
Wrappers in `modules/teststructure/save_test_data.go`:
`SaveTerraformOptions` / `SaveTerraformOptionsIfNotPresent` / `LoadTerraformOptions` (file `TerraformOptions.json`), `SaveString`/`LoadString`, `SaveInt`/`LoadInt`, `SaveArtifactID`/`LoadArtifactID` (v1: `SaveAmiId`), `SaveTestData`/`LoadTestData`/`IsTestDataPresent`, `FormatTestDataPath`, `CleanupTestData`, `CleanupTestDataFolder(E)`.
Module-owned wrappers follow the same shape and live beside the module so `teststructure` doesn't have to import every cloud: `aws.SaveEc2KeyPair`/`aws.LoadEc2KeyPair` (`modules/aws/save_test_data.go`), `k8s.SaveKubectlOptions`, `packer.SavePackerOptions`.

**Mechanically**: everything is plain JSON on disk under `<terraformDir>/.test-data/<Name>.json`. Nothing is in-memory, so a *separate* `go test` invocation picks the data straight back up. That is what makes `SKIP_deploy_terraform=true go test -run TestX` work — the validate stage `LoadTerraformOptions` from the file the previous process wrote. Secrets get `0o600` + `SaveRedacted`.

### Temp-folder copy, and its interaction with stages
```go
func CopyTerraformFolderToTemp(t, rootFolder, terraformModuleFolder) string   // teststructure.go:82
func CopyTerraformFolderToDest(t, rootFolder, terraformModuleFolder, destRootFolder) string
```
Copies the whole *root* (to keep relative paths working) to `os.TempDir()/<cleaned t.Name()>-<random>` and returns the path to the module inside it. **Crucially (teststructure.go:120): if any `SKIP_*` env var is set it returns the original folder instead**, precisely so `.test-data` and `.terraform`/state survive between processes. Temp-copy and stage-caching are mutually exclusive by design.

### Canonical example
`/Users/vincentsmet/cdktn/ref-terratest/test/terraform_packer_example_test.go` (`TestTerraformPackerExample`, lines 22-64) — stages `build_ami`, `deploy_terraform`, `validate`, `logs`, `cleanup_terraform`, `cleanup_ami`; `SKIP_build_ami=true go test -v -run TestTerraformPackerExample`. Docs: `docs/_docs/02_testing-best-practices/iterating-locally-using-test-stages.md`.

---

## 2. Terraform helpers — `modules/terraform`

`/Users/vincentsmet/cdktn/ref-terratest/modules/terraform/options.go` — `Options` fields (~35): `TerraformDir`, `TerraformBinary`, `Vars map[string]any`, `VarFiles []string`, `MixedVars []Var` (ordered `-var`/`-var-file` mix), `EnvVars`, `BackendConfig`, `PluginDir`, `PlanFilePath`, `Targets`, `LockTimeout`, `Lock`, `Parallelism`, `NoColor`, `NoStderr`, `OutputMaxLineSize`, `MigrateState`, `Reconfigure`, `Upgrade`, `SetVarsAfterVarFiles`, `ExtraArgs` (per-subcommand `[]string`), `Stdin`, `Logger`, `SshAgent`, `WarningsAsErrors`, `RetryableTerraformErrors`, `MaxRetries`, `TimeBetweenRetries`. `Clone()` deep-copies (via `jinzhu/copier` + manual map copies) — Logger/SshAgent excepted.

**Binary selection** (`modules/terraform/cmd.go:37-56`):
```go
const TofuDefaultPath = "tofu"; const TerraformDefaultPath = "terraform"
var DefaultExecutable = defaultTerraformExecutable()   // probes `terraform -version`; falls back to "tofu"
func GetCommonOptions(options *Options, args ...string) (*Options, []string) {
    if options.TerraformBinary == "" { options.TerraformBinary = DefaultExecutable }
    if options.Parallelism > 0 && slices.Contains(commandsWithParallelism /* plan,apply,destroy */, args[0]) {
        args = append(args, fmt.Sprintf("--parallelism=%d", options.Parallelism)) }
    if options.SshAgent != nil { options.EnvVars["SSH_AUTH_SOCK"] = options.SshAgent.SocketFile() }
    ...
}
```
Terragrunt is a separate module (`modules/terragrunt`, ~145 exported funcs) rather than a binary flag.

**Retry on known-flaky errors** — `modules/terraform/cmd.go:130-160` + `modules/core/retry/retry.go:153`:
`RunTerraformCommandContextE` wraps every invocation in `retry.DoWithRetryableErrorsContextE(t, ctx, desc, options.RetryableTerraformErrors, options.MaxRetries, options.TimeBetweenRetries, fn)`. The map is `regex → human message`; the regex is matched against **both stdout/stderr and `err.Error()`**. A non-match is wrapped in `retry.FatalError` and aborts immediately. `options.go:20-43` defines `DefaultRetryableTerraformErrors` (11 patterns): `connection reset by peer`, `transport is closing`, `unable to verify signature|checksum`, `no provider exists with the given name`, `registry service is unreachable`, `Error installing provider`, `Failed to query available provider packages`, `timeout while waiting for plugin to start`, `timed out waiting for server handshake`, `could not query provider registry for`, and `Provider produced inconsistent result after apply`. `terraform.WithDefaultRetryableErrors(t, opts)` clones and merges them + sets `MaxRetries=3`, `TimeBetweenRetries=5s`.

**Commands** (v1 names; v2 appends `Context`): `Init`, `InitAndApply`, `Apply`, `ApplyAndIdempotent`, `InitAndApplyAndIdempotent` (apply then plan and fail if changes — `apply.go:56`), `Plan`, `InitAndPlan`, `InitAndPlanAndShow`, `InitAndPlanAndShowWithStruct`, `InitAndPlanAndShowWithStructNoLogTempPlanFile`, `InitAndPlanWithExitCode`, `PlanExitCode`, `Destroy`, `Show`, `ShowWithStruct`, `Validate`, `InitAndValidate`, `Get`, `WorkspaceSelectOrNew` (`workspace list` → `select` or `new` → `show`), `WorkspaceDelete`, `RunTerraformCommand`, `GetExitCodeForTerraformCommand`, `OPAEval`.
Exit-code constants (`terraform.go`): `DefaultSuccessExitCode=0`, `DefaultErrorExitCode=1`, `TerraformPlanChangesPresentExitCode=2`.

**Plan-struct assertions** (`modules/terraform/plan_struct.go`): `PlanStruct{ResourcePlannedValuesMap map[string]*tfjson.StateResource, ResourceChangesMap map[string]*tfjson.ResourceChange, RawPlan tfjson.Plan}` built by recursively flattening `planned_values` across child modules; `ParsePlanJSON`, `AssertPlannedValuesMapKeyExists`, `RequirePlannedValuesMapKeyExists`, `AssertResourceChangesMapKeyExists`.

**Typed outputs** (`modules/terraform/output.go`, ~28 exported funcs): `Output`, `OutputRequired`, `OutputList`, `OutputMap`, `OutputMapOfObjects`, `OutputListOfObjects`, `OutputForKeys`, `OutputAll`, `OutputJson`, `OutputStruct`, each with an `E` variant. All go through `terraform output -json` and a recursive `parseMap`/`parseList`/`parseFloat` that *coerces* JSON floats back to ints (`output.go:120-135`) so `1` comes back as `int`, not `float64`. Typed errors in `errors.go`: `OutputKeyNotFound`, `OutputValueNotMap`, `OutputValueNotList`, `EmptyOutput`, `UnexpectedOutputType`.

---

## 3. The cloud-validation monorepo — breadth, pattern, cost

Exported-function counts (excluding `_test.go`), from the v2 tree:

| module | exported funcs | files |
|---|---|---|
| `azure` | 484 | 68 |
| `aws` | 428 | 56 |
| `k8s` | 312 | 62 |
| `gcp` | 288 | 56 |
| `terraform` | 183 | 32 |
| `core/*` (files, formatting, logger, random, retry, shell, testing, teststate) | 153 | — |
| `terragrunt` | 145 | 41 |
| `httphelper` | 58 | 6 |
| `helm` | 49 | 17 |
| `ssh` | 46 | 11 |
| `docker` | 45 | 16 |
| `teststructure` | 43 | 5 |
| `dnshelper` | 39 | 4 |
| `packer` | 22 | 5 |
| `opa` | 11 | 5 |
| `database` | 4 | 1 |

≈ **2,300 exported helper functions**, the overwhelming majority of which are thin SDK wrappers (`modules/aws/` alone: `acm.go asg.go cloudwatch.go dynamodb.go ebs.go ec2.go ecr.go ecs.go iam.go keypair.go kms.go lambda.go rds.go route53.go s3.go secretsmanager.go sns.go sqs.go ssm.go vpc.go …`).

**The pattern**: every helper is a `Foo`/`FooE` pair — `FooE` returns `(T, error)`, `Foo` calls it and `t.Fatal`s / `require.NoError`s. First arg is always `testing.TestingT` (`modules/core/testing/testing.go`), a 9-method interface (`Fail FailNow Fatal Fatalf Error Errorf Name Helper`) deliberately *not* `*testing.T` so Ginkgo etc. work. In v2 a third axis was added: `FooContext`/`FooContextE` taking `ctx context.Context`, and the non-`Context` forms were deleted — i.e. the pair-pattern's combinatorial cost is now a *documented migration burden* (`docs/_docs/04_migrating-to-v2/{behavior-changes,import-map,rewriting-imports}.md`, plus a generated `docs/v2-import-map.md`).

**Region randomization / unique IDs**: `modules/aws/region.go` — `GetRandomStableRegion(t, approved, forbidden []string)` (curated "stable" list), `GetRandomRegion`, `GetRandomRegionForService`, plus `modules/aws/ec2.go` `GetRecommendedInstanceType(t, region, []string)` because instance types aren't uniform across regions. `modules/core/random/random.go`: `UniqueID()` (6 chars), `Random`, `RandomInt`, `RandomString`. Namespacing doctrine: `docs/_docs/02_testing-best-practices/namespacing.md`.

**Maintenance cost / staleness (2026 status, verified live 2026-09-20)**:
- 7,947 stars; **0 open issues**; **8 open PRs**; last commit 2026-09-19. Not stale — but see below.
- `v1.0.0` released 2026-05-11 (https://www.gruntwork.io/blog/terratest-1-0-released). Latest v1: `v1.0.1`, 2026-06-27. Latest tag overall: `modules/core/v2.0.0-beta.2`, 2026-08-10.
- The **entire point of v2 is to amortise the SDK-wrapper cost**: split into per-provider Go modules so an AWS-only consumer stops dragging Azure/GCP/k8s SDKs into `go.sum` (blog claims 332 → 72 go.sum lines, −78% — *that figure is from a search summary of the release notes, not re-verified against the raw body*). README: v1 is maintenance/security-fixes-only until 12 months after v2.0.0 GA.
- **No** evidence of a Gruntwork acquisition or a "Terratest is now community-maintained" declaration — searched, not found, not ruled out. **Unverified.**
- Read the takeaway as: *the monorepo model was expensive enough that its maintainers spent a whole major version re-architecting the dependency graph around it.* That is the single strongest argument in the RFC for CDKTN not to build one.

---

## 4. Parallelism & isolation

- `t.Parallel()` at the top of every test; stages run sequentially inside a test.
- Isolation via `CopyTerraformFolderToTemp` (per-test temp root, so `.terraform/` + `terraform.tfstate` never collide), **disabled whenever a `SKIP_*` var is set**.
- State isolation: local state inside the temp copy is the default; `WorkspaceSelectOrNew` exists when you must share a backend.
- Resource-name collisions: `random.UniqueID()` threaded through `Vars` into every nameable resource.
- Plugin cache: Terratest does **not** set `TF_PLUGIN_CACHE_DIR`; it exposes `Options.PluginDir` → `terraform init -plugin-dir` (`init.go:39`, `format.go:117`). The known concurrency pain is instead handled by the 11 default retryable-error regexes around `terraform init` plugin fetch.
- Go-level: `docs/_docs/02_testing-best-practices/avoid-test-caching.md` prescribes `go test -count=1 -timeout 30m -p 1 ./...` — `-p 1` disables *package*-level parallelism, so parallelism is intra-package only.
- `docs/.../testing-environment.md`: separate cloud account, and `cloud-nuke` nightly to sweep leaked resources (`docs/.../cleanup.md`).

---

## 5. Terratest vs `terraform test` today

- **No official HashiCorp blog comparing the two, and no official Gruntwork response.** Not found. Only third-party writeups (spacelift.io/blog/terraform-test; dev.to/env0/terratest-vs-terraformopentofu-test-in-depth-comparison-10le). **Flag as unverified in the RFC.**
- Terratest's own `docs/_docs/02_testing-best-practices/alternative-testing-tools.md` lists kitchen-terraform, inspec, goss, awspec… and does **not** mention `terraform test` at all. `grep -ri "terraform test\|tftest"` over `modules/` and `docs/` returns nothing. **They do not interoperate and Terratest has no `terraform test` integration.**
- They compose only trivially: Terratest can `RunTerraformCommand(t, opts, "test")`.
- `terraform test` status: GA in **1.6.0**; **1.7** added `mock_provider` + `override_resource/data/module`; **1.11** added `override_during`; stable today is **1.16.3** (2026-09-16). `run` blocks support `command`, `state_key`, `parallel` (real, documented parallel run execution), `variables`, `module`, `expect_failures`, `plan_options`. `-junit-xml=<path>` is stable (incompatible with `-cloud-run`). OpenTofu latest is **1.12.6** (2026-08-19); mocking/overrides landed in OpenTofu 1.8.0; **`tofu test` JUnit output appears still unimplemented** (opentofu/opentofu#2501) — *unverified against 1.12.6 specifically*.

### `skip_cleanup` — your hypothesis is confirmed, with sourcing
- Requested: hashicorp/terraform **#34073** "Terraform Test: add ability to skip teardown" (open); related **#34356** "skip stage, add a breakpoint" (open).
- Implemented: **PR #36729** (merged 2025-04-02) "Allow skipping cleanup of entire test file or individual run blocks"; follow-ups **#36848** (backend blocks + skip_cleanup), **#36902**, and **#37359** "Implement controlling destroy functionality within Terraform Test" (merged 2025-09-10).
- **Shipping status, verified from live `main` CHANGELOG.md on 2026-09-20**: `skip_cleanup` and the companion **experimental `terraform test cleanup` command** sit under the **"1.18.0 (Unreleased)"** heading, explicitly qualified "In experimental builds of Terraform." Stable is 1.16.3; latest pre-release is 1.17.0-beta1. **It has shipped to no stable and no beta release.** The published `terraform test` language docs mention neither `skip_cleanup` nor `test cleanup`.
- **OpenTofu has nothing equivalent**: `search/issues repo:opentofu/opentofu skip_cleanup` → 0 results. Nearest: #248 (dump leftover state on failure), #1615 (retain resources on destroy), #3948 (post-*destroy* assertions — the opposite concern).
- ⇒ **For CDKTN, whose e2e path is `tofu`, `skip_cleanup` does not exist and should be treated as never arriving.** Custom code cannot be interleaved between apply and destroy of a `terraform test` run.

### Escape hatches inside `terraform test`
Confirmed available: HCL expressions, data sources, `check` blocks, provider-defined functions, `mock_provider`/`override_*`. **Not documented either way**: whether provisioners / the `external` data source / `terraform_data`+`local-exec` are *supported* inside a module under test. They are ordinary module features and no test-framework restriction was found, so they presumably execute as under `terraform apply` — **but that is inference, flag it.**

### ⚠️ Context finding you should put in the RFC preamble
**HashiCorp archived `hashicorp/terraform-cdk` on 2025-12-10** (`gh api repos/hashicorp/terraform-cdk` → `"archived": true`, `"pushed_at": "2025-12-10T…"`). CDKTF is sunset; HashiCorp says it will not maintain or develop it and encourages community forks (*the archive fact is primary-sourced; the reasons/forks language is secondary-sourced from community posts, e.g. peterwoods.online/blog/cdktf-is-dead*). This is why no `cdktf test` feature ever landed upstream — and it means **CDKTN owns this decision outright**; there is no upstream to align with.

### CDKTF prior art
- hashicorp/terraform-cdk **#806** "Support end-to-end testing cdktf stacks with Jest" — **closed**. Body notes it was "already possible using internal APIs of the cdktf-cli". Exactly the RFC's territory.
- #3703 "cdktf/testing: Add shouldTerraformApplyAndDestroy" (open), #2887 "add support for testing with Vitest" (closed), #3874 "fullSynth while testing returns invalid JSON" (open), #3918 (open).
- **No community "Terratest for CDKTF" package exists.** Upstream docs only ever covered synth-only unit tests.

---

## 6. NEW SECTION — the real-world CDKTN e2e suite at `/Users/vincentsmet/tcons/base/integ`

This is the highest-value evidence in the report: a production Terratest suite already driving **CDKTN-synthesized TypeScript stacks**. Everything below is from reading it.

### 6a. Structure

- A Go package tree inside the TS monorepo; the `go.mod` is one level up at `/Users/vincentsmet/tcons/base/go.mod` (module `github.com/terraconstructs/base`). Root package `integ` holds cross-cutting helpers; `integ/aws/` holds 24 SDK-wrapper files + 10 namespace sub-packages (`compute`, `storage`, `notify`, `edge`, `encryption`, `iam`, `monitoring`, `network`, `staticsite`, `stepfunctions`), each with `apps/*.ts`, `tf/`, `Makefile`, and `<ns>_test.go`.
- **Synth bridge**: `/Users/vincentsmet/tcons/base/integ/aws/util.go:59-125` `SynthApp(t, testApp, tfWorkingDir, env, additionalAsset...)`. It uses a bespoke external Go module **`github.com/terraconstructs/go-synth`** with a **Bun executor** (`executors.NewBunExecutor`) to: build an in-memory/afero FS, copy the repo root in as a local npm dep `./terraconstructs` (skipping `integ, src, .git, node_modules, dist, test, …` — `util.go:40-55`), rewrite the app's `../../../src` import to `terraconstructs` (`util.go:120`), `bun install`, evaluate `apps/<testApp>.ts`, then lift **`cdktf.out/stacks/<testApp>` → `tfWorkingDir`** (`util.go:121`). README warns: *"Make sure to build (`pnpm compile`) before running e2e — terratest only uses the compiled `lib` folder"* and *"Ensure bun is installed and available on $PATH for terratest to synth."*
  → **This is the single biggest piece of accidental complexity in the suite, and it exists solely because the harness is in Go and the app is in TypeScript.**
- **`TerraformDir`** is `tf/<testApp>` — a *deterministic, per-app* directory that the synth stage writes into. `CopyTerraformFolderToTemp` is **never used**; per-app directories provide the isolation instead.
- **Binary selection**: hardcoded `TerraformBinary: "tofu"` at `/Users/vincentsmet/tcons/base/integ/aws/util.go:153`. Not env-driven, not a matrix.
- **Deploy/destroy**: `util.go:148-168`
  ```go
  func DeployUsingTerraform(t, workingDir string, additionalRetryableErrors map[string]string) {
      terraformOptions := terraform.WithDefaultRetryableErrors(t, &terraform.Options{
          TerraformDir: workingDir, TerraformBinary: "tofu"})
      for k, v := range additionalRetryableErrors { terraformOptions.RetryableTerraformErrors[k] = v }
      test_structure.SaveTerraformOptions(t, workingDir, terraformOptions)
      terraform.InitAndApply(t, terraformOptions)
  }
  func UndeployUsingTerraform(t, workingDir) { terraform.Destroy(t, test_structure.LoadTerraformOptions(t, workingDir)) }
  ```
  Real per-test retryable errors are supplied inline, e.g. `storage/storage_test.go:273`: `".*No scalable target registered for service namespace: dynamodb.*"` → "eventual consistency between AutoScaling and DynamoDb".
- **Stages**: `synth_app`, `deploy_terraform`, `validate`, (`load_test`, `rename_app`, `validate_rename`), `cleanup_terraform` (deferred). Driven from the Makefile — `/Users/vincentsmet/tcons/base/integ/common.mk:34-52` defines pattern targets:
  ```make
  %-no-cleanup:     SKIP_cleanup_terraform=true make $*
  %-synth-only:     SKIP_deploy_terraform=true SKIP_validate=true SKIP_cleanup_terraform=true make $*
  %-validate-only:  SKIP_synth_app=true SKIP_cleanup_terraform=true make $*
  %-cleanup-only:   SKIP_synth_app=true SKIP_deploy_terraform=true SKIP_validate=true make $*
  ```
  `clean:` removes `tf/*`, `apps/cdktf.out`, `/tmp/go-synth-*` (`common.mk:54-57`). **This is the dev-iteration UX the CDKTN harness must reproduce.**
- **Outputs**: `util.LoadOutputAttribute(t, opts, key, attribute)` (`util.go:209-214`) wraps `terraform.OutputMap` + `require.NotEmpty` — because CDKTN stacks emit *structured* outputs (`{"bucket": {"name": …}}`), so the ubiquitous call shape is `LoadOutputAttribute(t, opts, "bucket", "name")`. Also `terraform.OutputAll`, and a generics helper `/Users/vincentsmet/tcons/base/integ/terraform.go:14-51`:
  ```go
  func TerraformOutputJMES[T any](t *testing.T, opts *terraform.Options, query string) T   // JMESPath over OutputForKeysE, then JSON round-trip into T
  ```
- **Assertions on API responses**: `/Users/vincentsmet/tcons/base/integ/assert.go` — `type Assertion{Path string /*JMESPath*/; Exists bool; ExpectedRegexp *string}` + `Assert(t, input, []Assertion)`, with an explicit comment at line 19 citing `aws-cdk/packages/@aws-cdk/integ-tests-alpha/lib/assertions/sdk.ts`. **They hand-rolled a Go port of `ExpectedResult`/`Match`.**
- **Env/naming**: every driver sets `AWS_REGION`, `ENVIRONMENT_NAME="test"`, `STACK_NAME=<testApp>` into the synth env (e.g. `storage/storage_test.go:258-261`). **No `random.UniqueID()` anywhere** (grep: 0 hits) and **no region randomization** — regions are hardcoded string literals: 59× `"us-east-1"`, 4× `"eu-central-1"`, 1× `"eu-west-2"`, 1× `"us-west-2"`. Uniqueness comes from app name + `ENVIRONMENT_NAME`, which means two concurrent runs of the same suite in one account would collide.
- **Parallelism**: `t.Parallel()` in every driver; isolation from distinct `tf/<app>` dirs, not temp copies.
- **Cleanup**: `defer test_structure.RunTestStage(t, "cleanup_terraform", …)`. No cloud-nuke equivalent observed.
- Uses **Terratest v1** import paths (`modules/test-structure`, `terraform.InitAndApply`) — a v2 migration is pending for them.

### 6b. Terratest capabilities actually relied on vs never touched

Imports across the whole suite (`grep -rhoE 'terratest/modules/[a-z-]+' | sort | uniq -c`):

| module | import sites | verdict |
|---|---|---|
| `modules/aws` | 28 | used — but see below |
| `modules/test-structure` | 24 | **core** |
| `modules/logger` | 23 | used |
| `modules/testing` | 18 | used (the `TestingT` interface) |
| `modules/terraform` | 16 | **core** |
| `modules/retry` | 12 | **core** |
| `modules/http-helper` | 4 | used, shallowly |
| `modules/files` | 1 | incidental |
| `k8s`, `helm`, `ssh`, `docker`, `packer`, `dns-helper`, `opa`, `database`, `gcp`, `azure`, `shell`, `random`, `terragrunt` | **0** | **never touched** |

**The decisive datum**: the project wrote **177 of its own exported AWS SDK-wrapper functions** across `integ/aws/*.go` (`cloudwatch.go` 21, `ec2.go` 17, `applicationautoscaling.go` 14, `sfn.go` 12, `util.go` 12, `servicediscovery.go` 10, `kinesis.go` 10, `cloudfront.go` 10, `autoscaling.go` 10, `sqs.go` 9, `dynamo.go` 7, `kms.go` 6, `s3.go` 5, `secretsmanager.go` 5, `sns.go` 4, `lambda.go` 4, `iam.go` 4, `eventbridge.go` 4, `acm.go` 4, `errors.go` 4, `batch.go` 2, …) **despite Terratest's `modules/aws` shipping 428**. Terratest's AWS module covered maybe 10-20% of what they needed (`aws.GetDynamoDBTable`, `aws.GetSyslogForInstance`, a handful more); everything else — Step Functions, App Auto Scaling, Cloud Map, CloudFront, Kinesis, EventBridge, Lambda-with-params — they wrote against `aws-sdk-go-v2` themselves.

> **This is the empirical case for the RFC's "do NOT rebuild the SDK-wrapper monorepo" stance.** A 428-function hand-maintained AWS wrapper layer still failed to cover a single real construct library's integration suite. Users write direct SDK calls regardless; the framework's job is to make that *easy*, not to intermediate it.

`http-helper` usage is likewise shallow — four call sites, all reproducible in ~5 lines of `fetch`: `compute/function_test.go:104` `HttpGet` → assert 200; `staticsite/bucket_test.go:49,60` `HttpGet` → assert 200; `compute/ecs_lb_test.go:104` `HttpGetWithRetryWithCustomValidation`; `compute/apigw_test.go:246` `HTTPDoWithRetry`.

`retry` **is** genuinely load-bearing: 12 sites, mostly `retry.DoWithRetryE` wrapping an SDK poll (`aws/acm.go:64`, `aws/cloudfront.go:171`, `aws/ec2.go:155`, `aws/cloudwatch.go:46`, `aws/kinesis.go:115`, `aws/secretsmanager.go:61`, `aws/servicediscovery.go:133`, `aws/sfn.go:152` uses `DoWithRetryableErrorsE`, `storage/storage_test.go:503,603`, `compute/ecs_sd_test.go:45,90`).

### 6c. Recurring boilerplate a first-party TS harness would delete

1. **The whole `go-synth` + Bun bridge** (`util.go:59-125`, ~65 lines of FS copying, dependency injection, import rewriting) — plus the `pnpm compile` prerequisite and the `lib/`-vs-`src/` footgun (`util.go:64`, `util.go:120`). In TypeScript this is `await project.synth()` / `Testing.fullSynth(stack)`. **Eliminated entirely.**
2. **11 near-identical stage drivers.** `runStorageIntegrationTest`, `runStorageIntegrationTestWithLoadTest`, `runStorageIntegrationTestWithRename` (a *second*, different copy in `staticsite/bucket_test.go:65`), `runComputeIntegrationTest`, `runComputeIntegrationTestWithRename`, `runEdgeIntegrationTest`, `runEncryptionIntegrationTest`, `runMonitoringIntegrationTest`, `runIamIntegrationTest`, `runNotifyIntegrationTest`, `runStepfunctionsIntegrationTest` — every one is the same 15 lines (`t.Parallel()`, `tfWorkingDir`, env map, deferred cleanup stage, synth/deploy/validate stages). One `integTest({...})` helper replaces all of them.
3. **`LoadOutputAttribute` / `TerraformOutputJMES[T]`** — hand-written because Terratest's `Output*` helpers are untyped and CDKTN outputs are nested objects. In TS this is just a typed accessor; with generated output types it's compile-time-checked.
4. **`assert.go`** — a 97-line Go re-implementation of CDK's `ExpectedResult`. In TS, `expect(...).toMatchObject(...)` plus a `jmespath`/optional-chaining accessor covers it.
5. **`ForwardingLogger`/`ForwardingCore`** (`util.go:242-273`, 30 lines) — a zap→terratest logger shim, needed only because two Go logging systems had to meet. Gone in TS.
6. **`PrettyPrintResourceChange` / `summarizePlan` / `countReplaceActions`** (`util.go:275-290`, `compute/helpers_test.go:14-51`) — plan-diff reporting that a framework should own.
7. Hardcoded `TerraformBinary: "tofu"` in one function — should be `TERRAFORM_BINARY_NAME`-driven like the rest of CDKTN.
8. No unique-ID/region strategy at all — a framework default (`uniqueId()` + opt-in region pool) would let the suite run concurrently.

### 6d. Which of its smoke tests fit inside plain `terraform test`

**Expressible in HCL (`assert` over data sources / outputs):**
- `iam/iam_test.go` role + assume-role-policy-document comparisons → `data "aws_iam_role"` + `jsondecode()` asserts. (They currently snapshot-compare against `snapshots/<app>/*.json`.)
- `storage/storage_test.go` DynamoDB table status/key-schema/attribute-definitions (`validateTableAutoScaling` lines 66-80) → `data "aws_dynamodb_table"`.
- `edge/edge_test.go` `validateServiceWithHttpNamespace` lines 88-145 — Cloud Map namespace/service/instance attribute equality → *partly*; `aws_service_discovery_*` data sources exist for namespace/service, not for instances or `DiscoverInstances`.
- `staticsite/bucket_test.go:49,60` HTTP 200 probes → `data "http"` + `check` block / output postcondition. The `hashicorp/http` provider's `retry` block handles the propagation delay.
- `compute/function_test.go:104` Function-URL GET 200 → same.

**Genuinely need custom code:**
- Every **invoke-and-observe** flow: `util.InvokeFunctionWithParams` + `util.WaitForQueueMessage` (`function_test.go:113-121`), SNS→SQS round-trips (`notify/notify_test.go:221`), Kinesis, EventBridge chains (`TestLambdaChain`).
- Every **poll-until-converged**: `util.WaitForCertificateIssued` (`edge_test.go:83`), `util.WaitForDistributionDeployed` (`edge_test.go:59`), `util.WaitForSfnExecutionStatus` (`stepfunctions_test.go:141,153,176,214,228`), `util.WaitForCloudMapInstanceDiscoverable` (`edge_test.go:139,143`).
- **Step Functions** start-execution + result assertion (`stepfunctions_test.go:236-245`) — no data source can start an execution.
- **App Auto Scaling** scalable targets / scaling policies / scheduled actions (`storage_test.go:84-113`) — no Terraform data sources exist.
- **Load tests** (`runStorageIntegrationTestWithLoadTest` → `storage_test.go:503,603` write traffic then poll CloudWatch).
- **`ReplaceTerraformResource`** (`util.go:173-182`) — `apply -replace=<addr>` on a resource discovered from `terraform state list`.
- **The rename tests** (`runComputeIntegrationTestWithRename`, `function_test.go:343-375`; `runStorageIntegrationTestWithRename`, `bucket_test.go:65`): deploy → validate → **re-synth the TS app with `ENVIRONMENT_NAME=renamed`** → replan → `require.Equal(t, 0, countReplaceActions(plan))`. This is *the* CDKTN-specific regression test (construct-ID/naming stability), it requires re-running the TypeScript synth mid-test, and **no version of `terraform test` can ever host it.**

**Rough split (estimate, not a count of every line)**: ~30-40% of assertion *statements* are attribute checks that HCL could express; but only a small handful of the ~45 test functions could run *end-to-end* inside `terraform test` without losing their point. **The suite is evidence that the custom-code tier is not a long tail — it is the main body of the work.**

---

## 7. Translation table

Legend — **Exists**: ✅ shipped · 🟡 partial/internal · ❌ absent. **Priority**: P0 = needed for a first usable harness · P1 = needed for parity with today's Go suite · P2 = nice-to-have.

| Terratest capability | TS / CDKTN equivalent | Exists today? | Proposed home | Pri |
|---|---|---|---|---|
| `teststructure.RunTestStage` + `SKIP_<stage>` | `stage(name, fn)` reading `process.env["SKIP_"+name]`; registered teardown via `afterAll`, and a `stages({...})` builder | ❌ | `@cdktn/integ` | **P0** |
| `.test-data` JSON store (`teststate.Save/Load`, `FormatPath`, `IsPresent`, `IsEmptyJSON`) | `TestData` class: `<workdir>/.test-data/<Name>.json`, `save/load/has/clear`, `0o600`, `saveRedacted` | ❌ | `@cdktn/integ` | **P0** |
| `SaveTerraformOptions`/`LoadTerraformOptions` | `saveDeployment()/loadDeployment()` persisting `{outDir, stackName, workingDirectory, vars, binary, retryable}` — the CDKTN analogue of `Options` | ❌ | `@cdktn/integ` | **P0** |
| `SaveString/SaveInt/SaveEc2KeyPair/SaveTestData` | one generic `testData.save<T>(name, value)` — **no per-cloud wrappers** (the `SaveEc2KeyPair` pattern is exactly the coupling to avoid) | ❌ | `@cdktn/integ` | **P0** |
| `terraform.Options{TerraformDir,…}` | `CdktfProject` ctor + `MutationOptions` (`vars`, `varFiles`, `parallelism`, `terraformParallelism`, `noColor`, `autoApprove`, `refreshOnly`, `migrateState`) | 🟡 `packages/@cdktn/cli-core/src/lib/cdktf-project.ts` — but the file header says *"the interfaces in this file are not stable"* | `@cdktn/cli-core` (stabilise a documented subset) | **P0** |
| `InitAndApply` / `Destroy` | `project.deploy({stackNames, autoApprove:true})` / `project.destroy(...)`; per-stack `CdktfStack.deploy/destroy` | ✅ `cdktf-project.ts`, `cdktf-stack.ts` | `@cdktn/cli-core` | — |
| multi-stack ordering | dependency-ordered deploy / reverse-ordered destroy, `parallelism` slots, serial `init` ("text file busy" cache guard) | ✅ `lib/helpers/stack-helpers` | `@cdktn/cli-core` | — |
| `Output` / `OutputMap` / `OutputAll` / `OutputStruct` typed getters | `outputs<T>(stackName)` returning a **typed** object; plus a `LoadOutputAttribute` analogue for CDKTN's nested `{construct:{attr}}` shape, and JMESPath access | 🟡 raw only: `TerraformCli.output()` → `{[k]: {sensitive,type,value}}`; `NestedTerraformOutputs`/`outputsByConstructId` exist but are untyped | `@cdktn/integ` on top of `cli-core` | **P0** |
| `RetryableTerraformErrors` + `WithDefaultRetryableErrors` (11 default regexes) | `retryableErrors: Record<string,string>` on the deploy wrapper + a `DEFAULT_RETRYABLE_ERRORS` constant; port the 11 regexes verbatim | ❌ — `CdktfProject` has no retry at all | `@cdktn/integ` (wrapping `project.deploy`) | **P0** |
| `retry.DoWithRetry(ableErrors)` / `DoWithTimeout` | `eventually(fn, {timeout, interval, backoffRate})`, `retry(fn, {maxRetries, sleep, retryableErrors})`, `FatalError` sentinel to abort early | ❌ | `@cdktn/integ` | **P0** |
| `CopyTerraformFolderToTemp` (+ skip-copy when `SKIP_*` set) | not needed for the app itself — `Testing.fullSynth()` already writes to `mkdtempSync("cdktf.outdir.")`. Needed instead: a **stable** outDir when stages are in play, i.e. `CDKTF_OUTDIR=tf/<app>` | 🟡 `Testing.fullSynth` (`packages/cdktn/src/testing/index.ts:174`) + `CDKTF_OUTDIR` (`packages/cdktn/src/app.ts:101`) | `@cdktn/integ` (outDir policy) | **P1** |
| `TerraformBinary` (terraform/tofu) | `TERRAFORM_BINARY_NAME` env var (**not** `CDKTF_*`) | ✅ `packages/@cdktn/commons/src/terraform.ts` — `process.env.TERRAFORM_BINARY_NAME \|\| "terraform"`, resolved once at import | — (document it) | — |
| `WorkspaceSelectOrNew` | workspace selection per test | ❌ | `@cdktn/integ` | P2 |
| `ApplyAndIdempotent` | `deploy()` then `diff()` and fail on non-empty plan | ❌ (`project.diff()` exists) | `@cdktn/integ` | **P1** |
| `InitAndPlanAndShowWithStruct` + `PlanStruct` + `Assert*MapKeyExists` | `planStruct()` returning `{resourceChanges, plannedValues, raw}` from `terraform show -json`; `countReplaceActions`/`summarizePlan` as first-class — **this is what the rename tests need** | ❌ | `@cdktn/integ` | **P1** |
| `PlanExitCode` / detailed exitcode | `planExitCode()` → 0/1/2 | ❌ | `@cdktn/integ` | P2 |
| `random.UniqueID()` | `uniqueId(len=6)` | ❌ | `@cdktn/integ` | **P0** (cheap, unblocks concurrency) |
| `aws.GetRandomStableRegion` / `GetRecommendedInstanceType` | `pickRegion(["us-east-1", …])` — a *user-supplied* pool, not a curated cloud table | ❌ | `@cdktn/integ` (generic only) | P2 |
| `modules/{aws,azure,gcp}` — ~1,200 SDK wrappers | **nothing.** Users call `@aws-sdk/client-*`, `@azure/*`, `@google-cloud/*` directly. Evidence: `tcons/base/integ` wrote 177 of its own anyway | n/a | **out of scope, explicitly** | — |
| `modules/httphelper` (58 funcs) | `fetch` + `eventually()` | n/a (3 lines of user code) | out of scope | — |
| `modules/{k8s,helm}` (361 funcs) | `@kubernetes/client-node`, `helm` via `execa` | n/a; **0 uses in the real suite** | out of scope | — |
| `modules/{ssh,docker,packer,dnshelper,database,opa}` | node libs (`ssh2`, `dockerode`, `dns/promises`, `pg`/`mysql2`) | n/a; **0 uses in the real suite** | out of scope | — |
| `testing.TestingT` abstraction | not needed — Jest and Vitest share `expect`; keep the harness runner-agnostic by never importing `@jest/globals` | n/a | `@cdktn/integ` design rule | — |
| CDK `ExpectedResult`/`Match` ≈ `tcons` `assert.go` | `expect(obj).toMatchObject(...)` + a small `atPath(obj, jmespath)` helper | ❌ (hand-rolled in Go today) | `@cdktn/integ` | **P1** |
| `go test -run` / `-p 1` / `-count=1` | `jest -t` / `--runInBand`; **no result caching to defeat** | ✅ (runner) | — | — |
| `cloud-nuke` nightly sweep | out of scope; document the pattern | n/a | RFC prose | — |
| **Go-user path** | **Terratest, unchanged**, with `TerraformDir` = `<CDKTF_OUTDIR>/stacks/<stack>` and `TerraformBinary: "tofu"` | ✅ *already proven in production by `tcons/base/integ`* | docs | **P0 (docs only)** |
| synth-only unit assertions | `Testing.synth/synthScope/toHaveResourceWithProperties/toBeValidTerraform/toPlanSuccessfully` | ✅ `packages/cdktn/src/testing/` | `cdktn` (jsii) | — |
| authoring `.tftest.hcl/.json` from TS | `TerraformTest`/`RunBlock` constructs emitting `<stack>.tftest.json` beside `cdk.tf.json` | ❌ | `cdktn` (jsii) | **P0** |
| `cdktn test` CLI | new subcommand | ❌ — command list is `init get convert deploy destroy diff list login synth watch output debug provider` (`packages/cdktn-cli/src/bin/cdktn.ts`) | `cdktn-cli` | **P0** |

---

## 8. jsii: where each piece belongs

- `cdktn` **is** jsii (`packages/cdktn/package.json` → targets `python, java, dotnet, go`).
- `@cdktn/cli-core`, `@cdktn/commons`, `cdktn-cli` are **plain TypeScript, published, non-jsii**.

**Recommendation — split by phase, not by language:**

| layer | package | jsii? | why |
|---|---|---|---|
| synth-time: `.tftest.json` authoring constructs, existing `Testing` matchers | `cdktn` | **yes** | It's construct-graph output; Python/Java/Go users must be able to author test files. `terraform test` then runs them language-agnostically — **this is the multi-language story, and it needs no runtime harness at all.** |
| runtime e2e harness: stages, `.test-data`, deploy/destroy, typed outputs, retry | **`@cdktn/integ`** (new) | **no — TypeScript-only** | It depends on `@cdktn/cli-core` (non-jsii), needs `async/await`, generics, closures, `Record<string,unknown>`, and structural typing that jsii forbids. Forcing it through jsii would gut the API for zero benefit: a Go user gets a *better* harness from Terratest, and a Python user gets `subprocess` + boto3. |
| CLI | `cdktn-cli` | no | `cdktn test` in two modes (§10). |

**Other languages:**
- **Go — the zero-cost path, already proven.** `terraform.Options{TerraformDir: filepath.Join(outDir,"stacks",stackName), TerraformBinary: "tofu"}` + `teststructure` + `retry`. `tcons/base/integ` does exactly this. Document it as a supported, first-class path in the RFC, including: `CDKTF_OUTDIR` to control the outdir, `<outDir>/manifest.json` + `<outDir>/stacks/<name>/cdk.tf.json` as the contract, `TERRAFORM_BINARY_NAME=tofu`, and a pointer to `github.com/terraconstructs/go-synth` as prior art for synth-from-Go (while noting the cleaner option is to run `cdktn synth` as a Make/CI step *before* `go test`, rather than embedding a Bun executor).
- **Python/Java/.NET**: `cdktn synth` as a pre-step, then the language's own test runner + cloud SDK, pointing `terraform`/`tofu` at the stack dir. The `.tftest.json` constructs give them the no-custom-code tier for free.
- **Stability precondition**: `@cdktn/cli-core/src/lib/index.ts` currently carries *"the interfaces in this file are not stable."* Shipping `@cdktn/integ` on top of `CdktfProject` means committing to a **documented, semver'd subset** — `CdktfProject`, `CdktfStack`, `SynthesizedStack`, `NestedTerraformOutputs`, `ProjectUpdate`/`StackUpdate`, `TerraformOutput`. Call that out as an RFC deliverable.

---

## 9. The hybrid, and the three workarounds

**Constraint, restated with sourcing**: `terraform test` destroys everything at the end of a run file, and `skip_cleanup` exists **only in unreleased/experimental Terraform builds (CHANGELOG "1.18.0 (Unreleased)") and not at all in OpenTofu**. Since CDKTN's e2e path is `tofu`, treat it as permanently unavailable. **There is no hook between apply and destroy of a `terraform test` run.**

### (a) Harness-owned apply/destroy, custom code in between — **RECOMMENDED**
The Terratest model, in TypeScript, on `CdktfProject`. The harness owns the lifecycle; between `deploy()` and `destroy()` you run arbitrary TS.
- **Pros**: full language power; failures are ordinary Jest failures with real stack traces; skip-teardown is a one-line env var *that the harness controls* (no Terraform feature needed); it is exactly what `tcons/base/integ` already does successfully in Go, so it's de-risked; the rename/replan test class is only possible here.
- **Cons**: reimplements retry/staging/state that `terraform test` gives free for the HCL-expressible tier; no `mock_provider`.
- Reuse the *same TS assertion objects* in both tiers: define assertions as plain data (`{path, matcher}`), then either (i) evaluate them in TS against SDK responses, or (ii) lower them into `assert { condition = … }` blocks in a generated `.tftest.json`. One author-time vocabulary, two execution engines.

### (b) `external`/`http` data source or `terraform_data`+`local-exec` calling back into Node — **REJECT**
- Undocumented inside `terraform test` (see §5; inference only).
- The `external` provider requires a program emitting a flat `map[string]string` on stdout — every assertion result must be stringified; failures surface as opaque provider errors with no stack trace and no diff.
- Test code would run inside `terraform apply`, so `tofu` must be able to find `node` and the compiled harness; provider errors abort the apply *before* other assertions run.
- **Security**: it turns any `.tftest.json`/module into an arbitrary-code-execution vector triggered by `tofu test`. For a framework that generates these files from user TS, that is an unacceptable default posture.
- Genuinely ugly: debugging means reading Terraform's error rendering of a JSON blob.

### (c) Provider-defined functions — **REJECT for smoke tests**
Functions are expected to be pure and are evaluated during expression evaluation, not as a lifecycle step. Making one do a `WaitForSfnExecutionStatus`-style poll means writing and distributing a Go provider — which is *more* Go than just using Terratest. Sensible only for pure computation (parsing, formatting), not for probing live infra.

### Recommendation
> **Two tiers, one authoring vocabulary.**
> **Tier 1 (cheap, no deploy harness):** CDKTN synthesizes `.tftest.json` beside `cdk.tf.json`; `cdktn test` shells out to `tofu test`. Covers plan-shape assertions, mocked-provider unit tests, attribute checks via data sources, and `http`-data-source probes. Runs in CI on every PR. Gets the multi-language story for free via jsii constructs in `cdktn`.
> **Tier 2 (`@cdktn/integ`):** harness-owned `deploy → custom TS → destroy`, staged, with `.test-data` persistence and `SKIP_*`. This is where SDK calls, polling, round-trips, load tests and the re-synth/replan regression tests live. Nightly / on-demand.
> Explicitly **do not** attempt to bridge tier 1 into tier 2 via `external`/`local-exec`. Revisit only if `skip_cleanup` ever ships in *OpenTofu* stable.

---

## 10. Comparison with AWS CDK `integ-tests-alpha`

**What it is** (README: `github.com/aws/aws-cdk/blob/main/packages/@aws-cdk/integ-tests-alpha/README.md`, `INTEGRATION_TESTS.md`):
- `new IntegTest({ testCases: [stack] })`; assertions via `integ.assertions.awsApiCall(service, api, params)` (JS SDK call, IAM policy auto-derived), `httpApiCall(url)` (node-fetch), `invokeFunction({functionName, payload})`.
- `ExpectedResult.objectLike/arrayWith/stringLikeRegexp/serializedJson` + `Match`.
- `.waitForAssertions({ totalTimeout, interval, backoffRate })` → backed by a **Step Functions waiter state machine**.
- Mechanism: **assertions are deployed as Lambda-backed CloudFormation custom resources in a separate `DeployAssert` stack**, so they don't pollute the diff of the stack under test.
- `integ-runner` workflow: synth-and-compare against a stored `*.snapshot/` cloud assembly (no deploy); `--update-on-failed` does real `cdk deploy` → assertions → `cdk destroy` → rewrite snapshot.

**Does an "assertions as Terraform resources/data sources/check blocks" analogue cover a useful 80% inside plain `terraform test`?**
**No — I'd put it at 30-40%, and the missing part is the expensive part.** Concretely:
- ✅ **Attribute reads** map cleanly: `data "aws_iam_role"`, `data "aws_dynamodb_table"`, `data "aws_s3_bucket"` + `assert { condition = … }`. Covers the `iam/` snapshot tests and much of `storage/`.
- ✅ **HTTP probes** map well: `data "http"` (the `hashicorp/http` provider has a `retry` block, giving you a poor-man's `waitForAssertions`) + a `check` block or output postcondition. Covers `staticsite/` and the Function-URL test.
- 🟡 **Lambda invoke**: `data "aws_lambda_invocation"` exists and genuinely works — the closest thing to `invokeFunction`.
- ❌ **Everything else that `awsApiCall` trivially does**: App Auto Scaling scalable targets/policies/scheduled actions, `sfn:StartExecution` + `DescribeExecution`, `sqs:ReceiveMessage`, `servicediscovery:DiscoverInstances`, CloudFront `DescribeDistribution` until `Deployed`, ACM until `ISSUED`. Terraform data sources exist for a *fraction* of AWS's API surface, and **there is no generic "call any API" data source** — which is precisely the gap CDK filled with a Lambda custom resource.
- ❌ **Retry semantics**: `waitForAssertions` has no Terraform analogue outside the `http` provider's `retry`. `time_sleep` + `depends_on` is the usual hack and it's a fixed sleep, not a poll.
- ⚠️ **`check` blocks specifically**: `check` failures are *warnings* during apply. **Whether a failing `check` block fails a `terraform test` run is something I did not verify** — flag it and confirm before relying on it. Resource **postconditions** and `assert` blocks definitely do fail.

**The interesting structural option** (worth a paragraph in the RFC, and squarely within this team's demonstrated ability): the true analogue of CDK's Lambda-backed custom resource is **a CDKTN-owned Terraform provider exposing a generic "call this cloud API and return JSON" data source plus a polling variant** — i.e. what `cfncompat` already does for CloudFormation semantics. That *would* get you to ~80% inside plain `terraform test`, with assertions synthesized from TypeScript. But it means owning a provider, a Go SDK-dispatch layer (the very SDK-wrapper maintenance burden §3 argues against, relocated into Go), and per-cloud auth. **My recommendation is to note it as a deliberately-deferred option, not to build it** — the `tcons/base/integ` evidence says the custom-code tier is the main body of the work, and the harness in TS gets you there with far less to maintain.

**What CDKTN *should* steal from CDK outright**: the **snapshot tier**. `integ-runner`'s "synth and diff against a committed cloud assembly, no deploy" is cheap, catches most regressions, and maps perfectly onto `cdktn synth` + a committed `cdk.tf.json`. `tcons/base/integ` already gropes toward this with `snapshots/<app>/*.json` and its rename/replan tests.

---

## 11. Recommended long-term roadmap (paste-ready)

- **Ship the no-custom-code tier first: TypeScript-authored `terraform test`.** jsii constructs in `cdktn` synthesize `<stack>.tftest.json` beside `cdk.tf.json`; `cdktn test` runs `tofu test` over them. This covers plan-shape assertions, `mock_provider` unit tests, data-source attribute checks and `http`-data-source probes, works identically for Python/Java/Go/.NET users, and needs no deployment harness. Committed synth snapshots (the `integ-runner --directory` model) ride along as the cheapest regression tier.

- **Then ship `@cdktn/integ` — a TypeScript-only, non-jsii e2e harness — as the Terratest analogue, built on `CdktfProject`.** Five primitives, nothing more: `stage(name, fn)` honouring `SKIP_<stage>`; a JSON `.test-data` store (`save/load/has/clear`, `0600`, redacted variant) that survives across processes; a deploy/destroy wrapper adding the 11 default retryable-error regexes, `maxRetries` and `applyAndIdempotent`; **typed** stack outputs (with a nested-attribute accessor for CDKTN's `{construct:{attr}}` output shape); and `retry`/`eventually` with `{timeout, interval, backoffRate}`. Plus `uniqueId()`. This deletes the ~11 duplicated stage drivers, the `LoadOutputAttribute`/`TerraformOutputJMES`/`assert.go`/`ForwardingLogger` boilerplate and the entire `go-synth`+Bun bridge that `tcons/base/integ` carries today (`/Users/vincentsmet/tcons/base/integ/aws/util.go:59-125`).

- **Explicitly refuse to build a cloud-SDK wrapper monorepo, and say why in the RFC.** Terratest maintains ~1,200 AWS/Azure/GCP/k8s wrapper functions and spent an entire major version (v2, multi-module) re-architecting around that cost — and it still wasn't enough: `tcons/base/integ` wrote **177 of its own AWS helpers** on top of Terratest's 428, and never touched `k8s`, `helm`, `ssh`, `docker`, `packer`, `dns-helper`, `opa`, `database`, `gcp` or `azure` at all. CDKTN supplies typed outputs, retry/eventually, and unique-ID/region helpers; users call AWS SDK v3 / Azure / GCP SDKs / `fetch` / `@kubernetes/client-node` directly.

- **Document the Go path as first-class and zero-cost: Terratest against `<CDKTF_OUTDIR>/stacks/<stack>`.** `terraform.Options{TerraformDir: filepath.Join(outDir, "stacks", name), TerraformBinary: "tofu"}` with `teststructure` and `retry`. This is not a hypothetical — it is how `tcons/base/integ` ships today. Contract to freeze and document: `CDKTF_OUTDIR`, `<outDir>/manifest.json`, `<outDir>/stacks/<name>/cdk.tf.json`, and `TERRAFORM_BINARY_NAME`. Recommend running `cdktn synth` as a pre-step rather than embedding a synth bridge in Go.

- **Treat `skip_cleanup` as never arriving, and stabilise `@cdktn/cli-core` instead.** `skip_cleanup` sits in Terraform's unreleased 1.18 CHANGELOG as experimental-builds-only, and OpenTofu has no equivalent (0 issue hits) — so custom code can never run between apply and destroy of a `terraform test` run, and the harness must own the lifecycle. The prerequisite is turning `CdktfProject`/`CdktfStack`/`SynthesizedStack`/`NestedTerraformOutputs`/`TerraformOutput` into a documented, semver'd public API (today `lib/index.ts` warns *"the interfaces in this file are not stable"*). Defer, and name as deferred, the "assertions-as-resources" option — a CDKTN-owned provider with a generic cloud-API data source (à la `cfncompat`) would reach CDK `integ-tests-alpha` parity inside plain `terraform test`, at the price of relocating the SDK-wrapper burden into Go.

---

## 12. Unverified / flagged

1. Terratest v2's "16 submodules" and the 332→72 go.sum figure — from a search summary of the release notes, not the raw body.
2. No official HashiCorp `terraform test` vs Terratest comparison, and no Gruntwork response — searched, **not found**, not ruled out.
3. No Gruntwork acquisition / "community maintained" declaration found — not found, not ruled out.
4. Whether provisioners / `external` data source / `terraform_data`+`local-exec` are *documented* as working inside a module under `terraform test` — **no documentation either way**; my §9(b) assessment treats them as working-by-inference and rejects them on other grounds regardless.
5. **Whether a failing `check` block fails a `terraform test` run** — not verified. `assert` blocks and resource postconditions definitely do. Confirm before designing tier 1 around `check`.
6. Whether `terraform test` supports the newer `list`/`query` resource mode — not checked.
7. OpenTofu 1.12.6 `tofu test` JUnit support — evidence (opentofu/opentofu#2501) suggests still missing, not reconfirmed at 1.12.6.
8. CDKTF sunset: the **archive fact** is primary-sourced (`gh api repos/hashicorp/terraform-cdk` → `archived: true`, `pushed_at: 2025-12-10`); the *reasons* and "encourages community forks" language are secondary-sourced (community blogs), not a fetched HashiCorp announcement.
9. My "30-40% expressible in HCL" split for the `tcons` suite is a qualitative read of the validate bodies I sampled (`storage`, `compute/function`, `edge`, `iam`, `staticsite`, `stepfunctions`, `notify`), not an exhaustive per-assertion count.
10. `/Users/vincentsmet/cdktn/ref-terratest` is the **v2** tree; v1 package paths and the non-`Context` function names cited in the RFC should be sanity-checked against the `v1` branch if exact API names matter.
