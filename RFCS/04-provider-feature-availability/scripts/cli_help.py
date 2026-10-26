#!/usr/bin/env python3
"""Enumerates and parses the CLI command / flag surface of one terraform or
tofu binary from its `-help` output.

Usage: python3 -I cli_help.py <binary> <product> <version> > cli-surface.json

The binary is run directly (cli-sweep.sh resolves its path once through
`mise exec <product>@<version> -- sh -c 'command -v <exe>'`, which avoids a
mise shim round-trip for each of the ~50 help invocations per version).

Help text is written for humans and its layout drifts between releases, so
the parser is deliberately explicit and line-oriented:

  * A line at column 0 is a SECTION HEADING ("Usage: ...", "Options:",
    "Plan Customization Options:", "Main commands:", "All other commands:",
    "Subcommands:", "Global options (...)"). The heading decides how the
    indented lines below it are read.
  * In a command-list section (main / all other / subcommands), an indented
    line `  <name>  <description>` (two or more spaces between) is an entry.
  * In any other section, an indented line whose first token starts with
    `-<letter>` is a FLAG LINE when its indent is <= the indent of the first
    flag line in that section:
        -name                      switch (boolean, no value shown)
        -name=true|false           boolean shown with its non-default value
        -name=PLACEHOLDER          takes a value
        -name 'foo=bar' / -name X  takes a value (space-separated placeholder)
        -a, -b                     aliases (comma-separated flag tokens)
    followed by two or more spaces and the description (or end of line).
    Deeper-indented lines after a flag line are description continuations.
  * A bracketed all-caps tag after the name ("-x [EXPERIMENTAL]") is a
    description prefix, not a placeholder: the flag is recorded as a switch
    (help shows no value) and build-cli-matrix.py takes kind / takes_value
    from the source check where one exists.
  * The legacy-flag prose line "-state, state-out, and -backup are legacy
    options ..." declares those three flags ("from": "legacy-prose").
  * Everything else inside a section is prose. Prose lines that mention a
    `-flag` token (e.g. "-state, state-out, and -backup are legacy options")
    are recorded as `prose_flag_mentions` and also logged as UNPARSED, so a
    layout change that hides a flag inside prose cannot go unnoticed.

Every line that is neither blank, a heading, a list entry, a flag line, a
continuation, nor plain section prose is reported in `unparsed` per command
(and on stderr), so drift in the help layout is visible in the sweep log.
"""
import json
import os
import re
import subprocess
import sys

PARSER_VERSION = 2
MAX_DEPTH = 3
TIMEOUT_S = 30
DESC_LIMIT = 240

# Commands whose help is not part of the binary's own surface: `stacks`
# (Terraform >= 1.13) downloads and execs the separately versioned HCP
# Terraform stacks plugin on `-help`; `rpcapi` is a hidden machine interface.
NO_RECURSE = {"stacks", "rpcapi"}

DEPRECATION_RE = re.compile(
    r"\b(deprecated|deprecation warning|legacy|no longer (?:supported|used|has any effect)"
    r"|will be removed|obsolete)\b",
    re.I,
)
HEADING_RE = re.compile(r"^\S.*$")
LIST_ENTRY_RE = re.compile(r"^(\s+)([a-z][a-z0-9-]*)(?:\s{2,}(.*))?$")
FLAG_TOKEN = r"-[A-Za-z][A-Za-z0-9_-]*"
FLAG_LINE_RE = re.compile(
    r"^(?P<indent>\s+)"
    r"(?P<flags>" + FLAG_TOKEN + r"(?:,\s*" + FLAG_TOKEN + r")*)"
    r"(?P<value>=\S+|\s'[^']*'|\s\"[^\"]*\"|\s[A-Za-z<\[][^\s]*)?"
    r"(?:\s{2,}(?P<desc>\S.*))?\s*$"
)
# apply/destroy help pages that delegate their plan options to `plan -help`
# instead of listing them ("... accepted by the terraform plan command",
# "terraform plan -help")
REFERS_TO_PLAN_RE = re.compile(
    r"(?:terraform|tofu) plan -help|plan-customization options accepted by the (?:terraform|tofu) plan command",
    re.I,
)
# Fallback for flag lines whose description is separated by a single space
# ("-var-file=filename Load variable values ...", OpenTofu 1.8-1.10 when the
# column overflowed). Only tried at the section's flag indent; such flags are
# marked "loose": true.
FLAG_LINE_LOOSE_RE = re.compile(
    r"^(?P<indent>\s+)(?P<flags>" + FLAG_TOKEN + r")(?P<value>=\S+)?\s(?P<desc>[A-Z(\"'].*)$"
)
# destroy help pages that only say "This command is a convenience alias for:
# terraform apply -destroy" (all apply flags apply)
REFERS_TO_APPLY_RE = re.compile(r"alias for:?\s+(?:terraform|tofu) apply -destroy", re.I)
MENTION_RE = re.compile(r"(?<![\w-])(-{1,2}[a-z][a-z0-9-]+)")
# Terraform import / refresh / taint / untaint (and others) name their
# legacy local-backend flags only in a prose line:
#   "-state, state-out, and -backup are legacy options supported for the local"
# (note the missing dash on state-out). Recorded as flags with
# "from": "legacy-prose".
LEGACY_PROSE_RE = re.compile(
    r"^\s+(?P<list>-[a-z][a-z0-9-]*(?:,?\s+(?:and\s+)?-?[a-z][a-z0-9-]*)+)\s+are legacy options\b"
)
# A bracketed all-caps tag after the flag name is a description prefix, not
# a value placeholder ("-state-provider-lock-file [EXPERIMENTAL]").
TAG_PLACEHOLDER_RE = re.compile(r"^\[[A-Z][A-Z -]*\]$")


