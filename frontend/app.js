"use strict";

/**
 * TRE Watchlist Terminal — Frontend Logic
 *
 * Connects to GET /movers with pagination, conditional ETag validation,
 * multiple ticker selections, and custom spreadsheet views.
 */

// App configuration

const API_URL =
  (window.APP_CONFIG && window.APP_CONFIG.apiUrl !== "PLACEHOLDER_API_URL"
    ? window.APP_CONFIG.apiUrl
    : null);

// DOM references

const $ = (id) => document.getElementById(id);

const elLoading = $("state-loading");
const elError   = $("state-error");
const elEmpty   = $("state-empty");
const elContent = $("content");
const elErrorMsg = $("error-msg");

const elStatCount     = $("stat-count");
const elStatBest      = $("stat-best");
const elStatWorst     = $("stat-worst");
const elStatAvg       = $("stat-avg");
const elStatUpdated   = $("stat-updated");

const elGrid          = $("movers-grid");
const elTableBody     = $("movers-table-body");
const elTableWrapper  = $("movers-table-wrapper");
const elWatchlistList = $("watchlist-checklist");

const elToggleGrid    = $("toggle-view-grid");
const elToggleTable   = $("toggle-view-table");

const elDiagCache     = $("diag-cache-status");
const elDiagGw        = $("diag-gw-status");
const elApiModeVal    = $("api-mode-val");

// Application state variables

let allMoversData = [];
let selectedTickers = new Set(["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"]);
let selectedDirectionFilter = "all"; // "all" | "gain" | "loss"
let currentLimit = 7;
let currentViewMode = "grid"; // "grid" | "table"

// Simple client-side cache mapping: { limit: { data: [...], etag: "W/xxx" } }
const clientCache = {};
let chartInstance = null;

// Utility formatting helpers

function formatDate(iso) {
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

// Interface state toggles

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
  elErrorMsg.textContent = msg || "Could not load data. Please check configuration.";
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

// Checklist UI component for watchlist filters

function rebuildWatchlistChecklist() {
  elWatchlistList.innerHTML = "";
  const tickersList = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"];

  tickersList.forEach((ticker) => {
    // Count occurrences of this ticker in the current dataset
    const count = allMoversData.filter((m) => m.ticker === ticker).length;
    const isActive = selectedTickers.has(ticker);

    const item = document.createElement("div");
    item.className = `watchlist-item ${isActive ? "active" : ""}`;
    item.innerHTML = `
      <div class="item-left">
        <span class="checkbox-custom"></span>
        <span class="item-ticker">${ticker}</span>
      </div>
      <span class="item-badge">${count} pts</span>
    `;

    item.addEventListener("click", () => {
      if (selectedTickers.has(ticker)) {
        // Don't deselect the last ticker to avoid an empty state
        if (selectedTickers.size > 1) {
          selectedTickers.delete(ticker);
        }
      } else {
        selectedTickers.add(ticker);
      }
      rebuildWatchlistChecklist();
      applyFiltersAndRender();
    });

    elWatchlistList.appendChild(item);
  });
}

// Metric calculations for headers

function renderSummary(movers) {
  elStatCount.textContent = movers.length;

  if (!movers.length) {
    elStatBest.textContent = "—";
    elStatWorst.textContent = "—";
    elStatAvg.textContent = "—";
    return;
  }

  const best = movers.reduce((a, b) => (b.pct_change > a.pct_change ? b : a));
  const worst = movers.reduce((a, b) => (b.pct_change < a.pct_change ? b : a));

  elStatBest.textContent = `${best.ticker} ${formatPct(best.pct_change)}`;
  elStatWorst.textContent = `${worst.ticker} ${formatPct(worst.pct_change)}`;

  // Average absolute daily volatility
  const totalVol = movers.reduce((sum, m) => sum + Math.abs(m.pct_change), 0);
  const avgVol = totalVol / movers.length;
  elStatAvg.textContent = formatPct(avgVol);

  elStatUpdated.textContent = new Date().toLocaleTimeString("en-US", {
    hour: "2-digit", minute: "2-digit", second: "2-digit"
  });
}

// Chart rendering using Chart.js

function renderChart(movers) {
  const sorted = [...movers].sort((a, b) => a.date.localeCompare(b.date));

  const labels = sorted.map((m) => `${formatShortDate(m.date)} (${m.ticker})`);
  const values = sorted.map((m) => m.pct_change);

  // Styling properties matching our dark terminal
  const colors = values.map((v) =>
    v >= 0 ? "rgba(16, 185, 129, 0.7)" : "rgba(239, 68, 68, 0.7)"
  );
  const borderColors = values.map((v) =>
    v >= 0 ? "#10b981" : "#ef4444"
  );

  const ctx = document.getElementById("movementChart").getContext("2d");

  if (chartInstance) {
    chartInstance.destroy();
  }

  // Draw custom grid line backgrounds
  chartInstance = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "% Change",
        data: values,
        backgroundColor: colors,
        borderColor: borderColors,
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
          backgroundColor: "#0c1219",
          borderColor: "#1f2d3d",
          borderWidth: 1,
          titleFont: { family: "Outfit, sans-serif", weight: "bold" },
          bodyFont: { family: "JetBrains Mono, monospace" },
          padding: 12,
          cornerRadius: 6,
          callbacks: {
            label: (ctx) => {
              const m = sorted[ctx.dataIndex];
              const netDiff = m.close_price - m.open_price;
              return [
                ` Ticker:      ${m.ticker}`,
                ` Return:      ${formatPct(m.pct_change)}`,
                ` Open Price:  ${formatPrice(m.open_price)}`,
                ` Close Price: ${formatPrice(m.close_price)}`,
                ` Move Delta:  ${formatPrice(netDiff)} (${netDiff >= 0 ? "Gain" : "Loss"})`,
              ];
            },
          },
        },
      },
      scales: {
        x: {
          grid: { color: "#1f2d3d", drawOnChartArea: true },
          ticks: { color: "#8ba2b5", font: { family: "Outfit, sans-serif", size: 10 } },
        },
        y: {
          grid: { color: "#1f2d3d", drawOnChartArea: true },
          ticks: {
            color: "#8ba2b5",
            font: { family: "JetBrains Mono, monospace", size: 10 },
            callback: (val) => (val >= 0 ? "+" : "") + val.toFixed(1) + "%",
          },
        },
      },
    },
  });
}

