// Pharma Digital Job Tracker — frontend
// Loads jobs.json + candidates.json and renders filterable, sortable tables.

const PAGE_SIZE = 100;

const state = {
  data: null,
  filters: { type: new Set(), seniority: new Set(), country: new Set(),
             source: new Set(), company: new Set() },
  query: "",
  sort: { col: "seniority_rank", dir: "desc" },
  page: 0,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// ----- Boot ---------------------------------------------------------------
async function boot() {
  setupTabs();
  try {
    const [jobsResp, candResp] = await Promise.allSettled([
      fetch("jobs.json", { cache: "no-cache" }),
      fetch("candidates.json", { cache: "no-cache" }),
    ]);
    if (jobsResp.status === "fulfilled" && jobsResp.value.ok) {
      state.data = await jobsResp.value.json();
    } else {
      throw new Error("jobs.json missing");
    }
    if (candResp.status === "fulfilled" && candResp.value.ok) {
      state.candidates = await candResp.value.json();
    }
  } catch (err) {
    document.body.innerHTML = `<div style="padding:40px;text-align:center;font-family:system-ui">
      <h2>No data yet</h2>
      <p>Run <code>python scraper/run.py</code> to generate <code>docs/jobs.json</code>.</p>
      <p style="color:#888">${err.message}</p>
    </div>`;
    return;
  }
  renderHeader();
  buildFilters();
  setupSearch();
  setupSort();
  setupReset();
  render();
  renderWatchlist();
  renderDiscovery();
  loadDigestLink();
}

async function loadDigestLink() {
  try {
    const r = await fetch("digests/index.json", { cache: "no-cache" });
    if (!r.ok) return;
    const idx = await r.json();
    if (!idx.latest) return;
    const url = `digests/${idx.latest}`;
    const wrap = document.getElementById("digest-link-wrap");
    const a = document.getElementById("digest-link");
    a.href = url;
    a.title = `${idx.new_jobs} new jobs this week`;
    wrap.hidden = false;
    const aboutLink = document.getElementById("about-digest-link");
    if (aboutLink) aboutLink.href = url;
  } catch {}
}

// ----- Tabs ---------------------------------------------------------------
function setupTabs() {
  $$(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.tab;
      $$(".tab").forEach((b) => b.classList.toggle("active", b === btn));
      $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${id}`));
    });
  });
}

// ----- Header -------------------------------------------------------------
function renderHeader() {
  $("#job-count").textContent = state.data.total_jobs.toLocaleString();
  const watchlistCount = (state.data.watchlist || []).length;
  $("#company-count").textContent = (state.data.total_companies + watchlistCount).toLocaleString();
  const ts = new Date(state.data.generated_at);
  $("#generated-at").textContent = ts.toLocaleString();
}

// ----- Filters ------------------------------------------------------------
function buildFilters() {
  const buckets = {
    type: tally("company_type"),
    seniority: tally("seniority"),
    country: tally("country"),
    source: tally("source"),
  };
  buildCheckboxes("type", buckets.type, (k) => state.data.type_labels[k] || k);
  buildCheckboxes("seniority", buckets.seniority, (k) => state.data.seniority_labels[k] || k,
                  state.data.seniority_order);
  buildCheckboxes("country", buckets.country, (k) => k || "—");
  buildCheckboxes("source", buckets.source, (k) => k || "—");
  buildCompanyFilter(tally("company"));
}

function buildCompanyFilter(tally) {
  const list = document.getElementById("company-list");
  const search = document.getElementById("company-search");
  const entries = [...tally.entries()]
    .filter(([k]) => !!k)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));

  function paint(filter = "") {
    const f = filter.toLowerCase();
    list.innerHTML = "";
    let shown = 0;
    for (const [val, count] of entries) {
      if (f && !val.toLowerCase().includes(f)) continue;
      if (!f && shown >= 100) break;   // cap top-N when not searching
      shown++;
      const id = `f-company-${val.replace(/\W/g, "_")}`;
      const wrap = document.createElement("label");
      wrap.innerHTML = `
        <input type="checkbox" id="${id}" value="${escape(val)}"
               ${state.filters.company.has(val) ? "checked" : ""}>
        <span>${escape(val)}</span>
        <span class="pill">${count}</span>`;
      wrap.querySelector("input").addEventListener("change", (e) => {
        if (e.target.checked) state.filters.company.add(val);
        else state.filters.company.delete(val);
        state.page = 0;
        render();
      });
      list.appendChild(wrap);
    }
    if (!shown) list.innerHTML = `<div class="muted small" style="padding:6px">No matches</div>`;
  }

  paint();
  search.addEventListener("input", (e) => paint(e.target.value.trim()));
}

function tally(key) {
  const m = new Map();
  for (const j of state.data.jobs) {
    const v = j[key] || "";
    m.set(v, (m.get(v) || 0) + 1);
  }
  return m;
}

function buildCheckboxes(name, tally, label, order) {
  const root = $(`#filter-${name}`);
  let entries = [...tally.entries()];
  if (order) {
    const idx = new Map(order.map((k, i) => [k, i]));
    entries.sort((a, b) => (idx.get(a[0]) ?? 99) - (idx.get(b[0]) ?? 99));
  } else {
    entries.sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }
  for (const [val, count] of entries) {
    if (!val) continue;
    const id = `f-${name}-${val.replace(/\W/g, "_")}`;
    const wrap = document.createElement("label");
    wrap.innerHTML = `
      <input type="checkbox" id="${id}" value="${escape(val)}">
      <span>${escape(label(val))}</span>
      <span class="pill">${count}</span>`;
    wrap.querySelector("input").addEventListener("change", (e) => {
      if (e.target.checked) state.filters[name].add(val);
      else state.filters[name].delete(val);
      state.page = 0;
      render();
    });
    root.appendChild(wrap);
  }
}

function setupSearch() {
  let t;
  $("#q").addEventListener("input", (e) => {
    clearTimeout(t);
    t = setTimeout(() => {
      state.query = e.target.value.trim().toLowerCase();
      state.page = 0;
      render();
    }, 120);
  });
}

function setupReset() {
  $("#reset-filters").addEventListener("click", () => {
    state.query = "";
    $("#q").value = "";
    for (const k of Object.keys(state.filters)) state.filters[k].clear();
    $$('input[type=checkbox]').forEach((c) => (c.checked = false));
    const cs = document.getElementById("company-search");
    if (cs) { cs.value = ""; cs.dispatchEvent(new Event("input")); }
    state.page = 0;
    render();
  });
}

function setupSort() {
  $$("th.sortable").forEach((th) => {
    th.addEventListener("click", () => {
      const col = th.dataset.sort;
      if (state.sort.col === col) {
        state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
      } else {
        state.sort.col = col;
        state.sort.dir = col === "seniority_rank" || col === "posted_at" ? "desc" : "asc";
      }
      $$("th.sortable").forEach((h) => h.classList.remove("sorted-asc", "sorted-desc"));
      th.classList.add(state.sort.dir === "asc" ? "sorted-asc" : "sorted-desc");
      render();
    });
  });
}

// ----- Render -------------------------------------------------------------
function applyFilters() {
  const q = state.query;
  return state.data.jobs.filter((j) => {
    for (const k of Object.keys(state.filters)) {
      if (state.filters[k].size && !state.filters[k].has(j[k] || "")) return false;
    }
    if (q) {
      const blob = `${j.title} ${j.company} ${j.location} ${j.department}`.toLowerCase();
      if (!blob.includes(q)) return false;
    }
    return true;
  });
}

function applySort(rows) {
  const { col, dir } = state.sort;
  const m = dir === "asc" ? 1 : -1;
  return rows.slice().sort((a, b) => {
    const va = a[col] ?? "";
    const vb = b[col] ?? "";
    if (typeof va === "number" && typeof vb === "number") return (va - vb) * m;
    return String(va).localeCompare(String(vb)) * m;
  });
}

function render() {
  const rows = applySort(applyFilters());
  renderActiveFilters();
  renderCounters();
  renderTable(rows);
  renderPager(rows.length);
}

function renderActiveFilters() {
  const root = $("#active-filters");
  root.innerHTML = "";
  for (const [name, set] of Object.entries(state.filters)) {
    for (const v of set) {
      const label = name === "type" ? state.data.type_labels[v]
                  : name === "seniority" ? state.data.seniority_labels[v]
                  : v;
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = `${cap(name)}: ${label}`;
      chip.addEventListener("click", () => {
        set.delete(v);
        const cb = document.getElementById(`f-${name}-${v.replace(/\W/g, "_")}`);
        if (cb) cb.checked = false;
        state.page = 0; render();
        // re-paint the company list when a chip removed it
        if (name === "company") {
          const search = document.getElementById("company-search");
          if (search) search.dispatchEvent(new Event("input"));
        }
      });
      root.appendChild(chip);
    }
  }
}

function renderCounters() {
  for (const k of Object.keys(state.filters)) {
    const n = state.filters[k].size;
    $(`#cnt-${k}`).textContent = n ? n : "";
  }
}

function renderTable(rows) {
  const tbody = $("#jobs-tbody");
  const start = state.page * PAGE_SIZE;
  const slice = rows.slice(start, start + PAGE_SIZE);
  if (!slice.length) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:32px;color:#888">No matching jobs.</td></tr>`;
    return;
  }
  tbody.innerHTML = slice.map((j) => `
    <tr>
      <td><span class="seniority s-${j.seniority}">${escape(j.seniority_label)}</span></td>
      <td class="title">${escape(j.title)}</td>
      <td class="company">${escape(j.company)}${j.country ? ` <span class="muted small">(${j.country})</span>` : ""}</td>
      <td><span class="badge b-${j.company_type}">${escape(j.type_label)}</span></td>
      <td>${escape(j.location)}</td>
      <td class="muted small">${formatSalary(j)}</td>
      <td class="muted small">${formatDate(j.posted_at)}</td>
      <td>${j.url ? `<a class="apply-btn" href="${escape(j.url)}" target="_blank" rel="noopener">View</a>` : ""}</td>
    </tr>`).join("");
}

function formatSalary(j) {
  if (!j.salary_min && !j.salary_max) return "—";
  const lo = j.salary_min, hi = j.salary_max;
  const fmt = (n) => {
    if (n == null) return "?";
    if (n >= 1000) return Math.round(n / 1000) + "k";
    return n.toLocaleString();
  };
  const range = (lo && hi && lo !== hi) ? `${fmt(lo)}–${fmt(hi)}`
              : `${fmt(hi || lo)}`;
  const tag = j.salary_predicted ? `<span title="Predicted by Adzuna" style="opacity:0.6">~</span>` : "";
  return `${tag}${range}`;
}

function renderPager(total) {
  const pages = Math.ceil(total / PAGE_SIZE);
  const root = $("#pager");
  if (pages <= 1) { root.innerHTML = `${total} result${total === 1 ? "" : "s"}`; return; }
  const start = state.page * PAGE_SIZE + 1;
  const end = Math.min(total, start + PAGE_SIZE - 1);
  root.innerHTML = `
    <button ${state.page === 0 ? "disabled" : ""}>← Prev</button>
    <span>Showing ${start.toLocaleString()}–${end.toLocaleString()} of ${total.toLocaleString()}</span>
    <button ${state.page >= pages - 1 ? "disabled" : ""}>Next →</button>`;
  const [prev, , next] = root.children;
  prev.addEventListener("click", () => { state.page--; render(); window.scrollTo(0, 0); });
  next.addEventListener("click", () => { state.page++; render(); window.scrollTo(0, 0); });
}

// ----- Watchlist ----------------------------------------------------------
function renderWatchlist() {
  const grid = $("#watchlist-grid");
  const items = (state.data.watchlist || []).slice().sort((a, b) =>
    a.type.localeCompare(b.type) || a.name.localeCompare(b.name));
  grid.innerHTML = items.map((w) => `
    <div class="card">
      <a href="${escape(w.url)}" target="_blank" rel="noopener">${escape(w.name)} ↗</a>
      <div class="row">
        <span class="badge b-${w.type}">${escape(w.type_label)}</span>
        ${w.country ? `<span class="muted">${w.country}</span>` : ""}
      </div>
    </div>`).join("");
}

// ----- Discovery ----------------------------------------------------------
function renderDiscovery() {
  // Conferences (always render, independent of candidates)
  const confGrid = $("#conferences-grid");
  if (confGrid) {
    const confs = (state.candidates && state.candidates.conferences) || [];
    confGrid.innerHTML = confs.map((c) => `
      <div class="card">
        <a href="${escape(c.url)}" target="_blank" rel="noopener">${escape(c.name)} ↗</a>
        <div class="row">
          <span class="muted">${escape(c.region)}</span>
          <span class="muted">· ${escape(c.focus)}</span>
        </div>
      </div>`).join("");
  }

  if (!state.candidates) {
    $("#discovery-meta").textContent = "No discovery data yet — run python scraper/discover.py";
    return;
  }
  const c = state.candidates;
  const srcParts = Object.entries(c.sources || {})
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${escape(k)}: ${v}`).join(" · ");
  $("#discovery-meta").innerHTML =
    `<strong>${c.count.toLocaleString()}</strong> unique candidates from
     <strong>${Object.keys(c.sources || {}).length}</strong> sources
     · generated ${new Date(c.generated_at).toLocaleString()}<br>
     <span class="muted small">${srcParts}</span>`;

  const allRows = (c.candidates || []).slice().sort((a, b) => a.name.localeCompare(b.name));
  const renderRows = (rows) => {
    const tbody = $("#discovery-tbody");
    tbody.innerHTML = rows.slice(0, 500).map((r) => {
      const evidence = (r.evidence || [])[0];
      const link = evidence?.url || r.website;
      const linkLabel = evidence ? evidence.source : (r.website ? "site" : "");
      return `
        <tr>
          <td><strong>${escape(r.name)}</strong></td>
          <td>${(r.sources || []).map(s => `<span class="badge">${escape(s)}</span>`).join(" ")}</td>
          <td class="muted small">${escape(r.one_liner || "")}</td>
          <td>${escape(r.stage || "—")}</td>
          <td>${escape(r.batch || "—")}</td>
          <td>${r.team_size || "—"}</td>
          <td class="muted small">${escape((r.location || "").toString().slice(0, 60))}</td>
          <td>${link ? `<a href="${escape(link)}" target="_blank" rel="noopener">${escape(linkLabel)} ↗</a>` : ""}</td>
        </tr>`;
    }).join("");
    if (rows.length > 500) {
      tbody.innerHTML += `<tr><td colspan="8" class="muted small" style="text-align:center;padding:12px">…showing first 500 of ${rows.length}</td></tr>`;
    }
  };
  renderRows(allRows);

  $("#discovery-search").addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    if (!q) return renderRows(allRows);
    renderRows(allRows.filter((r) =>
      (r.name + " " + (r.one_liner || "")).toLowerCase().includes(q)));
  });
}

// ----- Helpers ------------------------------------------------------------
function escape(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function formatDate(s) {
  if (!s) return "—";
  // Workday returns "Posted 4 Days Ago" — pass through.
  if (typeof s === "string" && /posted/i.test(s)) return s.replace(/^Posted\s*/i, "");
  const d = new Date(s);
  if (isNaN(d)) return s;
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  if (days < 0) return d.toLocaleDateString();
  if (days === 0) return "today";
  if (days === 1) return "1d ago";
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return d.toLocaleDateString();
}

function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

document.addEventListener("DOMContentLoaded", boot);
