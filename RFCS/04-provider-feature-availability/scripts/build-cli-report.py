#!/usr/bin/env python3
"""Generates the self-contained cli-report.html from cli-matrix.json
(same style as report.html, which links to it)."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MATRIX = os.path.join(ROOT, "cli-matrix.json")
OUT_HTML = os.path.join(ROOT, "cli-report.html")

with open(MATRIX) as f:
    data = json.load(f)

payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")

html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Terraform / OpenTofu CLI surface</title>
<style>
  :root {
    --tf: #7b42bc; --tofu: #ffda18; --ok: #2da44e; --emits: #0969da;
    --absent: #d0d7de; --bg: #ffffff; --fg: #1f2328; --muted: #656d76;
    --border: #d0d7de; --row-hover: #f6f8fa;
  }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; margin: 0; color: var(--fg); background: var(--bg); }
  header { padding: 16px 24px; border-bottom: 1px solid var(--border); position: sticky; top: 0; background: var(--bg); z-index: 30; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  h2 { font-size: 14px; margin: 22px 0 6px; }
  a { color: var(--emits); }
  .sub { color: var(--muted); font-size: 12px; margin-bottom: 10px; }
  .legend, .controls { display:flex; gap: 14px; font-size: 11px; color: var(--muted); align-items: center; flex-wrap: wrap; }
  .controls { margin-top: 8px; }
  .controls input[type=search] { font-size: 12px; padding: 3px 6px; border: 1px solid var(--border); border-radius: 4px; width: 220px; max-width: 100%; }
  .sw { display:inline-block; width: 12px; height: 12px; border-radius: 3px; vertical-align: -2px; margin-right: 3px;}
  .sw.hatch { background: repeating-linear-gradient(45deg, #b6d7f5 0 3px, #e7f1fb 3px 6px); }
  main { padding: 0 24px 60px; overflow-x: auto; }
  .stats { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }
  .stat { border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; font-size: 12px; min-width: 150px; }
  .stat b { display: block; font-size: 18px; }
  .stat .k { color: var(--muted); font-size: 11px; }
  table { border-collapse: separate; border-spacing: 0; font-size: 12px; margin-top: 12px; }
  table.simple td, table.simple th { border-bottom: 1px solid var(--border); padding: 4px 10px 4px 0; text-align: left; vertical-align: top; }
  table.simple th { color: var(--muted); font-weight: 600; font-size: 11px; }
  #matrix thead th { position: sticky; top: 0; background: var(--bg); z-index: 10; }
  th.prod { text-align: center; font-size: 11px; padding: 4px 6px; border-bottom: 2px solid var(--border); }
  th.prod.tf { color: var(--tf); border-bottom-color: var(--tf); }
  th.prod.tofu { color: #946c00; border-bottom-color: var(--tofu); }
  th.ver { font-weight: 500; color: var(--muted); padding: 4px 3px; writing-mode: vertical-rl; transform: rotate(180deg); white-space: nowrap; font-size: 10px; height: 56px; vertical-align: bottom;}
  th.feat, td.feat { position: sticky; left: 0; background: var(--bg); z-index: 5; text-align: left; padding: 3px 12px 3px 0; white-space: nowrap; border-right: 1px solid var(--border); }
  td.feat code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
  tr.cmd td.feat { font-weight: 600; padding-top: 8px; }
  tr.flag td.feat { padding-left: 16px; }
  tr:hover td { background: var(--row-hover); }
  td.cell { width: 18px; min-width: 18px; height: 20px; padding: 2px; }
  td.cell div { width: 100%; height: 100%; border-radius: 3px; background: var(--absent); opacity: .35;}
  td.cell.listed div { background: var(--ok); opacity: 1; }
  td.cell.ref div { background: repeating-linear-gradient(45deg, #b6d7f5 0 4px, #e7f1fb 4px 8px); opacity: 1; border: 1px solid #9ec5e8; }
  td.cell.hidden div { background: #fff; opacity: 1; border: 1px dashed #cf222e; }
  td.gapcol { width: 16px; min-width: 16px; border-right: 1px solid var(--border);}
  .badge { display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 10px; margin-left: 6px; vertical-align: 1px; font-weight: 600;}
  .badge.tf-only { background: #f0e7fa; color: var(--tf); }
  .badge.tofu-only { background: #fff8c5; color: #946c00; }
  .badge.hidden { background: #ffebe9; color: #cf222e; }
  .badge.view { background: #eaeef2; color: var(--muted); }
  .badge.dep { background: #ffebe9; color: #9a6700; }
  .badge.cdktn { background: #ddf4ff; color: #0969da; }
  .muted { color: var(--muted); }
</style>
</head>
<body>
<header>
  <h1>Terraform / OpenTofu CLI command &amp; flag surface</h1>
  <div class="sub">Parsed from <code>&lt;binary&gt; [cmd [sub]] -help</code> at the first and last stable patch of every minor line ·
    Terraform <span id="tfRange"></span> · OpenTofu <span id="tofuRange"></span> ·
    <a href="report.html">provider-protocol feature matrix</a></div>
  <div class="legend">
    <span><span class="sw" style="background:var(--ok)"></span>listed in help</span>
    <span><span class="sw hatch"></span>accepted via a help reference (apply/destroy → plan options, destroy → apply)</span>
    <span><span class="sw" style="border:1px dashed #cf222e"></span>accepted but hidden from help (source cross-check, newest version only)</span>
    <span><span class="sw" style="background:var(--absent);opacity:.35"></span>not listed</span>
  </div>
  <div class="controls">
    <input type="search" id="q" placeholder="filter: plan, -target, state …">
    <label><input type="checkbox" id="onlyDiff"> product-only rows</label>
    <label><input type="checkbox" id="onlyChanged"> rows that change across versions</label>
    <label><input type="checkbox" id="hideView" checked> hide OpenTofu view-family flags on non-core commands</label>
    <label><input type="checkbox" id="onlyCdktn"> flags cdktn emits</label>
  </div>
</header>
<main>
  <div class="stats" id="stats"></div>
  <h2>Flags cdktn passes to the binary</h2>
  <div class="muted" style="font-size:12px">Fixed invocations in cdk-terrain (<code>@cdktn/cli-core</code>, <code>@cdktn/provider-schema</code>); cdktn never forwards arbitrary user flags.</div>
  <table class="simple" id="cdktn"></table>
  <h2>Matrix</h2>
  <table id="matrix"></table>
</main>
<script id="data" type="application/json">__PAYLOAD__</script>
<script>
const DATA = JSON.parse(document.getElementById("data").textContent);
const PRODUCTS = ["terraform", "opentofu"];
const V = DATA.versions;
const CORE = new Set(["plan", "apply", "destroy", "refresh", "import", "init"]);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const CDKTN = new Set(DATA.cdktn_emitted.map(r => `${r.command} ${r.flag}`));

document.getElementById("tfRange").textContent = `${V.terraform[0]} → ${V.terraform.at(-1)} (${V.terraform.length} swept)`;
document.getElementById("tofuRange").textContent = `${V.opentofu[0]} → ${V.opentofu.at(-1)} (${V.opentofu.length} swept)`;

const S = DATA.summary;
const stat = (k, v, note) => `<div class="stat"><span class="k">${k}</span><b>${v}</b><span class="muted">${note || ""}</span></div>`;
document.getElementById("stats").innerHTML =
  stat("commands (incl. subcommands)", S.commands_total, `TF-only ${S.commands_only.terraform} · Tofu-only ${S.commands_only.opentofu}`) +
  stat("command × flag pairs", S.flags_total, `TF-only ${S.flags_only.terraform} · Tofu-only ${S.flags_only.opentofu}`) +
  stat("product-only excl. view family", S.flags_only_excluding_view_family.terraform + S.flags_only_excluding_view_family.opentofu,
       `TF ${S.flags_only_excluding_view_family.terraform} · Tofu ${S.flags_only_excluding_view_family.opentofu}`) +
  stat("hidden from help (source)", S.flags_hidden_in_source.terraform + S.flags_hidden_in_source.opentofu,
       `flags: TF ${S.flags_hidden_in_source.terraform} · Tofu ${S.flags_hidden_in_source.opentofu}; commands: TF ${S.commands_hidden_in_source.terraform} · Tofu ${S.commands_hidden_in_source.opentofu}`);

document.getElementById("cdktn").innerHTML =
  "<tr><th>command</th><th>flag</th><th>Terraform</th><th>OpenTofu</th><th>emitted by</th></tr>" +
  DATA.cdktn_emitted.map(r => {
    const cell = p => { const x = r.products[p];
      if (x.all_swept_versions) return "all swept";
      if (x.source_verified_all_versions) return `all swept <span class="muted" title="${esc(x.source_verified_all_versions)}">(source-verified; help from ${x.first_seen || "never"})</span>`;
      return x.first_seen ? `from ${x.first_seen}` : "<b>not listed</b>"; };
    return `<tr><td><code>${esc(r.command)}</code></td><td><code>${esc(r.flag)}</code></td><td>${cell("terraform")}</td><td>${cell("opentofu")}</td><td class="muted">${esc(r.emitted_by)}</td></tr>`;
  }).join("");

// precompute per-row presence sets
function presence(rec, product) {
  if (!rec || !rec.first_seen) return new Set();
  const vs = V[product];
  const a = vs.indexOf(rec.first_seen), b = vs.indexOf(rec.last_seen);
  const gaps = new Set(rec.gaps || []);
  return new Set(vs.slice(a, b + 1).filter(v => !gaps.has(v)));
}
function rowCells(rec, product) {
  const pres = presence(rec, product);
  const hidden = rec && rec.hidden_in_source;
  const hiddenV = hidden ? (typeof hidden === "string" ? hidden : hidden.version) : null;
  return V[product].map(v => {
    let cls = "", title = `${product} ${v}: not listed`;
    if (pres.has(v)) {
      const ref = rec.via && !["listed", "mixed"].includes(rec.via);
      cls = ref ? "ref" : "listed";
      title = `${product} ${v}: ${ref ? "accepted via " + rec.via : "listed in help"}`;
    } else if (hiddenV === v) {
      cls = "hidden"; title = `${product} ${v}: accepted but hidden from help` + (hidden.origin ? ` (${hidden.origin})` : "");
    }
    return `<td class="cell ${cls}" title="${esc(title)}"><div></div></td>`;
  }).join("");
}
function badges(item, isFlag) {
  let h = "";
  if (item.only === "terraform") h += "<span class='badge tf-only'>TF only</span>";
  if (item.only === "opentofu") h += "<span class='badge tofu-only'>Tofu only</span>";
  for (const p of PRODUCTS) {
    const r = item.products[p];
    if (r && r.hidden_in_source) h += `<span class='badge hidden'>hidden in ${p === "terraform" ? "TF" : "Tofu"}</span>`;
    if (r && r.removed_in) h += `<span class='badge dep'>${p === "terraform" ? "TF" : "Tofu"}: gone from help in ${r.removed_in}</span>`;
    if (r && r.deprecation_markers && r.deprecation_markers.length && !r.removed_in) h += `<span class='badge dep' title='${esc(r.desc)}'>${r.deprecation_markers.join(", ")}</span>`;
  }
  if (isFlag && item.family === "view") h += "<span class='badge view'>view family</span>";
  if (isFlag && CDKTN.has(`${item.command} ${item.flag}`)) h += "<span class='badge cdktn'>cdktn emits</span>";
  return h;
}
function changes(item) {
  return PRODUCTS.some(p => { const r = item.products[p]; return !r || !r.first_seen || r.count !== V[p].length; });
}

function render() {
  const q = document.getElementById("q").value.trim().toLowerCase();
  const onlyDiff = document.getElementById("onlyDiff").checked;
  const onlyChanged = document.getElementById("onlyChanged").checked;
  const hideView = document.getElementById("hideView").checked;
  const onlyCdktn = document.getElementById("onlyCdktn").checked;
  let h = "<thead><tr><th class='feat'></th>";
  h += `<th class='prod tf' colspan='${V.terraform.length}'>Terraform</th><th class='gapcol'></th>`;
  h += `<th class='prod tofu' colspan='${V.opentofu.length}'>OpenTofu</th></tr>`;
  h += "<tr><th class='feat'>command / flag</th>";
  for (const v of V.terraform) h += `<th class='ver'>${v}</th>`;
  h += "<th class='gapcol'></th>";
  for (const v of V.opentofu) h += `<th class='ver'>${v}</th>`;
  h += "</tr></thead><tbody>";

  const byCmd = {};
  for (const [k, f] of Object.entries(DATA.flags)) (byCmd[f.command] ||= []).push(f);
  const globals = Object.entries(DATA.global_options).map(([name, g]) => ({command: "(global)", flag: name, products: g.products, only: g.only, family: null}));
  const cmds = [["(global)", {products: {terraform: {first_seen: V.terraform[0], last_seen: V.terraform.at(-1), count: V.terraform.length}, opentofu: {first_seen: V.opentofu[0], last_seen: V.opentofu.at(-1), count: V.opentofu.length}}, only: null}, globals],
                ...Object.entries(DATA.commands).map(([k, c]) => [k, c, byCmd[k] || []])];
  for (const [name, c, flags] of cmds) {
    const flagRows = flags.filter(f => {
      if (hideView && f.family === "view" && !CORE.has(name) && f.only === "opentofu") return false;
      if (onlyDiff && !f.only) return false;
      if (onlyChanged && !changes(f)) return false;
      if (onlyCdktn && !CDKTN.has(`${f.command} ${f.flag}`)) return false;
      if (q && !(`${name} ${f.flag}`.toLowerCase().includes(q))) return false;
      return true;
    });
    const cmdMatches = (!q || name.toLowerCase().includes(q)) && (!onlyDiff || c.only) && (!onlyChanged || changes(c)) && !onlyCdktn;
    if (!cmdMatches && !flagRows.length) continue;
    h += `<tr class='cmd'><td class='feat'><code>${esc(name)}</code>${badges(c, false)}</td>`;
    h += rowCells(c.products.terraform, "terraform") + "<td class='gapcol'></td>" + rowCells(c.products.opentofu, "opentofu") + "</tr>";
    for (const f of flagRows) {
      const anyRec = f.products.terraform || f.products.opentofu || {};
      const kind = anyRec.kind ? ` <span class='muted'>${anyRec.kind}${anyRec.placeholder ? " " + esc(anyRec.placeholder) : ""}</span>` : "";
      h += `<tr class='flag'><td class='feat' title='${esc(anyRec.desc || "")}'><code>${esc(f.flag)}</code>${kind}${badges(f, true)}</td>`;
      h += rowCells(f.products.terraform, "terraform") + "<td class='gapcol'></td>" + rowCells(f.products.opentofu, "opentofu") + "</tr>";
    }
  }
  h += "</tbody>";
  document.getElementById("matrix").innerHTML = h;
}
for (const id of ["q", "onlyDiff", "onlyChanged", "hideView", "onlyCdktn"]) document.getElementById(id).addEventListener("input", render);
render();
</script>
</body>
</html>
"""

html = html.replace("__PAYLOAD__", payload)
with open(OUT_HTML, "w") as f:
    f.write(html)
print(f"wrote {OUT_HTML} ({len(html)//1024} KiB)")
