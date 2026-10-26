#!/usr/bin/env python3
"""Cross-checks a swept CLI surface (cli_help.py output) against the Go source.

Usage:
  python3 -I cli-source-check.py <ref-clone> <product> <version> <cli-surface.json>

<ref-clone> is a (blobless is fine) clone of hashicorp/terraform or
opentofu/opentofu. All files are read in one `git cat-file --batch` call at
tag v<version>; cli-sweep.sh prefetches the needed blobs in one batch first
(a blobless clone otherwise fetches each blob in its own round trip).

The answer this produces is "which flags does the binary's parser ACCEPT",
which is what an allowlist must be built from; help text only says which
flags are LISTED.

Two checks:

1. Commands: every key of the `Commands` map in commands.go
   (Terraform: ./commands.go, OpenTofu: ./cmd/tofu/commands.go), including
   entries registered only under `meta.AllowExperimentalFeatures` and the
   `HiddenCommands` / `hiddenCommands` set, against the commands the help
   sweep found. Each entry's `&command.<Type>{...}` literal is recorded
   (type + boolean fields such as `Destroy: true`).

2. Flags of EVERY registered command: starting from `(*<Type>).Run` in
   internal/command, the walker follows calls whose names look like flag
   plumbing into internal/command and internal/command/arguments:
     - `arguments.Parse*` / `arguments.Bind*` and the package helpers they
       call (`extendedFlagSet`, `defaultFlagSet`, `ParseView`, OpenTofu
       `bind*` / `Bind*`),
     - Meta methods (`c.Meta.extendedFlagSet`, `defaultFlagSet`,
       `ignoreRemoteVersionFlagSet`, ...),
     - OpenTofu >= 1.13 `RunCommand(<X>Commander(), ...)` -> `<X>Commander`,
     - methods of the command's own type (`c.setupTestExecution(...)`),
   and collects every `<recv>.<Kind>Var(..., "<name>", ...)` registration.
   `Meta.process` (strips `-no-color` before flag parsing) is recorded as
   `manual-strip`, `case "-x":` labels in `ParseView` as `manual-switch`,
   OpenTofu 1.11-1.12's `-deprecation=module:` prefix match as
   `manual-prefix` (takes a value), and `<x>.ViewOptions.AddFlags(...)`
   (OpenTofu 1.11-1.12) is followed into types.go.
   Guards around a registration or call are evaluated where possible:
     - Terraform `if state != nil {` against the caller's arguments
       (`extendedFlagSet("init", nil, nil, init.Vars)` drops state/operation),
     - OpenTofu bit masks (`if mask&viewFlagLint != 0`) against the caller's
       mask expression, resolved through the package's `const` blocks,
     - boolean parameters passed as literals (`bindApply(cli, true)`),
     - command struct fields from the commands.go literal (`c.Destroy`;
       fields not set in the literal are false).
   ApplyCommand serves both `apply` and `destroy` and picks its parser with
   an early return / switch, so the walker additionally skips the other
   mode's entry points (SKIP_CALLEES) in the Run body.
   Unevaluable guards (`if experimentsEnabled {`) keep the flag and record
   the guard text. OpenTofu's `.SetHidden(true)` is recorded as `hidden`.

Each source flag gets `takes_value` from its registration kind
(BoolVar/Bool/BoolFunc and the manual switch/strip forms take no value;
every other kind does). Caveat: a `Var` whose flag.Value implements
IsBoolFlag() would be reported as taking a value; none of the swept
versions registers one on a command flag set.

The flag list is then compared with the help sweep. For Terraform apply /
destroy the help page delegates plan options to `terraform plan -help`; the
"effective" help set adds the plan page's "Plan Customization Options".
"""
import json
import re
import subprocess
import sys

SOURCE_FILES = {
    "terraform": {"commands": "commands.go"},
    "opentofu": {"commands": "cmd/tofu/commands.go"},
}
PKG_COMMAND = "internal/command"
PKG_ARGUMENTS = "internal/command/arguments"

# Commands that are not part of the binary's own flag surface (see
# cli_help.py NO_RECURSE): stacks execs an external plugin, rpcapi is a
# machine interface with its own protocol.
NOT_CHECKED = {"stacks", "rpcapi"}

