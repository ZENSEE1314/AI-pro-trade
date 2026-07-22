let DATA = null;
let currentSymbol = "BTCUSDT";
let sortKey = "sharpe";
let sortDir = -1;
let selectedStrategy = null;
let eqChart = null;
const equityCache = {};

const COLS = [
  ["strategy", "Strategy"],
  ["total_return_pct", "Return %"],
  ["cagr_pct", "CAGR %"],
  ["sharpe", "Sharpe"],
  ["sortino", "Sortino"],
  ["max_drawdown_pct", "Max DD %"],
  ["win_rate_pct", "Win %"],
  ["profit_factor", "PF"],
  ["num_trades", "Trades"],
  ["exposure_pct", "Expo %"],
];

async function init() {
  DATA = await (await fetch("/api/results")).json();
  if (DATA.error) {
    document.getElementById("tbl").innerHTML = `<tr><td>${DATA.error}</td></tr>`;
    return;
  }
  const tabs = document.getElementById("symTabs");
  DATA.symbols.forEach(s => {
    const b = document.createElement("div");
    b.className = "tab" + (s === currentSymbol ? " active" : "");
    b.textContent = s.replace("USDT", "");
    b.onclick = () => { currentSymbol = s; selectedStrategy = null; render(); };
    tabs.appendChild(b);
  });
  render();
  loadLiquidations();
  setInterval(loadLiquidations, 10000);
}

function rowsFor(symbol) {
  return DATA.results.filter(r => r.symbol === symbol)
    .slice().sort((a, b) => (a[sortKey] < b[sortKey] ? 1 : -1) * sortDir * -1);
}

function fmt(v, key) {
  if (typeof v !== "number") return v;
  const cls = (key.includes("return") || key.includes("cagr") || key === "sharpe" ||
    key === "sortino" || key === "profit_factor")
    ? (v > (key === "profit_factor" ? 1 : 0) ? "pos" : "neg") : "";
  return `<span class="${cls}">${v.toLocaleString()}</span>`;
}

function render() {
  document.querySelectorAll(".tab").forEach(t =>
    t.classList.toggle("active", t.textContent === currentSymbol.replace("USDT", "")));
  document.getElementById("symLabel").textContent = currentSymbol;

  const rows = rowsFor(currentSymbol);
  if (!selectedStrategy) selectedStrategy = rows[0]?.strategy;

  const thead = document.querySelector("#tbl thead");
  thead.innerHTML = "<tr>" + COLS.map(([k, label]) =>
    `<th data-k="${k}">${label}${sortKey === k ? (sortDir < 0 ? " ▼" : " ▲") : ""}</th>`).join("") + "</tr>";
  thead.querySelectorAll("th").forEach(th => th.onclick = () => {
    const k = th.dataset.k;
    if (sortKey === k) sortDir *= -1; else { sortKey = k; sortDir = -1; }
    render();
  });

  const tbody = document.querySelector("#tbl tbody");
  tbody.innerHTML = rows.map(r => `<tr class="row ${r.strategy === selectedStrategy ? "selected" : ""}" data-s="${r.strategy}">
    ${COLS.map(([k]) => k === "strategy"
      ? `<td>${r.strategy}<span class="cat">${r.category}</span></td>`
      : `<td>${fmt(r[k], k)}</td>`).join("")}</tr>`).join("");
  tbody.querySelectorAll("tr.row").forEach(tr => tr.onclick = () => {
    selectedStrategy = tr.dataset.s; render();
  });

  const best = rows.slice().sort((a, b) => b.sharpe - a.sharpe)[0];
  const bh = rows.find(r => r.category === "Benchmark");
  document.getElementById("stats").innerHTML = `
    <div class="stat"><div class="v">${rows.length}</div><div class="l">strategies tested</div></div>
    <div class="stat"><div class="v pos">${best ? best.strategy : "—"}</div><div class="l">best sharpe (${best ? best.sharpe : ""})</div></div>
    <div class="stat"><div class="v ${bh && bh.total_return_pct > 0 ? "pos" : "neg"}">${bh ? bh.total_return_pct + "%" : "—"}</div><div class="l">buy &amp; hold return</div></div>
    <div class="stat"><div class="v">${rows.filter(r => r.sharpe > (bh ? bh.sharpe : 0)).length}</div><div class="l">beat buy &amp; hold (sharpe)</div></div>`;

  drawEquity();
}

async function drawEquity() {
  if (!equityCache[currentSymbol]) {
    equityCache[currentSymbol] = await (await fetch(`/api/equity/${currentSymbol}`)).json();
  }
  const curves = equityCache[currentSymbol];
  const curve = curves[selectedStrategy];
  const bench = curves["Buy & Hold"];
  if (!curve) return;
  document.getElementById("eqTitle").textContent = `Equity — ${selectedStrategy} (${currentSymbol})`;
  const ds = [{
    label: selectedStrategy, data: curve.v, borderColor: "#5b8cff",
    borderWidth: 1.6, pointRadius: 0, tension: .15,
  }];
  if (bench && selectedStrategy !== "Buy & Hold") ds.push({
    label: "Buy & Hold", data: bench.v, borderColor: "#8b98ad",
    borderWidth: 1, pointRadius: 0, borderDash: [4, 4], tension: .15,
  });
  if (eqChart) eqChart.destroy();
  eqChart = new Chart(document.getElementById("eqChart"), {
    type: "line",
    data: { labels: curve.t, datasets: ds },
    options: {
      maintainAspectRatio: false, animation: false,
      scales: {
        x: { ticks: { color: "#8b98ad", maxTicksLimit: 6 }, grid: { color: "rgba(35,44,61,.4)" } },
        y: { type: "logarithmic", ticks: { color: "#8b98ad" }, grid: { color: "rgba(35,44,61,.4)" } },
      },
      plugins: { legend: { labels: { color: "#e6edf7", boxWidth: 12 } } },
    },
  });
}

async function loadLiquidations() {
  try {
    const d = await (await fetch("/api/liquidations")).json();
    const st = document.getElementById("liqStatus");
    st.textContent = d.status.connected ? "● live" : "○ offline (exchange feed unreachable from this host)";
    st.style.color = d.status.connected ? "#2dd4a7" : "#8b98ad";
    document.getElementById("liqSummary").innerHTML = Object.entries(d.summary).map(([sym, s]) => `
      <div class="stat"><div class="v">${sym.replace("USDT", "")}</div>
      <div class="l"><span class="neg">L $${Math.round(s.long_liqs_usd).toLocaleString()}</span> ·
      <span class="pos">S $${Math.round(s.short_liqs_usd).toLocaleString()}</span></div></div>`).join("");
    document.getElementById("liqFeed").innerHTML = d.events.slice(0, 40).map(e => `
      <div class="liq-item">
        <span>${e.symbol.replace("USDT", "")} <span class="badge ${e.side === "SELL" ? "long" : "short"}">${e.side === "SELL" ? "LONG LIQ" : "SHORT LIQ"}</span></span>
        <span>$${Math.round(e.value_usd).toLocaleString()} @ ${e.price.toLocaleString()}</span>
      </div>`).join("") || `<div class="note">waiting for events…</div>`;
  } catch (e) { /* server not ready */ }
}

init();
