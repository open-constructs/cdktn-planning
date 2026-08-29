# stack-notifications

Draft proposal for CloudFormation `NotificationARNs` parity: per-resource
deployment events published from the **CDKTN CLI execution engine**
(`@cdktn/cli-core`) to AWS SNS (first), GCP Pub/Sub and Azure Event Grid — not
from a Terraform provider, which structurally cannot see the whole graph.

Follows cfncompat `v0.3.0`
([RFC 006](https://github.com/cdktn-io/terraform-provider-cfncompat/blob/main/RFCs/006-pseudo-parameter-polyfill.md)),
whose `cfncompat_pseudo_parameters.notification_arns` is echo-only by design.

| File | Purpose |
| --- | --- |
| `PROPOSAL.md` | Problem, findings (JSON UI stream, current cli-core seams, TACOS survey, CloudFormation field mapping), design (declaration, two event-source tiers, event model, sinks, bridge/TACOS alignment), requirements, open questions |

## Key conclusions

- The Terraform/OpenTofu `-json` UI stream (OpenTofu ≥ 1.12 `-json-into`) is the
  only stable per-resource signal; OTel tracing is experimental and no hooks
  RFC exists.
- `cli-core` already has zod schemas for that stream and a per-resource deploy
  callback, but `deploy` runs `apply` on a pty without `-json` today.
- No wrapper/TACOS exposes per-resource events; none is SNS-native — the engine
  is the right (and only) home, and a TACOS running CDKTN inherits it.
- Event payload uses CloudFormation `StackEvent` vocabulary so existing
  SNS→Slack/EventBridge consumers work unchanged; sinks never fail a deploy.