# ApplyCommand.Run dispatches on c.Destroy via an early return (OpenTofu
# >= 1.13) or a tagless switch (Terraform); neither is a guard block, so the
# other mode's parser entry points are skipped by name.
SKIP_CALLEES = {
    ("ApplyCommand", True): {"ApplyCommander", "ParseApply", "BindApply"},
    ("ApplyCommand", False): {"DestroyCommander", "ParseApplyDestroy", "BindApplyDestroy"},
}

# Calls the walker follows (by callee name). Everything else in a Run body
# (backend setup, config loading, ...) does not register flags.
FOLLOW_RE = re.compile(
    r"^(?:Parse[A-Z]\w*|parse\w*Flags?|Bind[A-Z]\w*|bind[A-Z]\w*|\w*[Ff]lag[Ss]et|\w*Commander|RunCommand|process|setup[A-Z]\w*|Add\w*Flags?)$"
)

FLAG_CALL_RE = re.compile(
    r"\b(\w+)\.(BoolVar|StringVar|IntVar|Int64Var|UintVar|Float64Var|DurationVar|StringArrayVar|"
    r"TextVar|Var|RawFlags|Func|BoolFunc|Bool|String|Int|Duration)\("
)
NAME_ARG_INDEX = {"Func": 0, "BoolFunc": 0, "Bool": 0, "String": 0, "Int": 0, "Duration": 0}
NO_VALUE_KINDS = {"BoolVar", "Bool", "BoolFunc", "manual-switch", "manual-strip"}
CALL_RE = re.compile(r"(?<![\w.])((?:[A-Za-z_]\w*\.)*)([A-Za-z_]\w*)\(")
FUNC_RE = re.compile(r"(?m)^func\s+(?:\(\s*(\w+)\s+\*?(\w+)\s*\)\s*)?(\w+)\(")


