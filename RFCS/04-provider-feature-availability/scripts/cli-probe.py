#!/usr/bin/env python3
"""Runs a terraform / tofu binary with every candidate flag of every
flag-parsing command and records whether its flag parser ACCEPTS the flag.

Usage:
  python3 -I cli-probe.py <binary> <product> <version> <data-dir> \
      > data/cli-probe-<product>-<version>.json

Ground truth for cli-source-check.py. Candidates are every flag that any
data/cli-surface-*.json lists or any data/cli-source-check-*.json registers
for the command, in EITHER product and at any version (so product-only and
"since" claims are tested on the other product and older versions too).
The commands probed are the flag-parsing commands of this version's
data/cli-source-check-<product>-<version>.json. Each candidate runs as
`<bin> <cmd> -<flag>[=1] <positional args>` in a fresh empty directory, next
to a baseline run with a flag no version defines (-zzz-probe-bogus). An
output identical to the baseline with the bogus name replaced by the flag
name means "rejected" (the parser failed the same way); a different output
means the parser got past the flag ("accepted"). This needs no knowledge of each command's error
format (legacy commands print their help on a parse error, newer ones a
"flag provided but not defined" diagnostic).

Value flags are passed as `-flag=1` (VALUES for shaped ones), switches bare (kind from the source
check, else the help sweep). Positional args (POSITIONAL) are dummies that
make each command get past argument-count checks, so that an accepted flag
reaches a different error than the parse failure.

Safety: HOME, TF_CLI_CONFIG_FILE, TF_DATA_DIR and the cwd point into a
throwaway directory, stdin is /dev/null, TF_INPUT=0, CHECKPOINT_DISABLE=1,
TF_CLI_ARGS* are removed, and `login` / `logout` / `stacks` / `rpcapi` are
not probed (credentials / external plugin).
"""
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

BOGUS = "-zzz-probe-bogus"
TIMEOUT_S = 30
# login/logout: credentials; stacks/rpcapi: external plugin / machine
# interface; push: removed command that errors before looking at its args;
# parents print their help without parsing flags
SKIP = {"login", "logout", "stacks", "rpcapi", "push", "env", "workspace", "state", "providers", "metadata"}
# flags whose value has a required shape (OpenTofu 1.11-1.12 match the
# literal prefix "-deprecation=module:")
VALUES = {"-deprecation": "module:all", "-lock-timeout": "1s"}
# legacy commands print only their help on ANY parse error, so an invalid
# value would look like a rejected flag: durations get a valid duration
DURATION_KINDS = {"DurationVar", "Duration"}
POSITIONAL = {
    "import": ["null_resource.probe", "probe-id"],
    "state mv": ["null_resource.a", "null_resource.b"], "state move": ["null_resource.a", "null_resource.b"],
    "state rm": ["null_resource.a"], "state remove": ["null_resource.a"],
    "state show": ["null_resource.a"],
    "state push": ["probe-missing.tfstate"],
    "state replace-provider": ["hashicorp/a", "hashicorp/b"],
    "taint": ["null_resource.a"], "untaint": ["null_resource.a"],
    "force-unlock": ["probe-lock-id"],
    "providers mirror": ["probe-mirror"],
    "workspace new": ["probe"], "workspace select": ["probe"], "workspace delete": ["probe"],
    "env new": ["probe"], "env select": ["probe"], "env delete": ["probe"],
}


def run(binary, args, work):
    if os.path.exists(work):
        shutil.rmtree(work)
    os.makedirs(os.path.join(work, "cwd"))
    home = os.path.join(work, "home")
    os.makedirs(home)
    cfg = os.path.join(work, "cli.tfrc")
    open(cfg, "w").close()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TF_", "TOFU_"))}
    env.update({"HOME": home, "TF_CLI_CONFIG_FILE": cfg, "TF_DATA_DIR": os.path.join(work, "data"),
                "TF_INPUT": "0", "CHECKPOINT_DISABLE": "1", "TF_IN_AUTOMATION": "1"})
    try:
        p = subprocess.run([binary, *args], cwd=os.path.join(work, "cwd"), env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=TIMEOUT_S)
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return "timeout", ""


def norm(out, work):
    return out.replace(work, "<WORK>")


def main():
    binary, product, version, data = sys.argv[1:5]
    with open(os.path.join(data, f"cli-source-check-{product}-{version}.json")) as f:
        check = json.load(f)
    candidates = {}  # cmd -> flag -> takes_value guesses
    for name in sorted(os.listdir(data)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(data, name)) as f:
            if name.startswith("cli-surface-"):
                for cmd, e in json.load(f)["commands"].items():
                    for fl in e.get("flags", []):
                        candidates.setdefault(cmd, {}).setdefault(fl["name"], set()).add(fl["takes_value"])
            elif name.startswith("cli-source-check-"):
                for cmd, e in json.load(f)["flags"].items():
                    for r in e.get("source", []):
                        candidates.setdefault(cmd, {}).setdefault(r["name"], set()).add(r["takes_value"])
    commands = [c for c, e in check["flags"].items()
                if "error" not in e and e.get("parses_flags") and c not in SKIP]
    root = tempfile.mkdtemp(prefix=f"cli-probe-{product}-{version}-")
    jobs = []
    for cmd in sorted(commands):
        src = {r["name"]: r for r in check["flags"][cmd]["source"]}
        for name, guesses in sorted(candidates.get(cmd, {}).items()):
            if name in ("-help", "-h"):
                continue
            takes = src[name]["takes_value"] if name in src else any(guesses)
            value = VALUES.get(name) or ("1s" if name in src and src[name]["kind"] in DURATION_KINDS else "1")
            jobs.append((cmd, name, value if takes else None))
    baseline = {}

    def probe(job, idx):
        cmd, name, value = job
        work = os.path.join(root, f"w{idx}")
        args = cmd.split() + [name + ("=" + value if value is not None else "")] + POSITIONAL.get(cmd, [])
        code, out = run(binary, args, work)
        shutil.rmtree(work, ignore_errors=True)
        return job, code, norm(out, work)

    # baselines first (one per command)
    for i, cmd in enumerate(sorted(commands)):
        work = os.path.join(root, f"b{i}")
        code, out = run(binary, cmd.split() + [BOGUS] + POSITIONAL.get(cmd, []), work)
        baseline[cmd] = (code, norm(out, work))
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=int(os.environ.get("PROBE_PARALLELISM", "8"))) as ex:
        futs = []
        for i, job in enumerate(jobs):
            futs.append(ex.submit(probe, job, i))
        for fu in concurrent.futures.as_completed(futs):
            (cmd, name, _), code, out = fu.result()
            b_code, b_out = baseline[cmd]
            # what a parse failure on THIS flag looks like: the baseline with
            # the bogus name replaced by the flag name (exact, so help text
            # that mentions the flag elsewhere cannot cause a false match)
            b_out = b_out.replace(BOGUS.lstrip("-"), name.lstrip("-"))
            if code == "timeout":
                verdict = "timeout"
            elif (code, out) == (b_code, b_out):
                verdict = "rejected"
            else:
                verdict = "accepted"
            results.setdefault(cmd, {})[name] = verdict
    shutil.rmtree(root, ignore_errors=True)
    out = {"product": product, "version": version, "method": "differential vs " + BOGUS,
           "commands": {c: dict(sorted(v.items())) for c, v in sorted(results.items())}}
    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
