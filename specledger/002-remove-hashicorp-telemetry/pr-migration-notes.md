# PR-body section: user-facing migration notes (002)

> Paste this section into the PR body (checkpoint finding #4 — spec.md
> Edge Cases requires the revived consent prompt to be called out in
> user-facing migration/release notes; release-please only surfaces
> commit subjects).

---

## ⚠️ Telemetry changes — what users will notice after upgrading

**cdktn no longer sends any data to HashiCorp.** The checkpoint
telemetry transport (`checkpoint-api.hashicorp.com`) has been removed
entirely. Usage analytics now go to the project's own Sentry, and only
when enabled (see below).

**New `sendUsageTelemetry` flag in `cdktf.json`.** It controls usage
analytics (command name, language, CI name, synth duration — no
hostname, no stack contents) independently of `sendCrashReports`.

**One-time interactive prompt on upgrade.** On the first run in an
interactive terminal (TTY, not CI), existing projects whose `cdktf.json`
lacks `sendUsageTelemetry` are asked once and the answer is persisted.
You may **also** be asked about crash reporting if `sendCrashReports`
is missing from your `cdktf.json`: that prompt existed before but never
fired due to a bug (a missing key was silently treated as "no"); it now
works as originally intended.

**Non-interactive runs (CI, piped) are unchanged.** No prompts; usage
telemetry stays on by default (as it always was, now routed to Sentry
instead of HashiCorp) and crash reporting stays off by default.

**`CHECKPOINT_DISABLE` keeps working.** It still disables usage
telemetry everywhere and still does not affect crash reporting. Telemetry
is also fully inert when the build has no Sentry DSN (e.g. self-built
binaries).

| Situation | Before | After |
|---|---|---|
| Usage data recipient | HashiCorp checkpoint API | Project's own Sentry |
| `sendUsageTelemetry` unset, interactive | sent silently (no prompt existed) | prompted once, choice saved |
| `sendUsageTelemetry` unset, CI/non-interactive | sent | sent (to Sentry) |
| `CHECKPOINT_DISABLE` set | no usage data | no usage data |
| `sendCrashReports` missing, interactive | treated as "no" (prompt was broken) | prompted once, choice saved |
| Machine hostname in crash reports | sent (Sentry default) | scrubbed (`serverName: cdktn-cli`) |
