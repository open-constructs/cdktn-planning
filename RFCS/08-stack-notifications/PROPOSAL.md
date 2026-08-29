# Proposal: Stack event notifications (CloudFormation `NotificationARNs` parity) in the CDKTN execution engine

Status: **draft** · Code/architecture proposal, the evidence is
source read directly (`@cdktn/cli-core`, `terraform-provider-cfncompat`,
`aws-cdk-lib`) plus two capability surveys of the Terraform/OpenTofu ecosystem.
No `data/` sweep or `report.html`.

## Problem

CloudFormation publishes every **stack event** — `CREATE_IN_PROGRESS`,
`UPDATE_COMPLETE`, `DELETE_FAILED` with a reason, per logical resource, plus
stack-level bookends — to the SNS topics listed in the stack's
`NotificationARNs`. Organisations wire those topics to ChatOps, audit trails,
EventBridge and incident tooling; the AWS CDK exposes them as
`StackProps.notificationArns` / `cdk deploy --notification-arns` and as the
`AWS::NotificationARNs` pseudo parameter (`core/lib/stack.ts:510-516`,
`cfn-pseudo.ts:24`).

Terraform/OpenTofu has **no equivalent**. cfncompat `v0.3.0`
([RFC 006](https://github.com/cdktn-io/terraform-provider-cfncompat/blob/main/RFCs/006-pseudo-parameter-polyfill.md)
§2.3b) now *echoes* `notification_arns` so templates that read the pseudo
parameter resolve, but nothing delivers events — and nothing inside a provider
ever can:

> The Terraform plugin protocol (tfplugin5/6) gives a provider RPCs only for its
> own resources. There is no "apply started/finished" RPC and no visibility into
> other providers' resources. — RFC 006 §2.3b

The only place that sees the whole graph, knows the stack's name, and already
owns the `terraform`/`tofu` process is the **CDKTN CLI execution engine**
(`@cdktn/cli-core`). This proposal puts a provider-neutral *stack notifications*
capability there, with AWS SNS as the first sink and GCP Pub/Sub / Azure Event
Grid as siblings, so that:

1. the AWS CDK-on-Terrain bridge can honour `notificationArns` end to end
   (pseudo parameter *and* delivery from one declaration);
2. plain CDKTN users get CloudFormation-grade per-resource deployment events
   without a TACOS; and
3. a TACOS running CDKTN as its engine gets the same events for free.

## Findings

### F1 — The Terraform JSON UI stream is the only stable per-resource signal

Both CLIs emit the same JSON-Lines machine-readable UI under `-json`
([Terraform](https://developer.hashicorp.com/terraform/internals/machine-readable-ui),
[OpenTofu](https://opentofu.org/docs/internals/machine-readable-ui/)). OpenTofu
1.12 added `-json-into=FILE` (file or FIFO) so the stream can be consumed
*alongside* the human UI — built explicitly for wrapper tools
([release notes](https://opentofu.org/blog/opentofu-1-12-0/),
[dual streams](https://opentofu.org/blog/dual-command-output-streams/)).

| `type` | Fields relevant to a stack event |
| --- | --- |
| `apply_start` / `apply_progress` / `apply_complete` / `apply_errored` | `hook.resource{addr,module,resource_type,resource_name,resource_key,implied_provider}`, `hook.action` (create/update/delete/replace/read), `hook.id_key`/`hook.id_value` (start/complete only), `hook.elapsed_seconds`, `@timestamp` |
| `planned_change`, `resource_drift`, `change_summary` | plan-time only (`change.resource`, `change.action`, `change.reason`) |
| `diagnostic` | `severity`, `summary`, `detail`, `range` — **no resource address**; correlation is best-effort |
| `outputs` | per-output value/type/sensitive |
| `provision_*`, `refresh_*`, `ephemeral_op_*` | per-resource sub-phases |

Alternatives surveyed and rejected as a backbone: OpenTelemetry tracing in both
cores is explicitly "not a committed external interface… may be removed", covers
a handful of call sites (init/provider lock), has no per-resource apply spans and
fails silently ([opentofu#4102](https://github.com/opentofu/opentofu/issues/4102));
`TF_LOG` is unstructured; there is **no** hooks/webhook RFC or issue in OpenTofu —
`-json-into` is the sanctioned integration point.

### F2 — `@cdktn/cli-core` already models the stream but does not use it for `deploy`

- `src/lib/models/schema.ts` carries zod schemas for `version`,
  `planned_change`, `change_summary`, `outputs`, `apply_start/progress/complete/errored`,
  `provision_*`, `refresh_*`, `log` — i.e. the JSON UI contract is already typed
  in the codebase (consumed today by `output.ts`).
- `deploy`/`destroy` run `terraform apply` through a **pty** *without* `-json`
  (`models/deploy-machine.ts:383-415`: `apply`, `-auto-approve`?, `-refresh-only`?,
  `-no-color`?, `-parallelism`, `-var*`) and derive `DeployingResource`
  transitions (`models/terraform.ts:22-29`: `applyState`) by parsing the human
  output; consumers receive them through
  `Terraform.deploy(options, callback: (state: TerraformDeployState) => void)`
  (`terraform.ts:147-166`).
- The stack name is threaded through every `CdktfStack` call
  (`cdktf-stack.ts:28-70`, `stackName`), and the synthesized manifest already
  carries per-stack metadata the CLI reads before deploying.

So the engine has (a) a typed event schema, (b) a per-resource callback seam,
and (c) stack identity — the three inputs a notifier needs — but the highest-
fidelity source (`-json`) is not wired into `deploy`.

### F3 — No wrapper or TACOS offers per-resource outward events; none is SNS-native

Spacelift (run-state webhooks via notification policy), env0, Scalr
(`run:completed/errored/needs_attention`), HCP Terraform Notifications and Run
Tasks (run/stage level), Atlantis (PR comments), Terragrunt (before/after shell
hooks), tofu-controller/Burrito (Kubernetes `Events` per workspace CR). All are
**run-granular**. Nothing lets a user configure an SNS topic for per-resource
events. A TACOS that runs CDKTN as its engine would therefore *gain* a feature
it does not have, rather than duplicate one.

### F4 — CloudFormation `StackEvent` fields and what the stream can reconstruct

| CFN `StackEvent` field | Source | Quality |
| --- | --- | --- |
| `StackName` / `StackId` | CDKTN manifest (stack name) + cfncompat's deterministic `stack_id` rule (RFC 006 §2.3) | exact, engine-supplied |
| `LogicalResourceId` | `hook.resource.addr` (Terraform address; CDK logical id is recoverable via the bridge's id map if wanted) | exact |
| `ResourceType` | `hook.resource.resource_type` (`aws_s3_bucket`, `awscc_s3_bucket`, `cfncompat_custom_resource`) | exact |
| `PhysicalResourceId` | `hook.id_value` | absent on delete-start and most `apply_errored` |
| `ResourceStatus` | `type` × `hook.action` → `CREATE/UPDATE/DELETE_{IN_PROGRESS,COMPLETE,FAILED}`; `replace` → `DELETE_*` + `CREATE_*` | synthesized |
| `ResourceStatusReason` | nearest `diagnostic.detail`; `@message` on `apply_errored` | best-effort |
| `Timestamp` | `@timestamp` | exact |
| `ClientRequestToken` | engine run id | engine-supplied |
| `UPDATE_ROLLBACK_*`, `REVIEW_IN_PROGRESS` | — | no rollback phase in Terraform; not emitted |

### F5 — The AWS CDK bridge already has the declaration point

`Stack.notificationArns` (`stack.ts:814`) is `ScopedAws.notificationArns`; the
bridge (RFC 002 I2 `resolvePseudo`) maps it to
`data.cfncompat_pseudo_parameters.<stack>.notification_arns`, which is an
*input* echoed back (RFC 006 §2.2). The same list must reach the engine so the
pseudo parameter and actual delivery never disagree.

## Design

### 1. Declaration — where the ARNs come from (precedence high → low)

1. **CLI flag**: `cdktn deploy --notification-arn arn:… [--notification-arn …]`
   (mirrors `cdk deploy --notification-arns`); `--no-notifications` to mute.
2. **Stack metadata in the manifest**: apps declare on the stack, e.g.
   `new TerraformStack(app, "prod", { notifications: [...] })` (or
   `Notifications.of(stack).add(...)` as an aspect-free helper), written to the
   synthesized manifest next to the existing per-stack metadata. The AWS CDK
   bridge writes `StackProps.notificationArns` here.
3. **Project default in `cdktn.json` / `cdktf.json`**: `"notifications": [...]` applied to
   every stack.

A notification target is a small discriminated union, not just an ARN, so the
model is cloud-neutral from day one:

```jsonc
"notifications": [
  { "type": "aws-sns",        "topicArn": "arn:aws:sns:us-east-1:123456789012:deploys" },
  { "type": "gcp-pubsub",     "topic": "projects/p/topics/deploys" },
  { "type": "azure-eventgrid","topicEndpoint": "https://t.westeurope-1.eventgrid.azure.net/api/events" },
  { "type": "webhook",        "url": "https://…", "secret": "${env:DEPLOY_HOOK_SECRET}" }
]
```

Bare ARN strings are accepted as shorthand for `aws-sns` so
`--notification-arn` and CDK's `notificationArns` map 1:1.

### 2. Event source — two tiers

- **Tier A (no CLI behaviour change, ships first):** subscribe to the existing
  `TerraformDeployState` callback (`terraform.ts:147-166`) and translate
  `DeployingResource.applyState` transitions into events. Address, action and
  timing are available; `PhysicalResourceId` and reasons are not.
- **Tier B (full fidelity):** run `apply` with the machine-readable stream —
  OpenTofu ≥ 1.12: `-json-into=<fifo>` keeps the interactive pty UI intact;
  Terraform / older OpenTofu: `-json` on a **saved plan** (`plan -out` →
  approval on the rendered plan → `apply -json <planfile>`), which also removes
  the pty text-parsing the deploy machine relies on today. Parse with the
  existing `schema.ts` union. Tier B is opt-in until the deploy machine's
  approval flow is ported to saved plans.

Both tiers feed one `StackEventBus` in cli-core; sinks never see raw Terraform
lines.

### 3. Event model — CloudFormation-shaped, with Terrain extensions

```jsonc
{
  "StackId": "arn:aws:cloudformation:us-east-1:123456789012:stack/prod/…",   // cfncompat rule
  "StackName": "prod",
  "EventId": "prod-000042",                        // per-stack sequence
  "LogicalResourceId": "aws_s3_bucket.data",       // Terraform address
  "PhysicalResourceId": "my-data-bucket",          // hook.id_value when known
  "ResourceType": "aws_s3_bucket",
  "ResourceStatus": "CREATE_COMPLETE",
  "ResourceStatusReason": null,
  "Timestamp": "2026-08-29T09:12:53Z",
  "ClientRequestToken": "run-…",
  "Terrain": { "action": "create", "provider": "registry.terraform.io/hashicorp/aws",
               "elapsedSeconds": 4.2, "tool": "tofu 1.12.1", "tier": "B" }
}
```

Stack-level bookends (`CREATE_IN_PROGRESS` / `UPDATE_IN_PROGRESS` at start,
`*_COMPLETE` / `*_FAILED` at end, `DELETE_*` for destroy) are synthesized by the
engine; `ResourceStatus` values are the CloudFormation vocabulary so existing
SNS→Slack/EventBridge consumers work unchanged. SNS message attributes
(`StackName`, `ResourceStatus`, `ResourceType`) enable subscription filtering;
FIFO topics use `StackId` as the message group.

### 4. Sinks — pluggable, ambient credentials, never fail the deploy

`INotificationSink { publish(event): Promise<void> }` in cli-core with
implementations: `aws-sns` (`@aws-sdk/client-sns` `Publish`), `gcp-pubsub`
(`@google-cloud/pubsub`), `azure-eventgrid` (`@azure/eventgrid`), `webhook`
(HMAC-signed JSON POST), `file`/`stdout` (tests, CI artefacts). Credentials are
the CLI's ambient ones (same chain the providers use). Delivery is
at-least-once, ordered per stack, buffered with bounded retry; a sink failure
is an `Annotations` warning, never an apply failure (softer than CloudFormation,
which rejects an invalid topic — deliberately, because a notifier outage must
not block infrastructure changes).

### 5. Bridge and provider alignment

- The AWS CDK bridge writes `StackProps.notificationArns` to the manifest (§1.2)
  **and** to `data.cfncompat_pseudo_parameters.<stack>.notification_arns`; the
  engine's `StackId` uses the same deterministic rule as cfncompat, so events
  and `cfncompat_custom_resource` requests carry one identity.
- cfncompat keeps no delivery code (RFC 006 §2.3b stands).

### 6. TACOS

When CDKTN runs under HCP Terraform, Spacelift, env0 or a Kubernetes operator,
the engine emits the same events; the platform's run-level webhooks remain
complementary (F3). A TACOS wanting to expose "notification ARNs" in its UI
only needs to pass them to `cdktn deploy --notification-arn` — no new event
plumbing.

## Requirements

1. **R1 — Provider-neutral target model** (§1) accepted from CLI flag, stack
   manifest metadata and `cdktn.json`, with bare-ARN shorthand for SNS.
2. **R2 — `StackEventBus` + Tier A source** built on the existing
   `TerraformDeployState` callback (F2), emitting the CloudFormation-shaped
   event (§3) with synthesized stack bookends.
3. **R3 — `aws-sns` sink** first; `webhook` and `file` alongside for testing;
   failures warn, never fail (§4).
4. **R4 — Tier B `-json` source** behind a flag; `-json-into` on OpenTofu ≥ 1.12,
   saved-plan `apply -json` elsewhere; parsed with `schema.ts` (F1, F2).
5. **R5 — Bridge alignment**: `notificationArns` → manifest + pseudo-parameter
   data source; shared `StackId` rule (F5).
6. **R6 — `gcp-pubsub` and `azure-eventgrid` sinks** after R3 stabilises;
   same event payload.
7. **R7 — Docs**: a "Stack notifications" concept page mapping CloudFormation
   stack events to Terrain events, listing what cannot be reproduced (F4).

## Open questions

- Should `LogicalResourceId` be the Terraform address or, for bridged CDK
  stacks, the CloudFormation logical id (the bridge has the map)? Proposal:
  Terraform address, with `Terrain.cdkLogicalId` when known.
- Plan-phase events (`planned_change`, `resource_drift`) as `REVIEW_IN_PROGRESS`-
  style notifications, or apply-only in v1? Proposal: apply-only, drift later.
- Where do secrets for `webhook` live (`cdktn.json` env interpolation vs CLI
  env only)?
- Does Tier B's saved-plan flow become the default deploy path (it would also
  fix the pty text-parsing fragility), or stay opt-in?

## Effort

- **cli-core:** target model + `StackEventBus` + Tier A adapter + SNS/webhook/
  file sinks (~one PR); Tier B `-json` source (second PR, touches the deploy
  state machine).
- **cdktn (core):** stack metadata property → manifest (small).
- **Bridge:** map `notificationArns` (small, alongside the RFC 006 pseudo work).
- **Docs:** one concept page.
- **Deferred:** GCP/Azure sinks, drift/plan events, CDK logical-id mapping.

## Sources

- `@cdktn/cli-core` — `src/lib/models/schema.ts` (JSON UI zod schemas),
  `models/deploy-machine.ts:383-415` (apply invocation), `models/terraform.ts:22-29,131-170`
  (`DeployingResource`, `Terraform.deploy` callback), `cdktf-stack.ts:28-70`
- `terraform-provider-cfncompat` — RFC 006 §2.2/§2.3/§2.3b (`notification_arns` echo,
  deterministic `stack_id`, plugin-protocol limitation)
- `aws-cdk-lib` — `core/lib/stack.ts:510-516,814`, `core/lib/cfn-pseudo.ts:24`
- Terraform machine-readable UI — https://developer.hashicorp.com/terraform/internals/machine-readable-ui
- OpenTofu machine-readable UI / `-json-into` — https://opentofu.org/docs/internals/machine-readable-ui/,
  https://opentofu.org/blog/opentofu-1-12-0/, https://opentofu.org/blog/dual-command-output-streams/
- OpenTofu tracing status — https://github.com/opentofu/opentofu/issues/4102
- Plugin protocol — https://developer.hashicorp.com/terraform/plugin/terraform-plugin-protocol
- Terraform 1.14 actions — https://developer.hashicorp.com/terraform/language/invoke-actions
- CloudFormation stack events / `NotificationARNs` — https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_StackEvent.html,
  https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/pseudo-parameter-reference.html
- Platform notifications — HCP Terraform Notifications/Run Tasks, Spacelift webhooks,
  env0 notifications, Scalr webhooks, tofu-controller (URLs in the research notes)
