#!/usr/bin/env python3
"""Generates a self-contained interactive HTML report from functions-matrix.json."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MATRIX = os.path.join(ROOT, "functions-matrix.json")
OUT_HTML = os.path.join(ROOT, "report.html")

with open(MATRIX) as f:
    data = json.load(f)

payload = json.dumps(data, separators=(",", ":"))

html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Terraform / OpenTofu function availability matrix</title>
<style>
  :root {
    --tf: #7b42bc; --tofu: #ffda18; --ok: #2da44e; --partial: #bf8700;
    --absent: #d0d7de; --bg: #ffffff; --fg: #1f2328; --muted: #656d76;
    --border: #d0d7de; --row-hover: #f6f8fa;
  }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; margin: 0; color: var(--fg); background: var(--bg); }
  header { padding: 16px 24px; border-bottom: 1px solid var(--border); position: sticky; top: 0; background: var(--bg); z-index: 30; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .sub { color: var(--muted); font-size: 12px; margin-bottom: 10px; }
  .controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; font-size: 13px; }
  .controls input[type=search] { padding: 5px 9px; border: 1px solid var(--border); border-radius: 6px; min-width: 220px; font-size: 13px; }
  .controls select { padding: 4px 6px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; }
  .controls label { display: inline-flex; align-items: center; gap: 4px; cursor: pointer; user-select: none; }
  .stats { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px; color: var(--muted); margin-top: 8px; }
  .stats b { color: var(--fg); }
  .legend { display:flex; gap: 12px; font-size: 11px; color: var(--muted); margin-top: 6px; align-items: center; flex-wrap: wrap; }
  .sw { display:inline-block; width: 12px; height: 12px; border-radius: 3px; vertical-align: -2px; margin-right: 3px;}
  main { padding: 0 24px 60px; overflow-x: auto; }
  table { border-collapse: separate; border-spacing: 0; font-size: 12px; margin-top: 12px; }
  thead th { position: sticky; top: 0; background: var(--bg); z-index: 10; }
  th.prod { text-align: center; font-size: 11px; padding: 4px 6px; border-bottom: 2px solid var(--border); }
  th.prod.tf { color: var(--tf); border-bottom-color: var(--tf); }
  th.prod.tofu { color: #946c00; border-bottom-color: var(--tofu); }
  th.ver { font-weight: 500; color: var(--muted); padding: 4px 2px; writing-mode: vertical-rl; transform: rotate(180deg); white-space: nowrap; font-size: 10px; height: 52px; vertical-align: bottom;}
  th.fn, td.fn { position: sticky; left: 0; background: var(--bg); z-index: 5; text-align: left; padding: 3px 10px 3px 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; white-space: nowrap; border-right: 1px solid var(--border); cursor: pointer; }
  th.intro, td.intro { padding: 3px 8px; white-space: nowrap; font-family: ui-monospace, Menlo, monospace; font-size: 11px; color: var(--muted); border-right: 1px solid var(--border); text-align: center;}
  tr:hover td { background: var(--row-hover); }
  tr:hover td.fn { background: var(--row-hover); }
  td.cell { width: 16px; min-width: 16px; height: 18px; padding: 1px; }
  td.cell div { width: 100%; height: 100%; border-radius: 2px; background: var(--absent); opacity: .35;}
  td.cell.full div { background: var(--ok); opacity: 1; }
  td.cell.partial div { background: var(--partial); opacity: 1; }
  td.cell.gap div { background: #cf222e; opacity: .8; }
  td.gapcol { width: 14px; min-width: 14px; border-right: 1px solid var(--border);}
  tr.details td { background: #f6f8fa; font-size: 12px; padding: 10px 14px; border-bottom: 1px solid var(--border); }
  tr.details code { background: #eaeef2; padding: 1px 4px; border-radius: 4px; font-size: 11px;}
  .badge { display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 10px; margin-left: 6px; vertical-align: 1px; font-family: -apple-system, sans-serif; font-weight: 600;}
  .badge.tf-only { background: #f0e7fa; color: var(--tf); }
  .badge.tofu-only { background: #fff8c5; color: #946c00; }
  .badge.late { background: #ddf4ff; color: #0969da; }
  .badge.removed { background: #ffebe9; color: #cf222e; }
  .count { color: var(--muted); font-size: 12px; margin: 10px 0 0; }
</style>
</head>
<body>
<header>
  <h1>Terraform / OpenTofu function availability matrix</h1>
  <div class="sub">Built from <code>&lt;binary&gt; metadata functions -json</code> across every stable release · Terraform <span id="tfRange"></span> · OpenTofu <span id="tofuRange"></span></div>
  <div class="controls">
    <input type="search" id="q" placeholder="Filter functions… (regex ok)">
    <select id="presence">
      <option value="all">All functions</option>
      <option value="differs">Differs between products</option>
      <option value="tf-only">Terraform only</option>
      <option value="tofu-only">OpenTofu only</option>
      <option value="late">Introduced after baseline</option>
      <option value="removed">Removed at some point</option>
    </select>
    <select id="granularity">
      <option value="minor">Minor versions (rollup)</option>
      <option value="patch">Every patch release</option>
    </select>
    <label><input type="checkbox" id="hideBaseline"> hide functions present everywhere</label>
  </div>
  <div class="stats" id="stats"></div>
  <div class="legend">
    <span><span class="sw" style="background:var(--ok)"></span>available (whole column)</span>
    <span><span class="sw" style="background:var(--partial)"></span>introduced mid-column (hover for exact patch)</span>
    <span><span class="sw" style="background:#cf222e;opacity:.8"></span>gap / removed</span>
    <span><span class="sw" style="background:var(--absent);opacity:.35"></span>not available</span>
    <span>click a function name for its signature</span>
  </div>
</header>
<main>
  <div class="count" id="count"></div>
  <table id="matrix"></table>
</main>
<script id="data" type="application/json">__PAYLOAD__</script>
<script>
const DATA = JSON.parse(document.getElementById("data").textContent);
const PRODUCTS = ["terraform", "opentofu"];
const vkey = v => v.split(".").map(Number);
const vcmp = (a, b) => { const x = vkey(a), y = vkey(b); for (let i=0;i<3;i++){ if(x[i]!==y[i]) return x[i]-y[i]; } return 0; };
const minorOf = v => v.split(".").slice(0,2).join(".");

const VERSIONS = DATA.versions; // product -> sorted versions
const FN = DATA.functions;
const NAMES = Object.keys(FN).sort();
const BASE = { terraform: VERSIONS.terraform[0], opentofu: VERSIONS.opentofu[0] };
const LATEST = { terraform: VERSIONS.terraform.at(-1), opentofu: VERSIONS.opentofu.at(-1) };

document.getElementById("tfRange").textContent = `${BASE.terraform} → ${LATEST.terraform} (${VERSIONS.terraform.length} releases)`;
document.getElementById("tofuRange").textContent = `${BASE.opentofu} → ${LATEST.opentofu} (${VERSIONS.opentofu.length} releases)`;

// availability test: version v is in [introduced, removed) minus gaps
function available(name, product, v) {
  const p = FN[name].products[product];
  if (!p) return false;
  if (vcmp(v, p.introduced) < 0) return false;
  if (p.removed && vcmp(v, p.removed) >= 0) return false;
  if (p.gaps && p.gaps.includes(v)) return false;
  return true;
}

function classify(name) {
  const tf = FN[name].products.terraform, tofu = FN[name].products.opentofu;
  const flags = [];
  if (tf && !tofu) flags.push("tf-only");
  if (tofu && !tf) flags.push("tofu-only");
  if ((tf && tf.introduced !== BASE.terraform) || (tofu && tofu.introduced !== BASE.opentofu)) flags.push("late");
  if ((tf && tf.removed) || (tofu && tofu.removed)) flags.push("removed");
  if (flags.length) flags.push("differs");
  return flags;
}

function columns(granularity) {
  const cols = {};
  for (const product of PRODUCTS) {
    if (granularity === "patch") {
      cols[product] = VERSIONS[product].map(v => ({ label: v, versions: [v] }));
    } else {
      const groups = new Map();
      for (const v of VERSIONS[product]) {
        const m = minorOf(v);
        if (!groups.has(m)) groups.set(m, []);
        groups.get(m).push(v);
      }
      cols[product] = [...groups.entries()].map(([m, vs]) => ({ label: m + ".x", versions: vs }));
    }
  }
  return cols;
}

function render() {
  const qRaw = document.getElementById("q").value.trim();
  let q = null;
  try { q = qRaw ? new RegExp(qRaw, "i") : null; } catch { q = null; }
  const presence = document.getElementById("presence").value;
  const granularity = document.getElementById("granularity").value;
  const hideBaseline = document.getElementById("hideBaseline").checked;

  const cols = columns(granularity);
  const rows = NAMES.filter(name => {
    if (q && !q.test(name)) return false;
    const flags = classify(name);
    if (hideBaseline && flags.length === 0) return false;
    if (presence !== "all" && !flags.includes(presence)) return false;
    return true;
  });

  const table = document.getElementById("matrix");
  let h = "<thead><tr><th class='fn'></th><th class='intro'>introduced<br>TF</th><th class='intro'>introduced<br>Tofu</th>";
  h += `<th class='prod tf' colspan='${cols.terraform.length}'>Terraform</th><th class='gapcol'></th>`;
  h += `<th class='prod tofu' colspan='${cols.opentofu.length}'>OpenTofu</th></tr>`;
  h += "<tr><th class='fn'>function</th><th class='intro'></th><th class='intro'></th>";
  for (const c of cols.terraform) h += `<th class='ver'>${c.label}</th>`;
  h += "<th class='gapcol'></th>";
  for (const c of cols.opentofu) h += `<th class='ver'>${c.label}</th>`;
  h += "</tr></thead><tbody>";

  for (const name of rows) {
    const f = FN[name];
    const flags = classify(name);
    let badges = "";
    if (flags.includes("tf-only")) badges += "<span class='badge tf-only'>TF only</span>";
    if (flags.includes("tofu-only")) badges += "<span class='badge tofu-only'>Tofu only</span>";
    if (flags.includes("late")) badges += "<span class='badge late'>new</span>";
    if (flags.includes("removed")) badges += "<span class='badge removed'>removed</span>";
    const tfIntro = f.products.terraform ? f.products.terraform.introduced + (f.products.terraform.introduced === BASE.terraform ? " *" : "") : "—";
    const tofuIntro = f.products.opentofu ? f.products.opentofu.introduced + (f.products.opentofu.introduced === BASE.opentofu ? " *" : "") : "—";
    h += `<tr data-fn="${name}"><td class='fn' title='click for signature'>${name}${badges}</td>`;
    h += `<td class='intro'>${tfIntro}</td><td class='intro'>${tofuIntro}</td>`;
    for (const product of PRODUCTS) {
      for (const c of cols[product]) {
        const avail = c.versions.map(v => available(name, product, v));
        const all = avail.every(Boolean), none = !avail.some(Boolean);
        const p = f.products[product];
        let cls = "cell", title = `${product} ${c.label}: not available`;
        if (all) { cls += " full"; title = `${product} ${c.label}: available`; }
        else if (!none) {
          const firstIdx = avail.indexOf(true);
          const isGapOrRemoval = p && (p.removed || (p.gaps && p.gaps.some(g => c.versions.includes(g)))) && vcmp(c.versions[0], p.introduced) >= 0;
          if (isGapOrRemoval && avail[0]) { cls += " gap"; title = `${product} ${c.label}: removed/missing in part of this series`; }
          else { cls += " partial"; title = `${product} ${c.label}: from ${c.versions[firstIdx]}`; }
        } else if (p && p.removed && vcmp(c.versions[0], p.removed) >= 0) {
          cls += " gap"; title = `${product} ${c.label}: removed at ${p.removed}`;
        }
        h += `<td class='${cls}' title='${title}'><div></div></td>`;
      }
      if (product === "terraform") h += "<td class='gapcol'></td>";
    }
    h += "</tr>";
  }
  h += "</tbody>";
  table.innerHTML = h;
  document.getElementById("count").textContent = `${rows.length} of ${NAMES.length} functions shown`;

  // stats
  const tfOnly = NAMES.filter(n => classify(n).includes("tf-only")).length;
  const tofuOnly = NAMES.filter(n => classify(n).includes("tofu-only")).length;
  const late = NAMES.filter(n => classify(n).includes("late")).length;
  const removed = NAMES.filter(n => classify(n).includes("removed")).length;
  document.getElementById("stats").innerHTML =
    `<span><b>${NAMES.length}</b> functions total</span>` +
    `<span><b>${tfOnly}</b> Terraform-only</span>` +
    `<span><b>${tofuOnly}</b> OpenTofu-only</span>` +
    `<span><b>${late}</b> introduced after baseline (* = present since first scanned release)</span>` +
    `<span><b>${removed}</b> removed</span>`;

  // row click -> signature details
  table.querySelectorAll("td.fn").forEach(td => td.addEventListener("click", () => {
    const tr = td.parentElement;
    const name = tr.dataset.fn;
    const existing = tr.nextElementSibling;
    if (existing && existing.classList.contains("details")) { existing.remove(); return; }
    table.querySelectorAll("tr.details").forEach(e => e.remove());
    const f = FN[name];
    const sig = f.signature;
    const params = (sig.parameters || []).map(p => `${p.name}: ${JSON.stringify(p.type)}`);
    if (sig.variadic_parameter) params.push(`...${sig.variadic_parameter.name}: ${JSON.stringify(sig.variadic_parameter.type)}`);
    const det = document.createElement("tr");
    det.className = "details";
    const totalCols = tr.children.length;
    const gaps = PRODUCTS.map(p => f.products[p] && f.products[p].gaps && f.products[p].gaps.length ? `<br><b>${p} gaps:</b> ${f.products[p].gaps.join(", ")}` : "").join("");
    det.innerHTML = `<td colspan="${totalCols}"><b>${name}(${params.join(", ")})</b> → <code>${JSON.stringify(sig.return_type)}</code><br>${(sig.description || "").replace(/</g,"&lt;")}${gaps}</td>`;
    tr.after(det);
  }));
}

for (const id of ["q", "presence", "granularity", "hideBaseline"]) {
  document.getElementById(id).addEventListener("input", render);
}
render();
</script>
</body>
</html>
"""

html = html.replace("__PAYLOAD__", payload)
with open(OUT_HTML, "w") as f:
    f.write(html)
print(f"wrote {OUT_HTML} ({len(html)//1024} KiB)")