// Render Grid and Table views

function renderGridView(movers) {
  elGrid.innerHTML = "";

  movers.forEach((m) => {
    const isGain = m.pct_change >= 0;
    const cls = isGain ? "gain" : "loss";
    const dirText = isGain ? "▲ GAIN" : "▼ LOSS";

    const card = document.createElement("div");
    card.className = `mover-card ${cls}`;
    card.innerHTML = `
      <div class="mover-header">
        <span class="mover-ticker">${m.ticker}</span>
        <span class="mover-date">${formatDate(m.date)}</span>
      </div>
      <div class="mover-value-block">
        <span class="mover-change">${formatPct(m.pct_change)}</span>
        <span class="mover-badge">${dirText}</span>
      </div>
      <div class="mover-prices">
        <div class="mover-price-item">
          <span class="price-label">Open</span>
          <span class="price-value">${formatPrice(m.open_price)}</span>
        </div>
        <div class="mover-price-item">
          <span class="price-label">Close</span>
          <span class="price-value">${formatPrice(m.close_price)}</span>
        </div>
        <div class="mover-price-item">
          <span class="price-label">Spread</span>
          <span class="price-value">${formatPrice(Math.abs(m.close_price - m.open_price))}</span>
        </div>
      </div>
    `;
    elGrid.appendChild(card);
  });
}

