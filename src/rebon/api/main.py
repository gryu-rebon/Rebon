"""
rebon internal web app + API.

Run:
    cd ~/Developments/rebon
    uvicorn src.rebon.api.main:app --reload --port 8000

Then open: http://localhost:8000
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from rebon.db.chroma import get_client, EMBEDDING_FN  # noqa: E402

STRAINS_PATH   = Path(__file__).parents[3] / "data" / "strains.json"
PRODUCTS_PATH  = Path(__file__).parents[3] / "data" / "products.json"


def get_db_strain_ids() -> set[str]:
    """Return the set of strain IDs currently in ChromaDB. Returns empty set if DB doesn't exist yet."""
    try:
        client = get_client()
        col = client.get_collection("strains", embedding_function=EMBEDDING_FN)
        result = col.get(include=[])
        return set(result["ids"])
    except Exception:
        return set()

app = FastAPI(title="rebon")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── API endpoints ──────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/strains")
def strains(q: Optional[str] = Query(default=None)):
    with open(STRAINS_PATH) as f:
        all_strains = json.load(f)

    db_ids = get_db_strain_ids()
    for s in all_strains:
        s["in_db"] = s["id"] in db_ids

    if q:
        q_lower = q.lower()
        def matches(s):
            searchable = " ".join([
                s.get("id") or "",
                s.get("name") or "",
                s.get("genus") or "",
                s.get("species") or "",
                s.get("strain_code") or "",
                s.get("evidence_tier") or "",
                s.get("viability") or "",
                " ".join(s.get("conditions") or []),
            ]).lower()
            return q_lower in searchable
        all_strains = [s for s in all_strains if matches(s)]

    return {"strains": all_strains, "total": len(all_strains)}


@app.get("/products")
def products(q: Optional[str] = Query(default=None)):
    with open(PRODUCTS_PATH) as f:
        brands = json.load(f)

    # Flatten brand → products, injecting brand fields into each product
    flat = []
    for brand_entry in brands:
        for p in brand_entry.get("products", []):
            item = {
                "brand": brand_entry.get("brand"),
                "market_name": brand_entry.get("market_name"),
                **p,
            }
            flat.append(item)

    if q:
        ql = q.lower()
        def matches(p):
            searchable = " ".join([
                p.get("brand") or "",
                p.get("market_name") or "",
                p.get("name") or "",
                p.get("form") or "",
                p.get("dsld_product_name") or "",
                " ".join(
                    s.get("name", "") for s in (p.get("probiotic_strains") or [])
                ),
            ]).lower()
            return ql in searchable
        flat = [p for p in flat if matches(p)]

    return {"products": flat, "total": len(flat)}


