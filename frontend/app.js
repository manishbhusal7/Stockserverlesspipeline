"use strict";

/**
 * TRE Watchlist — frontend application
 *
 * Fetches GET /movers from the API Gateway endpoint defined in config.js,
 * then renders a Chart.js bar chart and per-day mover cards.
 */

// ── Config ────────────────────────────────────────────────────────────────

const API_URL =
  (window.APP_CONFIG && window.APP_CONFIG.apiUrl !== "PLACEHOLDER_API_URL"
    ? window.APP_CONFIG.apiUrl
    : null);

// ── DOM refs ──────────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

const elLoading = $("state-loading");
const elError   = $("state-error");
const elEmpty   = $("state-empty");
const elContent = $("content");
const elErrorMsg = $("error-msg");

const elStatCount   = $("stat-count");
const elStatBest    = $("stat-best");
const elStatWorst   = $("stat-worst");
const elStatUpdated = $("stat-updated");
const elGrid        = $("movers-grid");

let chartInstance = null;
let allMoversData = [];
let selectedTickerFilter = null;
let selectedDirectionFilter = "all";


// ── State helpers ─────────────────────────────────────────────────────────

function showLoading() {
  elLoading.classList.remove("hidden");
  elError.classList.add("hidden");
  elEmpty.classList.add("hidden");
  elContent.classList.add("hidden");
}

function showError(msg) {
  elLoading.classList.add("hidden");
  elError.classList.remove("hidden");
  elContent.classList.add("hidden");
  elErrorMsg.textContent = msg || "Could not load data. Please try again later.";
}

function showEmpty() {
  elLoading.classList.add("hidden");
  elEmpty.classList.remove("hidden");
  elContent.classList.add("hidden");
}

function showContent() {
  elLoading.classList.add("hidden");
  elError.classList.add("hidden");
  elEmpty.classList.add("hidden");
  elContent.classList.remove("hidden");
}

// ── Formatting helpers ─────────────────────────────────────────────────────

function formatDate(iso) {
  // "2026-06-07" → "Jun 7, 2026"
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
  });
}

function formatShortDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    month: "short", day: "numeric",
  });
}

function formatPct(v) {
  return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
}

function formatPrice(v) {
  return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// ── Chart ─────────────────────────────────────────────────────────────────

function renderChart(movers) {
  const sorted = [...movers].sort((a, b) => a.date.localeCompare(b.date));

  const labels  = sorted.map((m) => formatShortDate(m.date));
  const values  = sorted.map((m) => m.pct_change);
  const colors  = values.map((v) =>
    v >= 0
      ? "rgba(63, 185, 80, 0.80)"
      : "rgba(248, 81, 73, 0.80)"
  );
  const borders = values.map((v) =>
    v >= 0 ? "rgba(63, 185, 80, 1)" : "rgba(248, 81, 73, 1)"
  );

  const ctx = document.getElementById("movementChart").getContext("2d");

  if (chartInstance) chartInstance.destroy();

  chartInstance = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "% Change (Open → Close)",
        data: values,
        backgroundColor: colors,
        borderColor: borders,
        borderWidth: 1.5,
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const m = sorted[ctx.dataIndex];
              return [
                ` ${m.ticker}  ${formatPct(m.pct_change)}`,
                ` Close: ${formatPrice(m.close_price)}`,
              ];
            },
          },
          backgroundColor: "#161b22",
          borderColor: "#30363d",
          borderWidth: 1,
          titleColor: "#e6edf3",
          bodyColor: "#8b949e",
          padding: 12,
        },
      },
      scales: {
        x: {
          grid: { color: "rgba(48,54,61,0.5)" },
          ticks: { color: "#8b949e", font: { family: "Inter" } },
        },
        y: {
          grid: { color: "rgba(48,54,61,0.5)" },
          ticks: {
            color: "#8b949e",
            font: { family: "JetBrains Mono, monospace", size: 11 },
            callback: (v) => (v >= 0 ? "+" : "") + v.toFixed(1) + "%",
          },
        },
      },
    },
  });
}

// ── Summary bar ────────────────────────────────────────────────────────────

function renderSummary(movers) {
  elStatCount.textContent = movers.length;

  if (!movers.length) return;

  const best  = movers.reduce((a, b) => b.pct_change > a.pct_change ? b : a);
  const worst = movers.reduce((a, b) => b.pct_change < a.pct_change ? b : a);

  elStatBest.textContent  = `${best.ticker} ${formatPct(best.pct_change)}`;
  elStatWorst.textContent = `${worst.ticker} ${formatPct(worst.pct_change)}`;

  elStatUpdated.textContent = new Date().toLocaleTimeString("en-US", {
    hour: "2-digit", minute: "2-digit",
  });
}