function renderTableView(movers) {
  elTableBody.innerHTML = "";

  movers.forEach((m) => {
    const isGain = m.pct_change >= 0;
    const cls = isGain ? "gain" : "loss";
    const dirText = isGain ? "▲ GAIN" : "▼ LOSS";
    const netDiff = m.close_price - m.open_price;

    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${formatDate(m.date)}</td>
      <td><span class="table-ticker">${m.ticker}</span></td>
      <td><span class="table-badge ${cls}">${dirText}</span></td>
      <td class="num-col table-pct ${cls}">${formatPct(m.pct_change)}</td>
      <td class="num-col">${formatPrice(m.open_price)}</td>
      <td class="num-col">${formatPrice(m.close_price)}</td>
      <td class="num-col">${formatPrice(netDiff)}</td>
    `;
    elTableBody.appendChild(row);
  });
}

// Aggregated filters for stock search

function applyFiltersAndRender() {
  let filtered = [...allMoversData];

  // 1. Filter by Watchlist checkbox values
  filtered = filtered.filter((m) => selectedTickers.has(m.ticker));

  // 2. Filter by direction button value
  if (selectedDirectionFilter === "gain") {
    filtered = filtered.filter((m) => m.pct_change >= 0);
  } else if (selectedDirectionFilter === "loss") {
    filtered = filtered.filter((m) => m.pct_change < 0);
  }

  // 3. Render calculations and diagrams
  renderSummary(filtered);
  renderChart(filtered);
  renderGridView(filtered);
  renderTableView(filtered);

  // If no items match
  if (filtered.length === 0) {
    const emptyMsg = `
      <div class="empty-filter-block">
        No movers matching the active watchlist / direction parameters.
      </div>
    `;
    elGrid.innerHTML = emptyMsg;
    elTableBody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 3rem;">No matching data</td></tr>`;
  }
}

// Event listener definitions

function setupEventListeners() {
  // Select All Watchlist Tickers
  const btnSelectAll = $("btn-select-all");
  if (btnSelectAll) {
    btnSelectAll.addEventListener("click", () => {
      selectedTickers = new Set(["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"]);
      rebuildWatchlistChecklist();
      applyFiltersAndRender();
    });
  }

  // Direction Segmented Control Buttons
  const directions = ["all", "gain", "loss"];
  directions.forEach((dir) => {
    const btn = $(`filter-dir-${dir}`);
    if (btn) {
      btn.addEventListener("click", () => {
        selectedDirectionFilter = dir;
        directions.forEach((d) => $(`filter-dir-${d}`).classList.remove("active"));
        btn.classList.add("active");
        applyFiltersAndRender();
      });
    }
  });

  // View Mode Toggles
  if (elToggleGrid && elToggleTable) {
    elToggleGrid.addEventListener("click", () => {
      currentViewMode = "grid";
      elToggleGrid.classList.add("active");
      elToggleTable.classList.remove("active");
      elGrid.classList.remove("hidden");
      elTableWrapper.classList.add("hidden");
    });

    elToggleTable.addEventListener("click", () => {
      currentViewMode = "table";
      elToggleTable.classList.add("active");
      elToggleGrid.classList.remove("hidden");
      elGrid.classList.add("hidden");
      elTableWrapper.classList.remove("hidden");
    });
  }
}

// Data loading and ETag caching implementation

async function loadData() {
  showLoading();

  if (!API_URL) {
    showError("Pipeline API Gateway URL is not configured. Setup variables in config.js.");
    return;
  }

  const fetchUrl = `${API_URL}?limit=${currentLimit}`;

  try {
    // Read previous metadata from client cache if present to build conditional ETag headers
    const cachedEntry = clientCache[currentLimit];
    const headers = { Accept: "application/json" };
    
    if (cachedEntry && cachedEntry.etag) {
      headers["If-None-Match"] = cachedEntry.etag;
    }

    const resp = await fetch(fetchUrl, { headers });

    // Handle 304 Not Modified
    if (resp.status === 304 && cachedEntry) {
      console.log(`[Cache Hit] ETag matched: ${cachedEntry.etag}. Utilizing local cache.`);
      allMoversData = cachedEntry.data;
      
      // Update sidebar diagnostic badge
      elDiagCache.textContent = "304 Cache Hit";
      elDiagCache.style.color = "var(--gain)";
      elDiagGw.innerHTML = `<span class="dot"></span>Live (Cached)`;
      
      rebuildWatchlistChecklist();
      applyFiltersAndRender();
      showContent();
      return;
    }

    if (!resp.ok) {
      throw new Error(`Server returned status code: ${resp.status}`);
    }

    // Handle 200 OK
    const json = await resp.json();

    if (!json.data || json.data.length === 0) {
      showEmpty();
      return;
    }

    // Save payload and retrieve ETag header response
    const etagHeader = resp.headers.get("ETag") || resp.headers.get("etag");
    
    allMoversData = json.data;

    // Cache the entry locally
    if (etagHeader) {
      clientCache[currentLimit] = {
        etag: etagHeader,
        data: json.data,
      };
      elDiagCache.textContent = "200 Live Saved";
      elDiagCache.style.color = "var(--accent)";
    } else {
      elDiagCache.textContent = "Disabled";
      elDiagCache.style.color = "var(--text-subtle)";
    }

    elDiagGw.innerHTML = `<span class="dot"></span>Connected`;
    elApiModeVal.textContent = "Massive Live";
    elApiModeVal.className = "badge-val live";

    rebuildWatchlistChecklist();
    applyFiltersAndRender();
    showContent();

  } catch (err) {
    console.error("handshake failed:", err);
    
    // Check if we have *any* cached data for this limit before showing full screen error
    const cachedEntry = clientCache[currentLimit];
    if (cachedEntry) {
      console.warn("API Offline. Utilizing stale fallback client cache.");
      allMoversData = cachedEntry.data;
      elDiagGw.innerHTML = `<span class="dot" style="background-color: var(--loss); box-shadow: 0 0 8px var(--loss)"></span>Offline (Stale)`;
      elDiagCache.textContent = "Offline Fallback";
      elDiagCache.style.color = "var(--loss)";
      
      rebuildWatchlistChecklist();
      applyFiltersAndRender();
      showContent();
    } else {
      showError(`Handshake integration failed: ${err.message}`);
    }
  }
}

// App initialization

setupEventListeners();
loadData();

// Auto-refresh every 30 minutes to keep terminal feeds hot
setInterval(loadData, 30 * 60 * 1000);
