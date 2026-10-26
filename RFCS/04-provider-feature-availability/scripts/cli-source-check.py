#!/usr/bin/env python3
"""Cross-checks a swept CLI surface (cli_help.py output) against the Go source.

Usage:
  python3 -I cli-source-check.py <ref-clone> <product> <version> <cli-surface.json>

<ref-clone> is a (blobless is fine) clone of hashicorp/terraform or
opentofu/opentofu; files are read with `git -C <ref> show v<version>:<path>`.

Two checks:

1. Commands: every key of the `Commands` map in commands.go
   (Terraform: ./commands.go, OpenTofu: ./cmd/tofu/commands.go), including
   entries registered only under `meta.AllowExperimentalFeatures` and the
   `HiddenCommands` / `hiddenCommands` set, against the commands the help
   sweep found.

2. Flags of plan / apply / init: starting from internal/command/<cmd>.go,
   follows the `arguments.Parse*` / `arguments.Bind*` calls into
   internal/command/arguments and every flag-set helper they call
   (Terraform: extendedFlagSet, defaultFlagSet, ParseView; OpenTofu:
   BindView / BindOperation / BindVars / BindState / BindBackend*), and
   collects every `<flagset>.<Kind>Var(..., "<name>", ...)` registration.
   Guards around a registration are evaluated where possible:
     - Terraform `if state != nil {` against the caller's arguments
       (`extendedFlagSet("init", nil, nil, init.Vars)` drops state/operation),
     - OpenTofu bit masks (`if mask&viewFlagLint != 0`) against the caller's
       mask expression, resolved through the package's `const` blocks,
     - boolean parameters passed as literals (`bindApply(cli, true)`).
   Unevaluable guards (`if experimentsEnabled {`) keep the flag and record
   the guard text. OpenTofu's `.SetHidden(true)` is recorded as `hidden`.
   Terraform's `ParseView` uses a `switch` on raw args; its `case "-x":`
   labels are collected as flags.

The flag list is then compared with the help sweep. For Terraform apply /
destroy the help page delegates plan options to `terraform plan -help`; the
"effective" help set adds the plan page's "Plan Customization Options".

The source files are an explicit, per-product list (SOURCE_FILES) rather than
a package scan, which keeps blob fetches from a blobless clone small; an
unresolved helper call is reported in `unresolved_calls`.
"""
import json
import re
import subprocess
import sys

# command -> (file stem under internal/command{,/arguments}, root filter).
# plan / apply / init are the required cross-check; the rest are the other
# commands cdktn invokes (see build-cli-matrix.py CDKTN_EMITTED).
CHECK_COMMANDS = {
    "plan": ("plan", None),
    "apply": ("apply", lambda r: not r.endswith("Destroy")),
    "destroy": ("apply", lambda r: r.endswith("Destroy") or r.startswith("ParseView")),
    "init": ("init", None),
    "providers lock": ("providers_lock", None),
    "providers schema": ("providers_schema", None),
    "output": ("output", None),
    "version": ("version", None),
}

SOURCE_FILES = {
    "terraform": {
        "commands": "commands.go",
        "helpers": [
            "internal/command/arguments/extended.go",
            "internal/command/arguments/default.go",
            "internal/command/arguments/view.go",
        ],
    },
    "opentofu": {
        "commands": "cmd/tofu/commands.go",
        "helpers": [
            "internal/command/arguments/extended.go",
            "internal/command/arguments/default.go",
            "internal/command/arguments/view.go",
            "internal/command/arguments/backend.go",
        ],
    },
}

FLAG_CALL_RE = re.compile(
    r"\b(\w+)\.(BoolVar|StringVar|IntVar|Int64Var|UintVar|Float64Var|DurationVar|StringArrayVar|"
    r"TextVar|Var|RawFlags|Func|BoolFunc|Bool|String|Int|Duration)\("
)
NAME_ARG_INDEX = {"Func": 0, "BoolFunc": 0, "Bool": 0, "String": 0, "Int": 0, "Duration": 0}
HELPER_CALL_RE = re.compile(
    r"(?<![\w.])(?:arguments\.)?(extendedFlagSet|defaultFlagSet|Parse[A-Z]\w*|Bind[A-Z]\w*|bind[A-Z]\w*)\("
)