def run_help(binary, args, cwd):
    env = dict(os.environ)
    env["CHECKPOINT_DISABLE"] = "1"
    env.pop("TF_CLI_ARGS", None)
    try:
        p = subprocess.run(
            [binary, *args, "-help"],
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=TIMEOUT_S,
        )
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return -1, ""


def classify_heading(line):
    low = line.lower()
    if low.startswith("usage"):
        return "usage"
    if low.startswith(("main commands", "common commands", "primary commands")):
        return "commands-main"
    if low.startswith("all other commands"):
        return "commands-other"
    if re.match(r"sub-?commands", low):
        return "subcommands"
    if low.startswith("global options"):
        return "options-global"
    if "option" in low or "flag" in low:
        return "options"
    return "prose"


def parse_value(raw):
    """-> (kind, placeholder) for the token after the flag name."""
    if not raw:
        return "switch", None
    raw = raw.strip()
    if raw.startswith("="):
        ph = raw[1:]
        if ph in ("true", "false"):
            return "bool", ph
        return "value", ph
    return "value", raw.strip("'\"")


def parse_help(text):
    """Parses one help page. Returns a dict (see module docstring)."""
    out = {
        "usage": None,
        "description": [],
        "commands": [],  # (name, desc, section) for command-list sections
        "flags": [],
        "prose_flag_mentions": [],
        "unparsed": [],
    }
    section = None
    heading = None
    flag_indent = None
    current = None  # flag dict receiving continuation lines
    cur_list = None
    for raw in text.expandtabs(8).splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if HEADING_RE.match(line):
            section = classify_heading(line)
            heading = line.rstrip(":").strip()
            flag_indent = None
            current = None
            cur_list = None
            if section == "usage":
                out["usage"] = line.split(":", 1)[1].strip() if ":" in line else line
            continue
        if section is None or section == "usage":
            # description paragraphs under the usage line
            out["description"].append(line.strip())
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if section in ("commands-main", "commands-other", "subcommands"):
            m = LIST_ENTRY_RE.match(line)
            if m and (cur_list is None or indent <= cur_list):
                cur_list = indent if cur_list is None else cur_list
                out["commands"].append(
                    {"name": m.group(2), "desc": (m.group(3) or "").strip(), "section": section}
                )
                continue
            if cur_list is not None and indent > cur_list and out["commands"]:
                out["commands"][-1]["desc"] += " " + stripped
                continue
            out["unparsed"].append(line)
            continue

        # option / prose sections
        is_flag_candidate = stripped.startswith("-") and re.match(r"-[A-Za-z]", stripped)
        if is_flag_candidate and (flag_indent is None or indent <= flag_indent):
            m = FLAG_LINE_RE.match(line)
            loose = False
            if not m and (flag_indent is None or indent == flag_indent):
                m = FLAG_LINE_LOOSE_RE.match(line)
                loose = bool(m)
            if m:
                flag_indent = indent if flag_indent is None else flag_indent
                names = [t.strip() for t in m.group("flags").split(",")]
                value, desc = m.group("value"), (m.group("desc") or "").strip()
                if value and TAG_PLACEHOLDER_RE.match(value.strip()):
                    desc = (value.strip() + " " + desc).strip()
                    value = None
                kind, ph = parse_value(value)
                current = {
                    "name": names[0],
                    "aliases": names[1:],
                    "kind": kind,
                    "takes_value": kind == "value",
                    "placeholder": ph,
                    "section": heading,
                    "desc": desc,
                }
                if loose:
                    current["loose"] = True
                out["flags"].append(current)
                continue
        if current is not None and flag_indent is not None and indent > flag_indent:
            current["desc"] = (current["desc"] + " " + stripped).strip()
            continue
        lm = LEGACY_PROSE_RE.match(line)
        if lm and section != "prose":
            names = ["-" + t.lstrip("-") for t in re.split(r",?\s+(?:and\s+)?", lm.group("list")) if t]
            known = {f["name"] for f in out["flags"]}
            for name in names:
                if name in known:
                    continue
                out["flags"].append({
                    "name": name, "aliases": [], "kind": "value", "takes_value": True,
                    "placeholder": None, "section": heading, "desc": stripped, "from": "legacy-prose",
                })
            current = None
            continue
        mentions = MENTION_RE.findall(stripped)
        if mentions and section != "prose":
            out["prose_flag_mentions"].append({"line": stripped, "flags": mentions, "section": heading})
            out["unparsed"].append(line)
            current = None
            continue
        # plain section prose (e.g. the paragraph under "Plan Customization
        # Options:") — recorded, not an error
        current = None
        if section == "prose" or not is_flag_candidate:
            out["description"].append(stripped)
            continue
        out["unparsed"].append(line)

    for f in out["flags"]:
        f["deprecation_markers"] = sorted({m.lower() for m in DEPRECATION_RE.findall(f["desc"])})
        if len(f["desc"]) > DESC_LIMIT:
            f["desc"] = f["desc"][: DESC_LIMIT - 1] + "…"
    out["description"] = " ".join(out["description"])[:DESC_LIMIT]
    return out