// ── Mover cards ────────────────────────────────────────────────────────────

function renderCards(movers) {
  elGrid.innerHTML = "";

  movers.forEach((m) => {
    const isGain   = m.pct_change >= 0;
    const dirLabel = isGain ? "▲ Gain" : "▼ Loss";
    const cls      = isGain ? "gain" : "loss";

    const card = document.createElement("article");
    card.className = `mover-card ${cls}`;
    card.innerHTML = `
      <div class="mover-header">
        <span class="mover-ticker">${m.ticker}</span>
        <span class="mover-date">${formatDate(m.date)}</span>
      </div>

      <div>
        <div class="mover-change">${formatPct(m.pct_change)}</div>
        <span class="mover-direction-badge">${dirLabel}</span>
      </div>

      <div class="mover-prices">
        <div class="mover-price-item">
          <span class="price-label">Close</span>
          <span class="price-value">${formatPrice(m.close_price)}</span>
        </div>
        <div class="mover-price-item">
          <span class="price-label">Open</span>
          <span class="price-value">${formatPrice(m.open_price)}</span>
        </div>
        <div class="mover-price-item">
          <span class="price-label">Move</span>
          <span class="price-value">${formatPrice(Math.abs(m.close_price - m.open_price))}</span>
        </div>
      </div>
    `;
    elGrid.appendChild(card);
  });
}

// ── Interactive Filters ────────────────────────────────────────────────────

function applyFiltersAndRender() {
  let filtered = [...allMoversData];

  // 1. Ticker filter
  if (selectedTickerFilter) {
    filtered = filtered.filter((m) => m.ticker === selectedTickerFilter);
  }

  // 2. Direction filter
  if (selectedDirectionFilter === "gain") {
    filtered = filtered.filter((m) => m.pct_change >= 0);
  } else if (selectedDirectionFilter === "loss") {
    filtered = filtered.filter((m) => m.pct_change < 0);
  }

  // 3. Render elements
  renderSummary(filtered);
  renderChart(filtered);
  renderCards(filtered);

  if (filtered.length === 0) {
    elGrid.innerHTML = `
      <div style="grid-column: 1 / -1; text-align: center; color: var(--text-muted); padding: 3rem 1rem; border: 1px dashed var(--border); border-radius: var(--radius); background: var(--bg-card);">
        No movers match the current filters.
      </div>
    `;
  }
}

function setDirectionFilter(dir) {
  selectedDirectionFilter = dir;
  ["all", "gain", "loss"].forEach((d) => {
    const btn = document.getElementById(`filter-dir-${d}`);
    if (btn) {
      if (d === dir) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    }
  });
  applyFiltersAndRender();
}

function setupFilters() {
  const btnAll  = document.getElementById("filter-dir-all");
  const btnGain = document.getElementById("filter-dir-gain");
  const btnLoss = document.getElementById("filter-dir-loss");

  if (btnAll)  btnAll.addEventListener("click", () => setDirectionFilter("all"));
  if (btnGain) btnGain.addEventListener("click", () => setDirectionFilter("gain"));
  if (btnLoss) btnLoss.addEventListener("click", () => setDirectionFilter("loss"));

  const pills = document.querySelectorAll(".watchlist-pills .pill");
  pills.forEach((pill) => {
    pill.addEventListener("click", () => {
      const ticker = pill.textContent.trim();
      if (selectedTickerFilter === ticker) {
        selectedTickerFilter = null;
        pill.classList.remove("active");
      } else {
        selectedTickerFilter = ticker;
        pills.forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
      }
      applyFiltersAndRender();
    });
  });
}

// ── Data fetching ─────────────────────────────────────────────────────────

async function loadData() {
  showLoading();

  if (!API_URL) {
    showError("API URL is not configured. See frontend/config.js.");
    return;
  }

  try {
    const resp = await fetch(API_URL, {
      headers: { Accept: "application/json" },
    });

    if (!resp.ok) {
      throw new Error(`API returned HTTP ${resp.status}`);
    }

    const json = await resp.json();

    if (!json.data || json.data.length === 0) {
      showEmpty();
      return;
    }

    allMoversData = json.data;
    applyFiltersAndRender();
    showContent();

  } catch (err) {
    console.error("Failed to load movers:", err);
    showError(`Error: ${err.message}`);
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────

setupFilters();
loadData();

// Auto-refresh every hour so the page stays current without a manual reload
setInterval(loadData, 60 * 60 * 1000);