def read_tree(ref, tag, product):
    """{path: source} for commands.go + internal/command{,/arguments}/*.go."""
    paths = [SOURCE_FILES[product]["commands"]]
    for d in (PKG_COMMAND, PKG_ARGUMENTS):
        p = subprocess.run(["git", "-C", ref, "ls-tree", "--name-only", f"{tag}:{d}"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        for name in p.stdout.decode().split():
            if name.endswith(".go") and not name.endswith("_test.go"):
                paths.append(f"{d}/{name}")
    req = "".join(f"{tag}:{p}\n" for p in paths).encode()
    p = subprocess.run(["git", "-C", ref, "cat-file", "--batch"], input=req,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    out, data, i = {}, p.stdout, 0
    for path in paths:
        nl = data.index(b"\n", i)
        header = data[i:nl].decode()
        i = nl + 1
        if header.endswith(" missing"):
            continue
        size = int(header.split()[2])
        out[path] = data[i:i + size].decode("utf-8", "replace")
        i += size + 1
    return out


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


class Func:
    def __init__(self, gofile, recv_var, recv_type, name, params, b_open, b_close):
        self.file = gofile
        self.recv_var = recv_var
        self.recv_type = recv_type
        self.name = name
        self.params = params
        self.b_open = b_open
        self.b_close = b_close

    @property
    def qual(self):
        return f"{self.file.path}:{self.recv_type + '.' if self.recv_type else ''}{self.name}"


class GoFile:
    def __init__(self, path, src):
        self.path = path
        self.pkg = path.rsplit("/", 1)[0] if "/" in path else ""
        self.src = src
        self.san = sanitize(src)
        self.funcs = []
        for m in FUNC_RE.finditer(self.san):
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
            self.funcs.append(Func(self, m.group(1), m.group(2), m.group(3), params, k, b_close))

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


class Index:
    def __init__(self, files):
        self.files = files
        self.by_name = {}
        for f in files:
            for fn in f.funcs:
                self.by_name.setdefault(fn.name, []).append(fn)
        self.consts = parse_consts([f for f in files if f.pkg in (PKG_COMMAND, PKG_ARGUMENTS)])

    def method(self, recv_type, name):
        return next((fn for fn in self.by_name.get(name, []) if fn.recv_type == recv_type), None)

    def resolve(self, caller, prefix, name):
        cands = self.by_name.get(name, [])
        if not cands:
            return None
        parts = [p for p in prefix.split(".") if p]
        if not parts:
            # package-level function in the caller's package
            return next((fn for fn in cands if fn.recv_type is None and fn.file.pkg == caller.file.pkg), None)
        if parts == ["arguments"]:
            return next((fn for fn in cands if fn.recv_type is None and fn.file.pkg == PKG_ARGUMENTS), None)
        if caller.recv_var and parts[0] == caller.recv_var:
            methods = [fn for fn in cands if fn.recv_type and fn.file.pkg == caller.file.pkg]
            if len(parts) == 1:
                own = [fn for fn in methods if fn.recv_type == caller.recv_type]
                if own:
                    return own[0]
            for t in (parts[-1], "Meta"):
                hit = [fn for fn in methods if fn.recv_type == t]
                if hit:
                    return hit[0]
            return methods[0] if len(methods) == 1 else None
        # field/variable of a known type: `apply.ViewOptions.AddFlags(...)`
        # (OpenTofu 1.11-1.12) -> method AddFlags on type ViewOptions
        hit = [fn for fn in cands if fn.recv_type == parts[-1]]
        if hit:
            return hit[0]
        if parts[0] not in ("flag", "strings", "fmt", "os", "tfdiags", "hcl", "cty"):
            methods = [fn for fn in cands if fn.recv_type and fn.file.pkg in (PKG_COMMAND, PKG_ARGUMENTS)]
            if len(methods) == 1:
                return methods[0]
        return None


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


def resolve_value(expr, env):
    """env: params (param -> arg text), locals (mask locals), fields (c.X)."""
    expr = expr.strip()
    if expr in env.get("locals", {}):
        return env["locals"][expr]
    if expr in env.get("params", {}):
        return env["params"][expr]
    if expr in env.get("fields", {}):
        return env["fields"][expr]
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
    mm = re.fullmatch(r"(!?)([\w.]+)", cond)
    if mm:
        arg = resolve_value(mm.group(2), env)
        if arg in ("true", "false"):
            val = (arg == "true") != bool(mm.group(1))
    if val is None:
        return None
    return (not val) if neg else val


def local_masks(fn, env, consts):
    """Mask-typed locals assigned in a function (`viewFlags := viewFlagAll`)."""
    f = fn.file
    out = {}
    body = f.src[fn.b_open:fn.b_close]
    for m in re.finditer(r"(?m)^\s*(\w+)\s*(?::=|=)\s*(.+)$", body):
        name, expr = m.group(1), m.group(2).strip()
        expr = re.sub(rf"^{name}\s*\|\s*", "", expr)
        val = eval_mask(expr, consts)
        if val is None:
            continue
        guards = f.guards_at(fn.b_open, fn.b_open + m.start())
        if all(eval_guard(g, env, consts) is not False for g in guards):
            out[name] = out.get(name, 0) | val
    return out


def collect(fn, idx, env, origin_guards, ctx, depth=0):
    """Appends flag records reachable from fn to ctx['result']."""
    key = (fn.qual, json.dumps(env.get("params", {}), sort_keys=True, default=str))
    if key in ctx["seen"] or depth > 8:
        return
    ctx["seen"].add(key)
    ctx["visited"].append(fn.qual)
    f = fn.file
    env = dict(env)
    env["locals"] = local_masks(fn, env, idx.consts)
    consts = idx.consts

    # Terraform ParseView: manual switch over raw args
    for m in re.finditer(r'case\s+"(-[a-z][a-z0-9-]*)"', f.src[fn.b_open:fn.b_close]):
        ctx["result"].append({"name": m.group(1), "origin": f"{f.path}:{fn.name}", "guards": origin_guards,
                              "hidden": False, "kind": "manual-switch"})
    # OpenTofu 1.11-1.12 ParseView: `if prefix := "-deprecation=module:"; strings.HasPrefix(v, prefix)`
    for m in re.finditer(r'prefix\s*:=\s*"(-[a-z][a-z0-9-]*)=', f.src[fn.b_open:fn.b_close]):
        ctx["result"].append({"name": m.group(1), "origin": f"{f.path}:{fn.name}", "guards": origin_guards,
                              "hidden": False, "kind": "manual-prefix"})
    # Meta.process: `if v == "-no-color"` strip loop
    if fn.name == "process" and fn.recv_type == "Meta":
        for m in re.finditer(r'==\s*"(-[a-z][a-z0-9-]*)"', f.src[fn.b_open:fn.b_close]):
            ctx["result"].append({"name": m.group(1), "origin": f"{f.path}:Meta.process", "guards": origin_guards,
                                  "hidden": False, "kind": "manual-strip"})

    for m in FLAG_CALL_RE.finditer(f.san, fn.b_open, fn.b_close):
        kind = m.group(2)
        p_open = m.end() - 1
        p_close = match_close(f.san, p_open, "(", ")")
        args = split_args(f.src, f.san, p_open + 1, p_close)
        i = NAME_ARG_INDEX.get(kind, 1)
        if len(args) <= i or not re.fullmatch(r'"[a-z][a-z0-9-]*"', args[i]):
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
        guards = f.guards_at(fn.b_open, m.start())
        evals = [eval_guard(g, env, consts) for g in guards]
        if any(v is False for v in evals):
            continue
        unknown = [g for g, v in zip(guards, evals) if v is None]
        rec = {
            "name": "-" + args[i].strip('"'),
            "origin": f"{f.path}:{fn.name}",
            "guards": origin_guards + unknown,
            "hidden": any(c == "SetHidden" and a == "true" for c, a in chain),
            "kind": kind,
        }
        disp = [a for c, a in chain if c == "SetDisplay"]
        if disp:
            rec["display"] = disp[0].strip('"')
        ctx["result"].append(rec)

    for m in CALL_RE.finditer(f.san, fn.b_open + 1, fn.b_close):
        prefix, name = m.group(1), m.group(2)
        if depth == 0 and name in ctx["skip"]:
            continue
        # OpenTofu >= 1.13: a parent Commander lists its subcommands'
        # Commanders in `Commands: []Command{...}`; those parse their own
        # (separately registered) command lines
        if name.endswith("Commander") and fn.name.endswith("Commander"):
            continue
        own_method = bool(fn.recv_var) and prefix == fn.recv_var + "."
        if not (follow := FOLLOW_RE.match(name)) and not own_method:
            continue
        callee = idx.resolve(fn, prefix, name)
        if callee is not None and not follow and callee.recv_type != fn.recv_type:
            continue
        if callee is None and not follow:
            continue
        if callee is None:
            if prefix == "arguments." or (fn.recv_var and prefix.startswith(fn.recv_var + ".")):
                ctx["unresolved"].add(prefix + name)
            continue
        if callee is fn:
            continue
        p_open = m.end() - 1
        p_close = match_close(f.san, p_open, "(", ")")
        args = split_args(f.src, f.san, p_open + 1, p_close)
        guards = f.guards_at(fn.b_open, m.start())
        evals = [eval_guard(g, env, consts) for g in guards]
        if any(v is False for v in evals):
            continue
        unknown = [g for g, v in zip(guards, evals) if v is None]
        cenv = {"params": {}, "fields": env.get("fields", {}) if callee.recv_type == fn.recv_type else {}}
        for p, aval in zip(callee.params, args):
            if p.split():
                cenv["params"][p.split()[0]] = resolve_value(aval, env)
        collect(callee, idx, cenv, origin_guards + unknown, ctx, depth + 1)


def source_commands(src):
    """-> {name: {"type", "fields", "experimental"}}, hidden set."""
    san = sanitize(src)
    cmds = {}
    for m in re.finditer(r'(?m)^\s*"([a-z0-9][a-z0-9 -]*)":\s*(?:func\(|[\w.]+\()', src):
        cmds[m.group(1)] = {"pos": m.end(), "experimental": False}
    for m in re.finditer(r'Commands\["([a-z0-9 -]+)"\]\s*=', src):
        cmds[m.group(1)] = {"pos": m.end(), "experimental": True}
    for name, c in cmds.items():
        lm = re.compile(r"&command\.(\w+)\{").search(san, c["pos"])
        nxt = re.compile(r'(?m)^\s*"[a-z0-9][a-z0-9 -]*":|Commands\["').search(san, c["pos"])
        if lm and (nxt is None or lm.start() < nxt.start()):
            c["type"] = lm.group(1)
            close = match_close(san, lm.end() - 1, "{", "}")
            if c["type"] == "AliasCommand":
                # OpenTofu `state ls/move/remove`: AliasCommand{Command: &command.StateListCommand{...}}
                inner = re.compile(r"&command\.(\w+)\{").search(san, lm.end(), close)
                if inner:
                    c["alias_of_type"] = inner.group(1)
                    c["type"] = inner.group(1)
            c["fields"] = {k: v == "true" for k, v in
                           re.findall(r"\b([A-Z]\w*):\s*(true|false)\b", src[lm.end():close])}
        else:
            c["type"] = None
            c["fields"] = {}
        del c["pos"]
    hidden = []
    hm = re.search(r"(?s)[hH]iddenCommands = map\[string\]struct\{\}\{(.*?)\n\t\}", src)
    if hm:
        hidden = re.findall(r'"([a-z0-9 -]+)"', hm.group(1))
    return cmds, sorted(set(hidden))


def help_sets(surface, cmd):
    entry = surface["commands"].get(cmd, {})
    help_flags = {f["name"] for f in entry.get("flags", [])}
    effective = set(help_flags)
    refers = entry.get("help_refers_to")
    if refers == "apply" and "apply" in surface["commands"]:
        effective |= {f["name"] for f in surface["commands"]["apply"]["flags"]}
        refers = surface["commands"]["apply"].get("help_refers_to")
    if refers == "plan" and "plan" in surface["commands"]:
        effective |= {f["name"] for f in surface["commands"]["plan"]["flags"]
                      if f["section"].lower().startswith("plan customization")}
    return help_flags, effective


def main():
    ref, product, version, surface_path = sys.argv[1:5]
    tag = f"v{version}"
    with open(surface_path) as fh:
        surface = json.load(fh)
    tree = read_tree(ref, tag, product)
    cmd_src = tree.get(SOURCE_FILES[product]["commands"], "")
    files = [GoFile(p, s) for p, s in tree.items() if p != SOURCE_FILES[product]["commands"]]
    idx = Index(files)
    out = {"product": product, "version": version, "tag": tag, "parser": "cli-source-check v2 (all commands)",
           "commands": {}, "flags": {}}

    # 1. commands
    cmds, hidden = source_commands(cmd_src)
    swept = set(surface["commands"])
    regular = sorted(c for c, v in cmds.items() if not v["experimental"])
    experimental = sorted(c for c, v in cmds.items() if v["experimental"])
    out["commands"] = {
        "source": regular,
        "experimental_only": experimental,
        "hidden_set": hidden,
        "in_source_not_in_help": sorted(c for c in regular if c not in swept),
        "in_help_not_in_source": sorted(c for c in swept if c not in cmds),
        "types": {c: {"type": v["type"], **({"fields": v["fields"]} if v["fields"] else {}),
                      **({"alias": True} if v.get("alias_of_type") else {})}
                  for c, v in sorted(cmds.items())},
    }

    # 2. flags of every registered command (experimental-only ones excluded:
    # release builds do not register them)
    all_bool_fields = {k for v in cmds.values() for k in v["fields"]}
    for cmd in regular:
        if cmd in NOT_CHECKED:
            continue
        ctype = cmds[cmd]["type"]
        run = idx.method(ctype, "Run") if ctype else None
        if run is None:
            out["flags"][cmd] = {"type": ctype, "error": "no Run method found"}
            continue
        fields = {f"{run.recv_var}.{k}": "false" for k in all_bool_fields}
        fields.update({f"{run.recv_var}.{k}": ("true" if v else "false") for k, v in cmds[cmd]["fields"].items()})
        ctx = {"result": [], "seen": set(), "visited": [], "unresolved": set(),
               "skip": SKIP_CALLEES.get((ctype, cmds[cmd]["fields"].get("Destroy", False)), set())}
        collect(run, idx, {"params": {}, "fields": fields}, [], ctx)
        by_name = {}
        for r in ctx["result"]:
            prev = by_name.get(r["name"])
            if prev is None or (prev["guards"] and not r["guards"]):
                by_name[r["name"]] = r
        src_flags = sorted(by_name.values(), key=lambda r: r["name"])
        for r in src_flags:
            r["takes_value"] = r["kind"] not in NO_VALUE_KINDS

        help_flags, effective = help_sets(surface, cmd)
        src_names = {r["name"] for r in src_flags}
        parses = any(r["kind"] not in ("manual-strip",) for r in src_flags) or any(
            ".Parse" in v or "Commander" in v for v in ctx["visited"])
        out["flags"][cmd] = {
            "type": ctype,
            "visited": list(dict.fromkeys(ctx["visited"])),
            "parses_flags": parses,
            "source": src_flags,
            "help_listed": sorted(help_flags),
            "help_effective": sorted(effective),
            "help_refers_to": surface["commands"].get(cmd, {}).get("help_refers_to"),
            "in_source_not_in_help": sorted(src_names - effective),
            "in_help_not_in_source": sorted(effective - src_names),
            "in_source_only_via_plan_reference": sorted((src_names & effective) - help_flags),
            "unresolved_calls": sorted(ctx["unresolved"]),
        }
    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