def flag_record(f):
    rec = {k: f[k] for k in ("name", "aliases", "kind", "takes_value", "placeholder",
                             "section", "deprecation_markers", "desc")}
    if f.get("loose"):
        rec["loose"] = True
    if f.get("from"):
        rec["from"] = f["from"]
    return rec


def main():
    binary, product, version = sys.argv[1:4]
    cwd = os.environ.get("CLI_SWEEP_CWD") or os.getcwd()
    code, top_text = run_help(binary, [], cwd)
    # `<bin> -help` on its own (no subcommand) — top-level page
    top = parse_help(top_text)
    result = {
        "product": product,
        "version": version,
        "parser_version": PARSER_VERSION,
        "global_options": [flag_record(f) for f in top["flags"]],
        "top_level": [
            {"name": c["name"], "section": c["section"].replace("commands-", ""), "desc": c["desc"]}
            for c in top["commands"]
        ],
        "commands": {},
        "unparsed": {},
    }
    if top["unparsed"]:
        result["unparsed"][""] = top["unparsed"]
    if not top["commands"]:
        print(f"FATAL {product} {version}: no commands parsed from top-level help", file=sys.stderr)
        sys.exit(2)

    queue = [([c["name"]], c["section"]) for c in top["commands"]]
    seen = set()
    while queue:
        path, listed_in = queue.pop(0)
        key = " ".join(path)
        if key in seen:
            continue
        seen.add(key)
        entry = {"listed_in": listed_in.replace("commands-", "")}
        if path[0] in NO_RECURSE:
            entry["not_swept"] = "external plugin / machine interface; help not part of the binary surface"
            result["commands"][key] = entry
            continue
        code, text = run_help(binary, path, cwd)
        page = parse_help(text)
        entry.update({
            "help_exit_code": code,
            "usage": page["usage"],
            "description": page["description"],
            "subcommands": [c["name"] for c in page["commands"] if c["section"] == "subcommands"],
            "flags": [flag_record(f) for f in page["flags"]],
        })
        # flags that only appear in the usage line ("providers schema -json",
        # "metadata functions -json", "state identities [options] -json")
        usage_rest = (page["usage"] or "").replace("[global options]", "")
        listed = {f["name"] for f in entry["flags"]}
        for tok in re.findall(r"(?<![\w-])(-[a-z][a-z0-9-]*)", usage_rest):
            if tok not in listed:
                listed.add(tok)
                entry["flags"].append({
                    "name": tok, "aliases": [], "kind": "switch", "takes_value": False,
                    "placeholder": None, "section": "Usage", "deprecation_markers": [], "desc": "",
                })
        flat = " ".join(text.split())
        if path == ["destroy"] and REFERS_TO_APPLY_RE.search(flat):
            entry["help_refers_to"] = "apply"
        elif path[0] in ("apply", "destroy") and REFERS_TO_PLAN_RE.search(flat):
            entry["help_refers_to"] = "plan"
        if page["prose_flag_mentions"]:
            entry["prose_flag_mentions"] = page["prose_flag_mentions"]
        if page["usage"] is None:
            entry["help_missing"] = True
            print(f"NO-USAGE {product} {version} '{key}' exit={code}: {text[:160]!r}", file=sys.stderr)
        if page["unparsed"]:
            result["unparsed"][key] = page["unparsed"]
            for line in page["unparsed"]:
                print(f"UNPARSED {product} {version} '{key}': {line.strip()}", file=sys.stderr)
        result["commands"][key] = entry
        if len(path) < MAX_DEPTH:
            for sub in entry["subcommands"]:
                queue.append((path + [sub], "subcommands"))

    result["counts"] = {
        "commands": len(result["commands"]),
        "flags": sum(len(c.get("flags", [])) for c in result["commands"].values()),
        "global_options": len(result["global_options"]),
        "unparsed_lines": sum(len(v) for v in result["unparsed"].values()),
    }
    json.dump(result, sys.stdout, indent=1, sort_keys=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
