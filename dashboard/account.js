const $ = id => document.getElementById(id);
const token = () => localStorage.getItem("apt_token");
const authHeaders = () => ({ "Content-Type": "application/json", "Authorization": "Bearer " + token() });

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: authHeaders(), ...opts });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function setMsg(id, text, ok) {
  const el = $(id);
  el.textContent = text;
  el.className = "msg " + (ok ? "ok" : "err");
}

async function doAuth(path) {
  try {
    const data = await api(path, {
      method: "POST",
      body: JSON.stringify({ email: $("email").value, password: $("password").value }),
    });
    localStorage.setItem("apt_token", data.token);
    showBot();
  } catch (e) { setMsg("authMsg", e.message, false); }
}

$("btnLogin").onclick = () => doAuth("/api/login");
$("btnRegister").onclick = () => doAuth("/api/register");
$("btnLogout").onclick = () => { localStorage.removeItem("apt_token"); location.reload(); };

$("btnSave").onclick = async () => {
  try {
    const live = $("live").checked;
    if (live && !confirm("Enable LIVE trading? Real market orders will be placed on Bitunix with your funds.")) {
      $("live").checked = false;
      return;
    }
    const s = await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({
        api_key: $("apiKey").value || null,
        api_secret: $("apiSecret").value || null,
        size_usdt: parseFloat($("sizeUsdt").value) || null,
        active: $("active").checked,
        live: $("live").checked,
      }),
    });
    $("apiKey").value = ""; $("apiSecret").value = "";
    fillSettings(s);
    setMsg("saveMsg", "Saved." + (s.live ? " LIVE MODE ON." : " Paper mode."), true);
  } catch (e) { setMsg("saveMsg", e.message, false); }
};

function fillSettings(s) {
  $("keyMask").textContent = s.has_keys ? `(saved: ${s.api_key_masked})` : "(none saved)";
  $("sizeUsdt").value = s.size_usdt;
  $("active").checked = s.active;
  $("live").checked = s.live;
}

async function refreshStatus() {
  try {
    const st = await api("/api/bot/status");
    $("botStatus").innerHTML = Object.entries(st.best_strategies).map(([sym, strat]) => {
      const sig = st.signals[sym];
      const price = st.prices[sym];
      const label = sig === 1 ? "LONG" : sig === -1 ? "SHORT" : "FLAT";
      const cls = sig === 1 ? "pos" : sig === -1 ? "neg" : "";
      return `<div class="stat"><div class="v">${sym.replace("USDT", "")}: <span class="${cls}">${label}</span></div>
        <div class="l">${strat}<br>last ${price ? "$" + price.toLocaleString() : "—"}</div></div>`;
    }).join("") + `<div class="stat"><div class="v">${st.last_eval ? new Date(st.last_eval * 1000).toLocaleTimeString() : "…"}</div>
      <div class="l">last evaluation${st.last_error ? "<br><span class='neg'>" + st.last_error + "</span>" : ""}</div></div>`;

    const pos = Object.entries(st.positions);
    $("posBox").innerHTML = pos.length
      ? "<b>Open positions:</b> " + pos.map(([s, p]) =>
        `${s.replace("USDT", "")} ${p.side > 0 ? "LONG" : "SHORT"} ${p.qty} @ $${p.entry.toLocaleString()}`).join(" · ")
      : "<span style='color:var(--muted)'>No open positions.</span>";

    const orders = (await api("/api/orders")).orders;
    document.querySelector("#ordersTbl tbody").innerHTML = orders.map(o => `<tr>
      <td>${new Date(o.ts * 1000).toLocaleString()}</td><td>${o.symbol}</td>
      <td class="${o.side === "BUY" ? "pos" : "neg"}">${o.side}</td>
      <td>${o.qty}</td><td>${o.price ? "$" + o.price.toLocaleString() : ""}</td>
      <td>${o.mode}</td><td>${o.status}</td><td style="color:var(--muted)">${o.info}</td></tr>`).join("")
      || "<tr><td colspan=8 style='color:var(--muted)'>No orders yet — the bot evaluates at each hourly candle close.</td></tr>";
  } catch (e) {
    if (e.message.includes("not logged in")) { localStorage.removeItem("apt_token"); location.reload(); }
  }
}

async function showBot() {
  $("authPanel").classList.add("hidden");
  $("botPanel").classList.remove("hidden");
  fillSettings(await api("/api/settings"));
  refreshStatus();
  setInterval(refreshStatus, 15000);
}

if (token()) showBot();
