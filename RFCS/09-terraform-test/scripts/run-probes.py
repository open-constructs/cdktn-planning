#!/usr/bin/env python3
"""Runs every fixture/probes/* against one CLI binary and prints a JSON digest.

usage: run-probes.py <binary> <product> <version> <workdir> <plugin-cache>

Each probe is a minimal test file exercising exactly one test-framework
feature. A probe counts as "supported" when `<binary> test -json` exits 0 AND
reports at least one passed run (so an ignored/undiscovered file is not a pass).
Probe layout: tests/ -> <work>/tests, root/ -> <work>/, module/ replaces the
default fixture/module, `flags` adds CLI flags, `expect-file` must exist after.
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
binary, product, version, work, cache = sys.argv[1:6]
env = dict(os.environ, TF_PLUGIN_CACHE_DIR=cache, TF_IN_AUTOMATION="1",
           TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE="1")


def run(args, cwd):
    p = subprocess.run([binary, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout, p.stderr


def first_error(stdout, stderr):
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        d = ev.get("diagnostic")
        if d and d.get("severity") == "error":
            return (d.get("summary", "") + ": " + d.get("detail", "")).strip()[:400]
    text = (stderr or stdout).strip()
    return text[:400] if text else None


results = {}
probes_dir = os.path.join(ROOT, "fixture", "probes")
for name in sorted(os.listdir(probes_dir)):
    probe = os.path.join(probes_dir, name)
    wd = os.path.join(work, name)
    shutil.rmtree(wd, ignore_errors=True)
    module = os.path.join(probe, "module")
    shutil.copytree(module if os.path.isdir(module) else os.path.join(ROOT, "fixture", "module"), wd)
    if os.path.isdir(os.path.join(probe, "root")):
        shutil.copytree(os.path.join(probe, "root"), wd, dirs_exist_ok=True)
    shutil.copytree(os.path.join(probe, "tests"), os.path.join(wd, "tests"))
    flags = open(os.path.join(probe, "flags")).read().split() if os.path.exists(os.path.join(probe, "flags")) else []

    code, out, err = run(["init", "-backend=false", "-input=false", "-no-color"], wd)
    if code != 0:
        results[name] = {"supported": False, "phase": "init", "exit": code, "error": (err or out).strip()[:400]}
        continue

    code, out, err = run(["test", "-json", *flags], wd)
    summary, types = None, set()
    for line in out.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        types.add(ev.get("type"))
        if ev.get("type") == "test_summary":
            summary = ev["test_summary"]
    supported = code == 0 and bool(summary) and summary.get("passed", 0) >= 1
    expect_status = os.path.join(probe, "expect-status")
    if os.path.exists(expect_status):  # behavioural probe: "supported" = the run ends in this status
        supported = bool(summary) and summary.get("status") in open(expect_status).read().strip().split("|")
    expect_file = os.path.join(probe, "expect-file")
    if supported and os.path.exists(expect_file):
        supported = os.path.exists(os.path.join(wd, open(expect_file).read().strip()))
    results[name] = {"supported": supported, "phase": "test", "exit": code, "summary": summary,
                     "json_events": sorted(t for t in types if t)}
    if not supported:
        results[name]["error"] = first_error(out, err)
    shutil.rmtree(wd, ignore_errors=True)

json.dump({"product": product, "version": version, "probes": results}, sys.stdout, indent=2, sort_keys=True)
print()
