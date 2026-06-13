#!/usr/bin/env python3
"""Generates a self-contained interactive HTML report from features-matrix.json."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MATRIX = os.path.join(ROOT, "features-matrix.json")
OUT_HTML = os.path.join(ROOT, "report.html")

with open(MATRIX) as f:
    data = json.load(f)

payload = json.dumps(data, separators=(",", ":"))

html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Terraform / OpenTofu provider-protocol feature matrix</title>
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
  .sub { color: var(--muted); font-size: 12px; margin-bottom: 10px; }
  .legend { display:flex; gap: 14px; font-size: 11px; color: var(--muted); align-items: center; flex-wrap: wrap; }
  .sw { display:inline-block; width: 12px; height: 12px; border-radius: 3px; vertical-align: -2px; margin-right: 3px;}
  .sw.hatch { background: repeating-linear-gradient(45deg, #b6d7f5 0 3px, #e7f1fb 3px 6px); }
  main { padding: 0 24px 60px; overflow-x: auto; }
  table { border-collapse: separate; border-spacing: 0; font-size: 12px; margin-top: 16px; }
  thead th { position: sticky; top: 0; background: var(--bg); z-index: 10; }
  th.prod { text-align: center; font-size: 11px; padding: 4px 6px; border-bottom: 2px solid var(--border); }
  th.prod.tf { color: var(--tf); border-bottom-color: var(--tf); }
  th.prod.tofu { color: #946c00; border-bottom-color: var(--tofu); }
  th.ver { font-weight: 500; color: var(--muted); padding: 4px 3px; writing-mode: vertical-rl; transform: rotate(180deg); white-space: nowrap; font-size: 10px; height: 56px; vertical-align: bottom;}
  th.feat, td.feat { position: sticky; left: 0; background: var(--bg); z-index: 5; text-align: left; padding: 5px 12px 5px 0; white-space: nowrap; border-right: 1px solid var(--border); cursor: pointer; }
  td.feat .key { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; color: var(--muted); display: block; }
  th.intro, td.intro { padding: 3px 8px; white-space: nowrap; font-family: ui-monospace, Menlo, monospace; font-size: 11px; color: var(--muted); border-right: 1px solid var(--border); text-align: center;}
  tr:hover td { background: var(--row-hover); }
  tr:hover td.feat { background: var(--row-hover); }
  td.cell { width: 22px; min-width: 22px; height: 26px; padding: 2px; }
  td.cell div { width: 100%; height: 100%; border-radius: 3px; background: var(--absent); opacity: .35;}
  td.cell.observed div { background: var(--ok); opacity: 1; }
  td.cell.emits div { background: repeating-linear-gradient(45deg, #b6d7f5 0 4px, #e7f1fb 4px 8px); opacity: 1; border: 1px solid #9ec5e8; }
  td.gapcol { width: 16px; min-width: 16px; border-right: 1px solid var(--border);}
  tr.details td { background: #f6f8fa; font-size: 12px; padding: 12px 16px; border-bottom: 1px solid var(--border); white-space: normal; }
  tr.details code { background: #eaeef2; padding: 1px 4px; border-radius: 4px; font-size: 11px;}
  tr.details ul { margin: 6px 0 0 18px; padding: 0; }
  tr.details li { margin: 2px 0; }
  .badge { display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 10px; margin-left: 6px; vertical-align: 1px; font-weight: 600;}
  .badge.tf-only { background: #f0e7fa; color: var(--tf); }
  .badge.lag { background: #ddf4ff; color: #0969da; }
  .badge.nofixture { background: #fff8c5; color: #946c00; }
  .badge.notga { background: #ffebe9; color: #cf222e; }
  .fixture { margin-top: 14px; font-size: 12px; color: var(--muted); }
  .fixture code { background: #eaeef2; padding: 1px 4px; border-radius: 4px; font-size: 11px; }
</style>
</head>
<body>
<header>
  <h1>Terraform / OpenTofu provider-protocol feature matrix</h1>
  <div class="sub">Built from <code>&lt;binary&gt; providers schema -json</code> sweeps at every minor boundary — a core fixture of small providers (all versions) plus an aws fixture for identity / list / actions (CLI ≥ 1.12) · Terraform <span id="tfRange"></span> · OpenTofu <span id="tofuRange"></span></div>
  <div class="legend">
    <span><span class="sw" style="background:var(--ok)"></span>observed in sweep output</span>
    <span><span class="sw hatch"></span>CLI emits the key (source-verified) but no fixture provider implements it</span>
    <span><span class="sw" style="background:var(--absent);opacity:.35"></span>not supported / not emitted</span>
    <span>click a feature for details</span>
  </div>
</header>
<main>
  <table id="matrix"></table>
  <div class="fixture" id="fixture"></div>
</main>
<script id="data" type="application/json">__PAYLOAD__</script>
<script>
const DATA = JSON.parse(document.getElementById("data").textContent);
const PRODUCTS = ["terraform", "opentofu"];
const vkey = v => v.split(".").map(Number);
const vcmp = (a, b) => { const x = vkey(a), y = vkey(b); for (let i=0;i<3;i++){ if(x[i]!==y[i]) return x[i]-y[i]; } return 0; };

const VERSIONS = DATA.versions;
const FEATURES = DATA.features;
const KEYS = Object.keys(FEATURES);

document.getElementById("tfRange").textContent = `${VERSIONS.terraform[0]} → ${VERSIONS.terraform.at(-1)} (${VERSIONS.terraform.length} swept)`;
document.getElementById("tofuRange").textContent = `${VERSIONS.opentofu[0]} → ${VERSIONS.opentofu.at(-1)} (${VERSIONS.opentofu.length} swept)`;

function cellState(fkey, product, v) {
  const p = FEATURES[fkey].products[product];
  if (p.observed_versions.includes(v)) return "observed";
  if (p.documented_emitted_from && vcmp(v, p.documented_emitted_from) >= 0) return "emits";
  return "absent";
}

function badges(fkey) {
  const f = FEATURES[fkey];
  const tf = f.products.terraform, tofu = f.products.opentofu;
  let h = "";
  if (tf.documented_emitted_from && !tofu.documented_emitted_from) h += "<span class='badge tf-only'>TF only</span>";
  if (tf.documented_emitted_from && tofu.documented_emitted_from && tf.documented_emitted_from !== tofu.documented_emitted_from) h += "<span class='badge lag'>diverged</span>";
  const anyObserved = tf.observed_versions.length || tofu.observed_versions.length;
  if (!anyObserved) h += "<span class='badge nofixture'>no fixture provider</span>";
  if (tf.documented_emitted_from && !tf.documented_ga) h += "<span class='badge notga'>not GA</span>";
  return h;
}

function render() {
  const table = document.getElementById("matrix");
  let h = "<thead><tr><th class='feat'></th><th class='intro'>emits<br>TF</th><th class='intro'>emits<br>Tofu</th>";
  h += `<th class='prod tf' colspan='${VERSIONS.terraform.length}'>Terraform</th><th class='gapcol'></th>`;
  h += `<th class='prod tofu' colspan='${VERSIONS.opentofu.length}'>OpenTofu</th></tr>`;
  h += "<tr><th class='feat'>feature</th><th class='intro'></th><th class='intro'></th>";
  for (const v of VERSIONS.terraform) h += `<th class='ver'>${v}</th>`;
  h += "<th class='gapcol'></th>";
  for (const v of VERSIONS.opentofu) h += `<th class='ver'>${v}</th>`;
  h += "</tr></thead><tbody>";

  for (const fkey of KEYS) {
    const f = FEATURES[fkey];
    const tfIntro = f.products.terraform.documented_emitted_from || "—";
    const tofuIntro = f.products.opentofu.documented_emitted_from || "—";
    h += `<tr data-f="${fkey}"><td class='feat' title='click for details'>${f.title}${badges(fkey)}<span class='key'>${f.schema_key} · protocol ${f.protocol}</span></td>`;
    h += `<td class='intro'>${tfIntro}</td><td class='intro'>${tofuIntro}</td>`;
    for (const product of PRODUCTS) {
      for (const v of VERSIONS[product]) {
        const s = cellState(fkey, product, v);
        const title = {
          observed: `${product} ${v}: observed in sweep`,
          emits: `${product} ${v}: CLI emits ${f.schema_key} (no fixture provider implements it)`,
          absent: `${product} ${v}: not supported / not emitted`,
        }[s];
        h += `<td class='cell ${s === "absent" ? "" : s}' title='${title}'><div></div></td>`;
      }
      if (product === "terraform") h += "<td class='gapcol'></td>";
    }
    h += "</tr>";
  }
  h += "</tbody>";
  table.innerHTML = h;

  table.querySelectorAll("td.feat").forEach(td => td.addEventListener("click", () => {
    const tr = td.parentElement;
    const fkey = tr.dataset.f;
    const existing = tr.nextElementSibling;
    if (existing && existing.classList.contains("details")) { existing.remove(); return; }
    table.querySelectorAll("tr.details").forEach(e => e.remove());
    const f = FEATURES[fkey];
    const det = document.createElement("tr");
    det.className = "details";
    let body = `<b>${f.title}</b> — <code>${f.schema_key}</code> · protocol ${f.protocol} · terraform-plugin-go ${f.plugin_go}<br>`;
    for (const product of PRODUCTS) {
      const p = f.products[product];
      const doc = p.documented_emitted_from ? `emits from ${p.documented_emitted_from}` : "not supported";
      const ga = p.documented_ga ? `GA ${p.documented_ga}` : (p.documented_emitted_from ? "not GA" : "");
      const obs = p.observed_introduced ? `observed from ${p.observed_introduced}` : "never observed with fixture";
      body += `<b>${product}:</b> ${doc}${ga ? " · " + ga : ""} · ${obs}<br>`;
    }
    body += `<i>${f.notes}</i>`;
    const evParts = [];
    for (const product of PRODUCTS) {
      const ev = f.evidence[product];
      if (!ev) continue;
      const items = Object.entries(ev.providers).map(([prov, names]) => {
        const list = Array.isArray(names) ? names.join(", ")
          : Object.entries(names).map(([r, atts]) => `${r}: ${atts.join(", ")}`).join(" · ");
        return `<li><code>${prov}</code> — ${list}</li>`;
      }).join("");
      evParts.push(`<b>evidence (${product} ${ev.version}):</b><ul>${items}</ul>`);
    }
    if (evParts.length) body += "<br>" + evParts.join("");
    det.innerHTML = `<td colspan="${tr.children.length}">${body}</td>`;
    tr.after(det);
  }));

  const fix = DATA.fixture_provider_selections || {};
  const fixParts = PRODUCTS.filter(p => fix[p] && Object.keys(fix[p]).length).map(p =>
    `${p}: ` + Object.entries(fix[p]).map(([k, v]) => `<code>${k}@${v}</code>`).join(" "));
  document.getElementById("fixture").innerHTML =
    fixParts.length ? "Fixture providers — " + fixParts.join(" · ") : "";
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