# ── Web UI ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def ui():
    return HTML


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>rebon</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #f5f5f5; color: #1a1a1a; }

  header { background: #1a1a1a; color: white; padding: 0 24px;
           display: flex; align-items: stretch; gap: 0; }
  .header-brand { display: flex; align-items: center; gap: 12px; padding: 16px 0; margin-right: 32px; }
  header h1 { font-size: 18px; font-weight: 700; letter-spacing: -0.02em; }
  header .badge { background: #4ade80; color: #1a1a1a; font-size: 11px;
                  font-weight: 600; padding: 2px 8px; border-radius: 999px; }

  .tab-nav { display: flex; align-items: stretch; }
  .tab-btn { background: none; border: none; color: rgba(255,255,255,0.55); font-size: 13px;
             font-weight: 500; padding: 0 16px; cursor: pointer; position: relative;
             transition: color 0.15s; white-space: nowrap; }
  .tab-btn:hover { color: rgba(255,255,255,0.85); }
  .tab-btn.active { color: white; }
  .tab-btn.active::after { content: ""; position: absolute; bottom: 0; left: 0; right: 0;
                            height: 2px; background: #4ade80; }
  .tab-btn .coming { font-size: 10px; color: rgba(255,255,255,0.3); margin-left: 5px; }

  /* Pages */
  .page { display: none; padding: 24px; min-height: calc(100vh - 53px); }
  .page.active { display: flex; flex-direction: column; }

  /* Toolbar */
  .toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
  .search-wrap { flex: 1; max-width: 440px; position: relative; }
  .search-wrap input { width: 100%; padding: 9px 12px 9px 36px; border: 1px solid #ddd;
                        border-radius: 8px; font-size: 13px; background: white;
                        transition: border-color 0.15s; }
  .search-wrap input:focus { outline: none; border-color: #4ade80; }
  .search-wrap .icon { position: absolute; left: 11px; top: 50%; transform: translateY(-50%);
                        color: #aaa; font-size: 14px; pointer-events: none; }
  .count { font-size: 13px; color: #888; }

  /* Filter pills */
  .filters { display: flex; gap: 6px; flex-wrap: wrap; }
  .filter-pill { font-size: 12px; padding: 4px 12px; border-radius: 999px; cursor: pointer;
                  border: 1px solid #ddd; background: white; color: #555; transition: all 0.15s; }
  .filter-pill:hover { border-color: #aaa; }
  .filter-pill.active { background: #1a1a1a; color: white; border-color: #1a1a1a; }
  .filter-pill.strong  { border-color: #bbf7d0; color: #15803d; background: #f0fdf4; }
  .filter-pill.strong.active  { background: #15803d; color: white; border-color: #15803d; }
  .filter-pill.moderate { border-color: #fde68a; color: #854d0e; background: #fefce8; }
  .filter-pill.moderate.active { background: #854d0e; color: white; border-color: #854d0e; }
  .filter-pill.preliminary { border-color: #fecaca; color: #b91c1c; background: #fef2f2; }
  .filter-pill.preliminary.active { background: #b91c1c; color: white; border-color: #b91c1c; }

  /* Table */
  .table-wrap { background: white; border-radius: 12px; border: 1px solid #e5e5e5;
                overflow: hidden; flex: 1; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  thead { background: #f9f9f9; position: sticky; top: 0; z-index: 1; }
  th { padding: 10px 14px; text-align: left; font-size: 11px; font-weight: 700;
       text-transform: uppercase; letter-spacing: 0.07em; color: #888;
       border-bottom: 1px solid #e5e5e5; white-space: nowrap; cursor: pointer; user-select: none; }
  th:hover { color: #555; }
  th .sort-arrow { margin-left: 4px; opacity: 0.3; font-style: normal; }
  th.sort-asc .sort-arrow::after  { content: "↑"; opacity: 1; color: #1a1a1a; }
  th.sort-desc .sort-arrow::after { content: "↓"; opacity: 1; color: #1a1a1a; }
  th:not(.sort-asc):not(.sort-desc) .sort-arrow::after { content: "↕"; }
  th.filter-row { padding: 4px 8px; background: #f3f4f6; cursor: default; }
  th.filter-row input, th.filter-row select {
    width: 100%; padding: 4px 7px; border: 1px solid #ddd; border-radius: 5px;
    font-size: 11px; font-weight: 400; text-transform: none; letter-spacing: 0;
    background: white; color: #333; outline: none;
  }
  th.filter-row input:focus, th.filter-row select:focus { border-color: #4ade80; }
  td { padding: 11px 14px; border-bottom: 1px solid #f0f0f0; vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  tbody tr { cursor: pointer; }
  tbody tr:hover td { background: #fafafa; }
  tbody tr.selected td { background: #f0fdf4 !important; }
  .no-results { text-align: center; padding: 48px; color: #aaa; font-size: 14px; }

  /* Cell types */
  .cell-id { font-family: "SF Mono", Menlo, monospace; font-size: 12px; font-weight: 600;
              color: #15803d; white-space: nowrap; }
  .cell-name { font-weight: 600; }
  .cell-italic { font-style: italic; color: #555; font-size: 12px; white-space: nowrap; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; max-width: 320px; }
  .chip { font-size: 11px; padding: 2px 7px; border-radius: 999px; white-space: nowrap; }
  .chip-blue { background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }
  .chip-green { background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0; }
  .chip-gray  { background: #f5f5f5; color: #555; border: 1px solid #e5e5e5; }

  /* Evidence badges */
  .badge-tier { font-size: 11px; padding: 2px 8px; border-radius: 999px; font-weight: 500; white-space: nowrap; }
  .tier-strong      { background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0; }
  .tier-moderate    { background: #fefce8; color: #854d0e; border: 1px solid #fde68a; }
  .tier-preliminary { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }
  .tier-unknown     { background: #f5f5f5; color: #777;    border: 1px solid #e5e5e5; }

  /* Detail panel */
  .overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.25); z-index: 200; }
  .overlay.open { display: block; }
  .panel { position: fixed; top: 0; right: 0; bottom: 0; width: 500px; max-width: 95vw;
           background: white; box-shadow: -4px 0 24px rgba(0,0,0,0.12); z-index: 201;
           display: flex; flex-direction: column;
           transform: translateX(100%); transition: transform 0.25s cubic-bezier(0.4,0,0.2,1); }
  .panel.open { transform: translateX(0); }
  .panel-header { padding: 18px 20px 14px; border-bottom: 1px solid #e5e5e5;
                   display: flex; align-items: flex-start; gap: 12px; }
  .panel-header-text { flex: 1; min-width: 0; }
  .panel-title { font-size: 15px; font-weight: 700; line-height: 1.4; }
  .panel-subtitle { font-size: 12px; color: #888; margin-top: 3px; font-style: italic; }
  .panel-close { background: none; border: none; font-size: 18px; color: #aaa;
                  cursor: pointer; padding: 2px 4px; flex-shrink: 0; }
  .panel-close:hover { color: #1a1a1a; }
  .panel-body { flex: 1; overflow-y: auto; padding: 20px; }

  .detail-section { margin-bottom: 22px; }
  .detail-section-title { font-size: 10px; font-weight: 700; text-transform: uppercase;
                           letter-spacing: 0.09em; color: #aaa; margin-bottom: 10px;
                           padding-bottom: 6px; border-bottom: 1px solid #f0f0f0; }
  .detail-row { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; font-size: 13px; }
  .detail-label { color: #888; flex-shrink: 0; width: 150px; font-size: 12px; }
  .detail-value { color: #1a1a1a; font-weight: 500; word-break: break-word; }
  .detail-value.mono { font-family: "SF Mono", Menlo, monospace; font-size: 11.5px; font-weight: 400; color: #555; }

  .rct-list { list-style: none; padding: 0; margin: 0; }
  .rct-list li { font-size: 12px; color: #444; line-height: 1.7; padding: 5px 0;
                  border-bottom: 1px solid #f5f5f5; }
  .rct-list li:last-child { border-bottom: none; }
  .rct-list li::before { content: "◦ "; color: #aaa; }

  /* Coming soon placeholder */
  .coming-soon { display: flex; flex-direction: column; align-items: center; justify-content: center;
                  height: 100%; padding-top: 120px; color: #aaa; gap: 12px; }
  .coming-soon .cs-icon { font-size: 40px; }
  .coming-soon h2 { font-size: 16px; font-weight: 600; color: #888; }
  .coming-soon p { font-size: 13px; }
</style>
</head>
<body>

<header>
  <div class="header-brand">
    <h1>rebon</h1>
    <span class="badge">Internal</span>
  </div>
  <nav class="tab-nav">
    <button class="tab-btn" onclick="switchTab('recommender', this)">
      Recommender <span class="coming">soon</span>
    </button>
    <button class="tab-btn" onclick="switchTab('products', this)">Products</button>
    <button class="tab-btn active" onclick="switchTab('strains', this)">Strains</button>
    <button class="tab-btn" onclick="switchTab('conditions', this)">
      Conditions <span class="coming">soon</span>
    </button>
  </nav>
</header>

<!-- ── RECOMMENDER (placeholder) ── -->
<div class="page" id="tab-recommender">
  <div class="coming-soon">
    <div class="cs-icon">🧬</div>
    <h2>Recommender coming soon</h2>
    <p>The agent pipeline will be wired up here once the DB and recommender logic are ready.</p>
  </div>
</div>

<!-- ── PRODUCTS ── -->
<div class="page" id="tab-products">
  <div class="toolbar">
    <div class="search-wrap">
      <span class="icon">🔍</span>
      <input type="text" id="productsSearch" placeholder="Search by brand, product name, strain…" oninput="onProductSearch(this.value)">
    </div>
    <span class="count" id="productsCount"></span>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th onclick="productSortBy('market_name')" id="pth-market_name">Brand <i class="sort-arrow"></i></th>
          <th onclick="productSortBy('name')" id="pth-name">Product <i class="sort-arrow"></i></th>
          <th onclick="productSortBy('form')" id="pth-form">Form <i class="sort-arrow"></i></th>
          <th onclick="productSortBy('serving_size')" id="pth-serving_size">Serving <i class="sort-arrow"></i></th>
          <th onclick="productSortBy('total_cfu_billion')" id="pth-total_cfu_billion">Total CFU <i class="sort-arrow"></i></th>
          <th>Strains</th>
          <th>Source</th>
          <th onclick="productSortBy('_enriched')" id="pth-_enriched">Enriched <i class="sort-arrow"></i></th>
        </tr>
        <tr>
          <th class="filter-row"><input id="pcf-brand"   placeholder="filter…" oninput="applyProductFilters()"></th>
          <th class="filter-row"><input id="pcf-name"    placeholder="filter…" oninput="applyProductFilters()"></th>
          <th class="filter-row">
            <select id="pcf-form" onchange="applyProductFilters()">
              <option value="">all</option>
              <option value="Capsule">Capsule</option>
              <option value="Tablet">Tablet</option>
              <option value="Powder">Powder</option>
              <option value="Liquid">Liquid</option>
              <option value="Gummi">Gummy</option>
            </select>
          </th>
          <th class="filter-row"><input id="pcf-serving" placeholder="filter…" oninput="applyProductFilters()"></th>
          <th class="filter-row"><input id="pcf-cfu"     placeholder="e.g. 10" oninput="applyProductFilters()"></th>
          <th class="filter-row"><input id="pcf-strain"  placeholder="filter…" oninput="applyProductFilters()"></th>
          <th class="filter-row">
            <select id="pcf-source" onchange="applyProductFilters()">
              <option value="">all</option>
              <option value="dsld">DSLD</option>
              <option value="iherb">iHerb</option>
              <option value="amazon">Amazon</option>
            </select>
          </th>
          <th class="filter-row">
            <select id="pcf-enriched" onchange="applyProductFilters()">
              <option value="">all</option>
              <option value="yes">yes</option>
              <option value="no">no</option>
            </select>
          </th>
        </tr>
      </thead>
      <tbody id="productsBody">
        <tr><td colspan="8" class="no-results">Loading…</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- ── STRAINS ── -->
<div class="page active" id="tab-strains">
  <div class="toolbar">
    <div class="search-wrap">
      <span class="icon">🔍</span>
      <input type="text" id="strainsSearch" placeholder="Search by name, ID, condition, evidence tier…" oninput="onSearch(this.value)">
    </div>
    <span class="count" id="strainsCount"></span>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th onclick="sortBy('id')" id="th-id">ID <i class="sort-arrow"></i></th>
          <th onclick="sortBy('name')" id="th-name">Name <i class="sort-arrow"></i></th>
          <th onclick="sortBy('strain_code')" id="th-strain_code">Strain Code <i class="sort-arrow"></i></th>
          <th onclick="sortBy('evidence_tier')" id="th-evidence_tier">Evidence <i class="sort-arrow"></i></th>
          <th>Conditions</th>
          <th onclick="sortBy('effective_cfu_dose_label')" id="th-effective_cfu_dose_label">Effective Dose <i class="sort-arrow"></i></th>
          <th onclick="sortBy('viability')" id="th-viability">Viability <i class="sort-arrow"></i></th>
          <th>In DB</th>
        </tr>
        <tr>
          <th class="filter-row"><input id="cf-id"        placeholder="filter…" oninput="applyFilters()"></th>
          <th class="filter-row"><input id="cf-name"       placeholder="filter…" oninput="applyFilters()"></th>
          <th class="filter-row"><input id="cf-strain_code" placeholder="filter…" oninput="applyFilters()"></th>
          <th class="filter-row">
            <select id="cf-tier" onchange="applyFilters()">
              <option value="">all</option>
              <option value="strong">strong</option>
              <option value="moderate">moderate</option>
              <option value="preliminary">preliminary</option>
              <option value="unknown">unknown</option>
            </select>
          </th>
          <th class="filter-row"><input id="cf-conditions" placeholder="filter…" oninput="applyFilters()"></th>
          <th class="filter-row"><input id="cf-dose"       placeholder="filter…" oninput="applyFilters()"></th>
          <th class="filter-row">
            <select id="cf-viability" onchange="applyFilters()">
              <option value="">all</option>
              <option value="shelf-stable">shelf-stable</option>
              <option value="refrigerated">refrigerated</option>
              <option value="unknown">unknown</option>
            </select>
          </th>
          <th class="filter-row">
            <select id="cf-indb" onchange="applyFilters()">
              <option value="">all</option>
              <option value="yes">yes</option>
              <option value="no">no</option>
            </select>
          </th>
        </tr>
      </thead>
      <tbody id="strainsBody">
        <tr><td colspan="7" class="no-results">Loading…</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- ── CONDITIONS (placeholder) ── -->
<div class="page" id="tab-conditions">
  <div class="coming-soon">
    <div class="cs-icon">🩺</div>
    <h2>Conditions map coming soon</h2>
    <p>Condition → strain mappings will appear here once the conditions index is built.</p>
  </div>
</div>

<!-- ── DETAIL PANEL ── -->
<div class="overlay" id="overlay" onclick="closePanel()"></div>
<div class="panel" id="panel">
  <div class="panel-header">
    <div class="panel-header-text">
      <div class="panel-title" id="panelTitle"></div>
      <div class="panel-subtitle" id="panelSubtitle"></div>
    </div>
    <button class="panel-close" onclick="closePanel()">✕</button>
  </div>
  <div class="panel-body" id="panelBody"></div>
</div>

<script>
// ── State ──────────────────────────────────────────────────────────────────────
let allStrains = [];
let filtered = [];
let activeTier = 'all';
let activeSort = null;
let sortDir = 1;
let searchTimeout = null;

// ── Tabs ───────────────────────────────────────────────────────────────────────
function switchTab(tab, btn) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('tab-' + tab).classList.add('active');
  closePanel();
}

// ── Data ───────────────────────────────────────────────────────────────────────
async function loadStrains() {
  const res = await fetch('/strains');
  const data = await res.json();
  allStrains = data.strains;
  applyFilters();
}

function colFilter(id) {
  return (document.getElementById(id)?.value || '').trim().toLowerCase();
}

function applyFilters(q = document.getElementById('strainsSearch').value.trim()) {
  let result = allStrains;

  // Global search
  if (q) {
    const ql = q.toLowerCase();
    result = result.filter(s => [
      s.id, s.name, s.genus, s.species, s.strain_code,
      s.evidence_tier, s.viability, ...(s.conditions || [])
    ].join(' ').toLowerCase().includes(ql));
  }

  // Column filters
  const fId         = colFilter('cf-id');
  const fName       = colFilter('cf-name');
  const fStrainCode = colFilter('cf-strain_code');
  const fTier       = colFilter('cf-tier');
  const fCond      = colFilter('cf-conditions');
  const fDose      = colFilter('cf-dose');
  const fViability = colFilter('cf-viability');
  const fInDb      = colFilter('cf-indb');

  if (fId)         result = result.filter(s => (s.id || '').toLowerCase().includes(fId));
  if (fName)       result = result.filter(s => (s.name || '').toLowerCase().includes(fName));
  if (fStrainCode) result = result.filter(s => (s.strain_code || '').toLowerCase().includes(fStrainCode));
  if (fTier)      result = result.filter(s => (s.evidence_tier || '') === fTier);
  if (fCond)      result = result.filter(s => (s.conditions || []).join(' ').toLowerCase().includes(fCond));
  if (fDose)      result = result.filter(s => (s.effective_cfu_dose_label || '').toLowerCase().includes(fDose));
  if (fViability) result = result.filter(s => (s.viability || '').toLowerCase() === fViability);
  if (fInDb)      result = result.filter(s => (s.in_db ? 'yes' : 'no') === fInDb);

  // Sort
  if (activeSort) {
    const tierOrder = { strong: 0, moderate: 1, preliminary: 2, unknown: 3 };
    result = [...result].sort((a, b) => {
      if (activeSort === 'evidence_tier') {
        const av = tierOrder[a.evidence_tier] ?? 3;
        const bv = tierOrder[b.evidence_tier] ?? 3;
        return (av - bv) * sortDir;
      }
      const av = (a[activeSort] || '').toString().toLowerCase();
      const bv = (b[activeSort] || '').toString().toLowerCase();
      return av < bv ? -sortDir : av > bv ? sortDir : 0;
    });
  }

  filtered = result;
  renderTable();
}

function onSearch(val) {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => applyFilters(val.trim()), 200);
}

function setTierFilter(tier, el) {
  activeTier = tier;
  document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  applyFilters();
}

function sortBy(col) {
  if (activeSort === col) sortDir *= -1;
  else { activeSort = col; sortDir = 1; }
  document.querySelectorAll('th[id^="th-"]').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
  });
  const th = document.getElementById('th-' + col);
  if (th) th.classList.add(sortDir === 1 ? 'sort-asc' : 'sort-desc');
  applyFilters();
}

// ── Render ─────────────────────────────────────────────────────────────────────
function tierBadge(t) {
  const cls = { strong: 'tier-strong', moderate: 'tier-moderate', preliminary: 'tier-preliminary' }[t] || 'tier-unknown';
  return `<span class="badge-tier ${cls}">${t || 'unknown'}</span>`;
}

function renderTable() {
  const tbody = document.getElementById('strainsBody');
  const n = filtered.length;
  document.getElementById('strainsCount').textContent = n + ' strain' + (n !== 1 ? 's' : '');

  if (!n) {
    tbody.innerHTML = '<tr><td colspan="7" class="no-results">No strains match.</td></tr>';
    return;
  }

  tbody.innerHTML = filtered.map((s, i) => {
    const conds = (s.conditions || []).slice(0, 3).map(c =>
      `<span class="chip chip-blue">${c}</span>`).join('') +
      (s.conditions?.length > 3 ? `<span class="chip chip-gray">+${s.conditions.length - 3}</span>` : '');

    const dbBadge = s.in_db
      ? `<span class="chip chip-green" title="In ChromaDB">✓ yes</span>`
      : `<span class="chip chip-gray" title="Not in ChromaDB">— no</span>`;

    return `<tr onclick="openDetail(${i})">
      <td class="cell-id">${s.id}</td>
      <td class="cell-name">${s.name || '—'}</td>
      <td style="font-size:12px;color:#555;white-space:nowrap">${s.strain_code || '—'}</td>
      <td>${tierBadge(s.evidence_tier)}</td>
      <td><div class="chips">${conds || '—'}</div></td>
      <td style="font-size:12px;color:#444;white-space:nowrap">${s.effective_cfu_dose_label || '—'}</td>
      <td style="font-size:12px;color:#555;text-transform:capitalize;white-space:nowrap">${s.viability || '—'}</td>
      <td>${dbBadge}</td>
    </tr>`;
  }).join('');
}

// ── Detail panel ───────────────────────────────────────────────────────────────
function openDetail(idx) {
  document.querySelectorAll('tbody tr.selected').forEach(r => r.classList.remove('selected'));
  document.querySelectorAll('tbody tr')[idx]?.classList.add('selected');

  const s = filtered[idx];
  document.getElementById('panelTitle').textContent = s.name || s.id;
  document.getElementById('panelSubtitle').textContent = [s.genus, s.species].filter(Boolean).join(' ');

  const row = (label, v) =>
    `<div class="detail-row"><span class="detail-label">${label}</span><span class="detail-value">${v ?? '—'}</span></div>`;
  const bool = v => v
    ? `<span class="chip chip-green">Yes</span>`
    : `<span class="chip chip-gray">No</span>`;

  const condChips = (s.conditions || []).map(c => `<span class="chip chip-blue">${c}</span>`).join('');
  const rcts = (s.key_rcts || []).map(r => `<li>${r}</li>`).join('');

  document.getElementById('panelBody').innerHTML = `
    <div class="detail-section">
      <div class="detail-section-title">Identity</div>
      ${row('ID', `<span class="detail-value mono">${s.id}</span>`)}
      ${row('Full name', s.name)}
      ${row('Genus', s.genus)}
      ${row('Species', s.species)}
      ${s.strain_code ? row('Designation', s.strain_code) : ''}
      ${(s.alternative_names || []).length ? row('Also known as', `<span style="font-style:italic">${s.alternative_names.join(', ')}</span>`) : ''}
    </div>
    <div class="detail-section">
      <div class="detail-section-title">Evidence</div>
      ${row('Evidence tier', tierBadge(s.evidence_tier))}
      ${s.evidence_tier_rationale ? `<div class="detail-row"><span class="detail-label"></span><span style="font-size:12px;color:#666;font-style:italic">${s.evidence_tier_rationale}</span></div>` : ''}
      ${row('Effective dose', s.effective_cfu_dose_label)}
      ${s.effective_cfu_dose ? row('Raw dose', `<span class="detail-value mono">${s.effective_cfu_dose}</span>`) : ''}
    </div>
    <div class="detail-section">
      <div class="detail-section-title">Formulation</div>
      ${row('Viability', s.viability)}
      ${row('Enteric coated', bool(s.enteric_coated))}
      ${s.survivability_notes ? row('Survivability', s.survivability_notes) : ''}
    </div>
    <div class="detail-section">
      <div class="detail-section-title">Conditions (${(s.conditions || []).length})</div>
      <div class="chips" style="max-width:100%">${condChips || '—'}</div>
    </div>
    ${rcts ? `<div class="detail-section">
      <div class="detail-section-title">Key Studies</div>
      <ul class="rct-list">${rcts}</ul>
    </div>` : ''}
    ${s.notes ? `<div class="detail-section">
      <div class="detail-section-title">Notes</div>
      <div style="font-size:13px;line-height:1.65;color:#555">${s.notes}</div>
    </div>` : ''}
    <div class="detail-section">
      <div class="detail-section-title">Status</div>
      ${row('Enriched', bool(s.enriched))}
      ${row('In ChromaDB', bool(s.in_db))}
    </div>
  `;

  document.getElementById('overlay').classList.add('open');
  document.getElementById('panel').classList.add('open');
}

function closePanel() {
  document.getElementById('overlay').classList.remove('open');
  document.getElementById('panel').classList.remove('open');
  document.querySelectorAll('tbody tr.selected').forEach(r => r.classList.remove('selected'));
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closePanel(); });

// ── Products state ─────────────────────────────────────────────────────────────
let allProducts = [];
let filteredProducts = [];
let productSort = null;
let productSortDir = 1;
let productSearchTimeout = null;

async function loadProducts() {
  const res = await fetch('/products');
  const data = await res.json();
  allProducts = data.products;
  applyProductFilters();
}

function pColFilter(id) {
  return (document.getElementById(id)?.value || '').trim().toLowerCase();
}

function applyProductFilters(q = document.getElementById('productsSearch').value.trim()) {
  let result = allProducts;

  if (q) {
    const ql = q.toLowerCase();
    result = result.filter(p => [
      p.brand, p.market_name, p.name, p.form, p.dsld_product_name,
      ...(p.probiotic_strains || []).map(s => s.name),
    ].join(' ').toLowerCase().includes(ql));
  }

  const fBrand   = pColFilter('pcf-brand');
  const fName    = pColFilter('pcf-name');
  const fForm    = pColFilter('pcf-form');
  const fServing = pColFilter('pcf-serving');
  const fCfu     = pColFilter('pcf-cfu');
  const fStrain  = pColFilter('pcf-strain');
  const fSource  = pColFilter('pcf-source');
  const fEnriched = pColFilter('pcf-enriched');

  if (fBrand)   result = result.filter(p => (p.market_name || p.brand || '').toLowerCase().includes(fBrand));
  if (fName)    result = result.filter(p => (p.name || '').toLowerCase().includes(fName));
  if (fForm)    result = result.filter(p => (p.form || '').toLowerCase().includes(fForm));
  if (fServing) result = result.filter(p => (p.serving_size || '').toLowerCase().includes(fServing));
  if (fCfu)     result = result.filter(p => (p.total_cfu_billion || 0) >= parseFloat(fCfu) || 0);
  if (fStrain)  result = result.filter(p => (p.probiotic_strains || []).some(s => s.name.toLowerCase().includes(fStrain)));
  if (fSource)  result = result.filter(p => Object.keys(p.detail_sources || {}).includes(fSource));
  if (fEnriched) {
    const want = fEnriched === 'yes';
    result = result.filter(p => !!p.detail_sources === want);
  }

  if (productSort) {
    result = [...result].sort((a, b) => {
      let av = productSort === '_enriched' ? (a.detail_sources ? 1 : 0)
             : productSort === 'total_cfu_billion' ? (a.total_cfu_billion || 0)
             : (a[productSort] || '').toString().toLowerCase();
      let bv = productSort === '_enriched' ? (b.detail_sources ? 1 : 0)
             : productSort === 'total_cfu_billion' ? (b.total_cfu_billion || 0)
             : (b[productSort] || '').toString().toLowerCase();
      return av < bv ? -productSortDir : av > bv ? productSortDir : 0;
    });
  }

  filteredProducts = result;
  renderProductsTable();
}

function onProductSearch(val) {
  clearTimeout(productSearchTimeout);
  productSearchTimeout = setTimeout(() => applyProductFilters(val.trim()), 200);
}

function productSortBy(col) {
  if (productSort === col) productSortDir *= -1;
  else { productSort = col; productSortDir = 1; }
  document.querySelectorAll('th[id^="pth-"]').forEach(th => th.classList.remove('sort-asc', 'sort-desc'));
  const th = document.getElementById('pth-' + col);
  if (th) th.classList.add(productSortDir === 1 ? 'sort-asc' : 'sort-desc');
  applyProductFilters();
}

function sourceTags(detail_sources) {
  if (!detail_sources) return '<span class="chip chip-gray">—</span>';
  return Object.keys(detail_sources).map(s => {
    const cls = s === 'dsld' ? 'chip-green' : s === 'iherb' ? 'chip-blue' : 'chip-gray';
    return `<span class="chip ${cls}">${s.toUpperCase()}</span>`;
  }).join(' ');
}

function renderProductsTable() {
  const tbody = document.getElementById('productsBody');
  const n = filteredProducts.length;
  document.getElementById('productsCount').textContent = n + ' product' + (n !== 1 ? 's' : '');

  if (!n) {
    tbody.innerHTML = '<tr><td colspan="8" class="no-results">No products match.</td></tr>';
    return;
  }

  tbody.innerHTML = filteredProducts.map((p, i) => {
    const strainChips = (p.probiotic_strains || []).slice(0, 2)
      .map(s => `<span class="chip chip-blue" title="${s.name}">${s.name.split(' ').slice(0,2).join(' ')}</span>`).join('')
      + (( p.probiotic_strains?.length || 0) > 2
          ? `<span class="chip chip-gray">+${p.probiotic_strains.length - 2}</span>` : '');

    const enrichedBadge = p.detail_sources
      ? `<span class="chip chip-green">✓ yes</span>`
      : `<span class="chip chip-gray">— no</span>`;

    const cfu = p.total_cfu_billion != null ? p.total_cfu_billion + 'B' : '—';

    return `<tr onclick="openProductDetail(${i})">
      <td style="font-weight:600;white-space:nowrap">${p.market_name || p.brand || '—'}</td>
      <td style="max-width:300px;font-size:12px">${p.name || '—'}</td>
      <td style="font-size:12px;white-space:nowrap">${p.form || '—'}</td>
      <td style="font-size:12px;color:#555;white-space:nowrap">${p.serving_size || '—'}</td>
      <td style="font-size:12px;white-space:nowrap">${cfu}</td>
      <td><div class="chips">${strainChips || '—'}</div></td>
      <td><div class="chips">${sourceTags(p.detail_sources)}</div></td>
      <td>${enrichedBadge}</td>
    </tr>`;
  }).join('');
}

function openProductDetail(idx) {
  document.querySelectorAll('#productsBody tr.selected').forEach(r => r.classList.remove('selected'));
  document.querySelectorAll('#productsBody tr')[idx]?.classList.add('selected');

  const p = filteredProducts[idx];
  document.getElementById('panelTitle').textContent = p.name || '—';
  document.getElementById('panelSubtitle').textContent = p.market_name || p.brand || '';

  const row = (label, v) =>
    `<div class="detail-row"><span class="detail-label">${label}</span><span class="detail-value">${v ?? '—'}</span></div>`;

  const factRows = (p.supplement_facts || []).map(f =>
    `<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #f5f5f5;font-size:12px">
      <span style="color:#444;flex:1">${f.name}</span>
      <span style="color:#888;white-space:nowrap;margin-left:12px">${f.amount || '—'}</span>
    </div>`
  ).join('');

  const strainRows = (p.probiotic_strains || []).map(s =>
    `<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #f5f5f5;font-size:12px">
      <span style="color:#15803d;font-style:italic;flex:1">${s.name}</span>
      <span style="color:#888;white-space:nowrap;margin-left:12px">${s.amount || '—'}${s.cfu_billion != null ? ' (' + s.cfu_billion + 'B CFU)' : ''}</span>
    </div>`
  ).join('');

  const sourceKeys = Object.keys(p.detail_sources || {});
  const sourceDetail = sourceKeys.map(src => {
    const fields = (p.detail_sources[src] || []).join(', ');
    return `<div class="detail-row"><span class="detail-label">${src.toUpperCase()}</span><span class="detail-value mono" style="font-size:11px">${fields}</span></div>`;
  }).join('');

  document.getElementById('panelBody').innerHTML = `
    <div class="detail-section">
      <div class="detail-section-title">Product Info</div>
      ${row('Brand', p.market_name || p.brand)}
      ${row('Form', p.form)}
      ${row('Serving size', p.serving_size)}
      ${row('Servings / container', p.servings_per_container)}
      ${row('Net content', p.net_content)}
      ${p.total_cfu_billion != null ? row('Total CFU', p.total_cfu_billion + ' Billion') : ''}
    </div>
    ${strainRows ? `<div class="detail-section">
      <div class="detail-section-title">Probiotic Strains (${(p.probiotic_strains || []).length})</div>
      ${strainRows}
    </div>` : ''}
    ${factRows ? `<div class="detail-section">
      <div class="detail-section-title">Supplement Facts (${(p.supplement_facts || []).length})</div>
      ${factRows}
    </div>` : ''}
    <div class="detail-section">
      <div class="detail-section-title">Source</div>
      ${row('Original source', p.source)}
      ${p.url && p.url !== 'https://www.iherb.com/New-Products' ? `<div class="detail-row"><span class="detail-label">URL</span><a href="${p.url}" target="_blank" style="font-size:12px;color:#1d4ed8;word-break:break-all">${p.url}</a></div>` : ''}
      ${p.dsld_id ? row('DSLD ID', `<span class="detail-value mono">${p.dsld_id}</span>`) : ''}
      ${p.dsld_product_name ? row('DSLD name', p.dsld_product_name) : ''}
    </div>
    ${sourceDetail ? `<div class="detail-section">
      <div class="detail-section-title">Data Sources</div>
      ${sourceDetail}
    </div>` : ''}
    ${p.description ? `<div class="detail-section">
      <div class="detail-section-title">Description</div>
      <div style="font-size:13px;line-height:1.65;color:#555">${p.description}</div>
    </div>` : ''}
  `;

  document.getElementById('overlay').classList.add('open');
  document.getElementById('panel').classList.add('open');
}

// ── Init ───────────────────────────────────────────────────────────────────────
loadStrains();
loadProducts();
</script>
</body>
</html>"""