def git_show(ref, tag, path):
    p = subprocess.run(["git", "-C", ref, "show", f"{tag}:{path}"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        return None
    return p.stdout.decode("utf-8", "replace")


def sanitize(src):
    """Blanks string literals and comments (same length, newlines kept)."""
    out = list(src)
    i, n = 0, len(src)

    def blank(a, b):
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            blank(i + 1, j)
            i = j + 1
        elif c == "`":
            j = src.find("`", i + 1)
            j = n if j < 0 else j
            blank(i + 1, j)
            i = j + 1
        else:
            i += 1
    return "".join(out)


def match_close(s, i, open_c, close_c):
    depth = 0
    for k in range(i, len(s)):
        if s[k] == open_c:
            depth += 1
        elif s[k] == close_c:
            depth -= 1
            if depth == 0:
                return k
    return len(s) - 1


def split_args(orig, san, a, b):
    """Top-level comma split of the call args between a and b (exclusive)."""
    args, depth, start = [], 0, a
    for k in range(a, b):
        ch = san[k]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(orig[start:k].strip())
            start = k + 1
    tail = orig[start:b].strip()
    if tail:
        args.append(tail)
    return args


class GoFile:
    def __init__(self, path, src):
        self.path = path
        self.src = src
        self.san = sanitize(src)
        self.funcs = {}
        for m in re.finditer(r"(?m)^func\s+(?:\([^)]*\)\s*)?(\w+)\(", self.san):
            name = m.group(1)
            p_open = m.end() - 1
            p_close = match_close(self.san, p_open, "(", ")")
            params = split_args(self.src, self.san, p_open + 1, p_close)
            # body: first "{" after the signature at paren depth 0
            k, depth = p_close + 1, 0
            while k < len(self.san):
                ch = self.san[k]
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                elif ch == "{" and depth == 0:
                    break
                k += 1
            b_close = match_close(self.san, k, "{", "}")
            self.funcs[name] = (params, k, b_close)

    def guards_at(self, start, pos):
        """Enclosing block headers between body start and pos (outer->inner)."""
        stack = []
        for k in range(start + 1, pos):
            ch = self.san[k]
            if ch == "{":
                line_start = self.san.rfind("\n", 0, k) + 1
                header = self.san[line_start:k].strip()
                hdr_orig = self.src[line_start:k].strip()
                stack.append(hdr_orig if header.startswith(("if ", "} else")) else None)
            elif ch == "}":
                if stack:
                    stack.pop()
        return [g for g in stack if g]


def parse_consts(files):
    consts = {}
    for f in files:
        for blk in re.finditer(r"(?ms)^const \((.*?)^\)", f.san):
            iota, prev = 0, None
            for line in f.src[blk.start(1):blk.end(1)].splitlines():
                line = line.split("//")[0].strip()
                if not line:
                    continue
                m = re.match(r"(\w+)(?:\s+\w+)?\s*=\s*(.+)$", line)
                if m:
                    name, expr = m.group(1), m.group(2)
                    prev = expr
                elif re.fullmatch(r"\w+", line) and prev is not None:
                    name, expr = line, prev
                else:
                    iota += 1
                    continue
                val = eval_mask(expr, consts, iota)
                if val is not None:
                    consts[name] = val
                iota += 1
    return consts


def eval_mask(expr, consts, iota=0):
    total = 0
    for tok in expr.replace("(", " ").replace(")", " ").split("|"):
        tok = tok.strip()
        if re.fullmatch(r"\d+", tok):
            total |= int(tok)
        elif re.fullmatch(r"1\s*<<\s*iota", tok):
            total |= 1 << iota
        elif tok in consts:
            total |= consts[tok]
        else:
            return None
    return total


def resolve_value(expr, caller_env):
    """caller_env: param -> arg text; also 'local:' assignments."""
    expr = expr.strip()
    if expr in caller_env.get("locals", {}):
        return caller_env["locals"][expr]
    if expr in caller_env.get("params", {}):
        return caller_env["params"][expr]
    return expr


def eval_guard(guard, env, consts):
    """True / False / None (unknown) for an `if ...` header."""
    neg = guard.startswith("} else")
    m = re.match(r"(?:\} else )?if\s+(.+?)\s*$", guard)
    if not m:
        return None
    cond = m.group(1)
    val = None
    mm = re.fullmatch(r"(\w+)\s*!=\s*nil", cond)
    if mm:
        arg = resolve_value(mm.group(1), env)
        val = None if arg == mm.group(1) else arg != "nil"
    mm = re.fullmatch(r"(\w+)\s*&\s*(\w+)\s*!=\s*0", cond)
    if mm:
        mask_expr = resolve_value(mm.group(1), env)
        mask = mask_expr if isinstance(mask_expr, int) else eval_mask(str(mask_expr), consts)
        bit = consts.get(mm.group(2))
        if mask is not None and bit is not None:
            val = bool(mask & bit)
    mm = re.fullmatch(r"(!?)(\w+)", cond)
    if mm:
        arg = resolve_value(mm.group(2), env)
        if arg in ("true", "false"):
            val = (arg == "true") != bool(mm.group(1))
    if val is None:
        return None
    return (not val) if neg else val


def local_masks(f, fname, env, consts):
    """Mask-typed locals assigned in a function (`viewFlags := viewFlagAll`)."""
    params, b_open, b_close = f.funcs[fname]
    out = {}
    body = f.src[b_open:b_close]
    for m in re.finditer(r"(?m)^\s*(\w+)\s*(?::=|=)\s*(.+)$", body):
        name, expr = m.group(1), m.group(2).strip()
        expr = re.sub(rf"^{name}\s*\|\s*", "", expr)
        val = eval_mask(expr, consts)
        if val is None:
            continue
        guards = f.guards_at(b_open, b_open + m.start())
        ok = all(eval_guard(g, env, consts) is not False for g in guards)
        if ok:
            out[name] = out.get(name, 0) | val
    return out


def collect(fname, files, env, consts, origin_guards, seen, result, unresolved, depth=0):
    f = next((x for x in files if fname in x.funcs), None)
    if f is None:
        unresolved.add(fname)
        return
    if (fname, json.dumps(env.get("params", {}), sort_keys=True)) in seen or depth > 6:
        return
    seen.add((fname, json.dumps(env.get("params", {}), sort_keys=True)))
    params, b_open, b_close = f.funcs[fname]
    env = dict(env)
    env["locals"] = local_masks(f, fname, env, consts)

    # Terraform ParseView: manual switch over raw args
    for m in re.finditer(r'case\s+"(-[a-z][a-z0-9-]*)"', f.src[b_open:b_close]):
        result.append({"name": m.group(1), "origin": f"{f.path}:{fname}", "guards": origin_guards,
                       "hidden": False, "kind": "manual-switch"})

    for m in FLAG_CALL_RE.finditer(f.san, b_open, b_close):
        recv, kind = m.group(1), m.group(2)
        p_open = m.end() - 1
        p_close = match_close(f.san, p_open, "(", ")")
        args = split_args(f.src, f.san, p_open + 1, p_close)
        idx = NAME_ARG_INDEX.get(kind, 1)
        if len(args) <= idx or not re.fullmatch(r'"[a-z][a-z0-9-]*"', args[idx]):
            continue
        # method chain: ).SetDisplay("=x").SetHidden(true)...
        chain = []
        k = p_close + 1
        while True:
            cm = re.match(r"\.(\w+)\(", f.san[k:])
            if not cm:
                break
            c_open = k + cm.end() - 1
            c_close = match_close(f.san, c_open, "(", ")")
            chain.append((cm.group(1), f.src[c_open + 1:c_close].strip()))
            k = c_close + 1
        guards = f.guards_at(b_open, m.start())
        evals = [eval_guard(g, env, consts) for g in guards]
        if any(v is False for v in evals):
            continue
        unknown = [g for g, v in zip(guards, evals) if v is None]
        rec = {
            "name": "-" + args[idx].strip('"'),
            "origin": f"{f.path}:{fname}",
            "guards": origin_guards + unknown,
            "hidden": any(c == "SetHidden" and a == "true" for c, a in chain),
            "kind": kind,
        }
        disp = [a for c, a in chain if c == "SetDisplay"]
        if disp:
            rec["display"] = disp[0].strip('"')
        result.append(rec)

    for m in HELPER_CALL_RE.finditer(f.san, b_open, b_close):
        callee = m.group(1)
        if callee == fname:
            continue
        p_open = m.end() - 1
        p_close = match_close(f.san, p_open, "(", ")")
        args = split_args(f.src, f.san, p_open + 1, p_close)
        guards = f.guards_at(b_open, m.start())
        evals = [eval_guard(g, env, consts) for g in guards]
        if any(v is False for v in evals):
            continue
        unknown = [g for g, v in zip(guards, evals) if v is None]
        cf = next((x for x in files if callee in x.funcs), None)
        if cf is None:
            if callee.startswith(("extendedFlagSet", "defaultFlagSet", "Bind", "bind", "ParseView")):
                unresolved.add(callee)
            continue
        # parameter names only ("cli *CommandLine" -> "cli")
        names = []
        for p in cf.funcs[callee][0]:
            names.append(p.split()[0])
        cenv = {"params": {}}
        for pname, aval in zip(names, args):
            v = resolve_value(aval, env)
            cenv["params"][pname] = v
        collect(callee, files, cenv, consts, origin_guards + unknown, seen, result, unresolved, depth + 1)


def source_commands(ref, tag, path):
    src = git_show(ref, tag, path) or ""
    cmds, experimental, hidden = [], [], []
    for m in re.finditer(r'(?m)^\s*"([a-z0-9][a-z0-9 -]*)":\s*(?:func\(|[\w.]+\()', src):
        cmds.append(m.group(1))
    for m in re.finditer(r'Commands\["([a-z0-9 -]+)"\]\s*=', src):
        experimental.append(m.group(1))
    hm = re.search(r"(?s)[hH]iddenCommands = map\[string\]struct\{\}\{(.*?)\n\t\}", src)
    if hm:
        hidden = re.findall(r'"([a-z0-9 -]+)"', hm.group(1))
    return sorted(set(cmds)), sorted(set(experimental)), sorted(set(hidden))


def main():
    ref, product, version, surface_path = sys.argv[1:5]
    tag = f"v{version}"
    surface = json.load(open(surface_path))
    cfg = SOURCE_FILES[product]
    out = {"product": product, "version": version, "tag": tag, "commands": {}, "flags": {}}

    # 1. commands
    cmds, experimental, hidden = source_commands(ref, tag, cfg["commands"])
    swept = set(surface["commands"])
    out["commands"] = {
        "source": cmds,
        "experimental_only": experimental,
        "hidden_set": hidden,
        "in_source_not_in_help": sorted(c for c in cmds if c not in swept),
        "in_help_not_in_source": sorted(c for c in swept if c not in cmds and c not in experimental),
    }

    # 2. flags
    for cmd, (stem, root_filter) in CHECK_COMMANDS.items():
        paths = [f"internal/command/arguments/{stem}.go", f"internal/command/{stem}.go"] + cfg["helpers"]
        files = []
        for p in paths:
            src = git_show(ref, tag, p)
            if src is not None:
                files.append(GoFile(p, src))
        consts = parse_consts(files)
        cmd_file = next((f for f in files if f.path == f"internal/command/{stem}.go"), None)
        roots = []
        if cmd_file:
            for m in re.finditer(r"arguments\.(Parse\w+|Bind\w+)\(", cmd_file.san):
                name = m.group(1)
                if root_filter and not root_filter(name):
                    continue
                roots.append(name)
        result, unresolved, seen = [], set(), set()
        for r in dict.fromkeys(roots):
            collect(r, files, {"params": {}}, consts, [], seen, result, unresolved)
        # Terraform: legacy commands strip `-no-color` in Meta.process
        # (internal/command/meta.go) before the arguments package sees them
        if cmd_file and re.search(r"\bMeta\.process\(|\bc\.process\(", cmd_file.san):
            meta = git_show(ref, tag, "internal/command/meta.go") or ""
            mf = GoFile("internal/command/meta.go", meta)
            if "process" in mf.funcs:
                _, a, b = mf.funcs["process"]
                for m in re.finditer(r'==\s*"(-[a-z][a-z0-9-]*)"', meta[a:b]):
                    result.append({"name": m.group(1), "origin": "internal/command/meta.go:process",
                                   "guards": [], "hidden": False, "kind": "manual-strip"})
            roots.append("Meta.process")
        by_name = {}
        for r in result:
            prev = by_name.get(r["name"])
            if prev is None or (prev["guards"] and not r["guards"]):
                by_name[r["name"]] = r
        src_flags = sorted(by_name.values(), key=lambda r: r["name"])

        entry = surface["commands"].get(cmd, {})
        help_flags = {f["name"] for f in entry.get("flags", [])}
        effective = set(help_flags)
        refers = entry.get("help_refers_to")
        if refers == "apply":
            effective |= {f["name"] for f in surface["commands"]["apply"]["flags"]}
            refers = surface["commands"]["apply"].get("help_refers_to")
        if refers == "plan":
            effective |= {f["name"] for f in surface["commands"]["plan"]["flags"]
                          if f["section"].lower().startswith("plan customization")}
        src_names = {r["name"] for r in src_flags}
        out["flags"][cmd] = {
            "roots": list(dict.fromkeys(roots)),
            "source": src_flags,
            "help_listed": sorted(help_flags),
            "help_effective": sorted(effective),
            "help_refers_to": entry.get("help_refers_to"),
            "in_source_not_in_help": sorted(src_names - effective),
            "in_help_not_in_source": sorted(effective - src_names),
            "in_source_only_via_plan_reference": sorted((src_names & effective) - help_flags),
            "unresolved_calls": sorted(unresolved),
        }
    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
