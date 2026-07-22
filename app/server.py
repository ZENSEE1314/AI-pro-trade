"""FastAPI server: dashboard, results API, liquidation feed, TV webhook,
user auth, and the per-token auto-trading engine."""

import asyncio
import json
import time
from collections import deque
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, db, liquidations, trader

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"
DASHBOARD_DIR = ROOT / "dashboard"
MAX_WEBHOOK_ALERTS = 500

app = FastAPI(title="AI Pro Trade")
tv_alerts: deque = deque(maxlen=MAX_WEBHOOK_ALERTS)


@app.on_event("startup")
async def startup():
    db.init()
    asyncio.create_task(liquidations.collector())
    asyncio.create_task(trader.engine())


# ---------- results / market data ----------

@app.get("/api/results")
def get_results():
    path = RESULTS_DIR / "results.json"
    if not path.exists():
        return JSONResponse({"error": "no results yet - run python -m app.run_backtests"}, status_code=404)
    return json.loads(path.read_text())


@app.get("/api/equity/{symbol}")
def get_equity(symbol: str):
    path = RESULTS_DIR / f"equity_{symbol}.json"
    if not path.exists():
        return JSONResponse({"error": f"no equity data for {symbol}"}, status_code=404)
    return json.loads(path.read_text())


@app.get("/api/liquidations")
def get_liquidations(limit: int = 200):
    return liquidations.snapshot(limit)


# ---------- auth ----------

class Credentials(BaseModel):
    email: str
    password: str


@app.post("/api/register")
def api_register(creds: Credentials):
    auth.register(creds.email, creds.password)
    return {"token": auth.login(creds.email, creds.password)}


@app.post("/api/login")
def api_login(creds: Credentials):
    return {"token": auth.login(creds.email, creds.password)}


# ---------- user settings / bot ----------

class SettingsIn(BaseModel):
    api_key: str | None = None
    api_secret: str | None = None
    size_usdt: float | None = None
    live: bool | None = None
    active: bool | None = None


@app.get("/api/settings")
def get_settings(user_id: int = Depends(auth.current_user)):
    s = db.get_settings(user_id)
    return {
        "has_keys": bool(s["api_key_enc"] and s["api_secret_enc"]),
        "api_key_masked": ("****" + db.decrypt(s["api_key_enc"])[-4:]) if s["api_key_enc"] else "",
        "size_usdt": s["size_usdt"],
        "live": bool(s["live"]),
        "active": bool(s["active"]),
    }


@app.post("/api/settings")
def post_settings(body: SettingsIn, user_id: int = Depends(auth.current_user)):
    fields = {}
    if body.api_key is not None and body.api_key.strip():
        fields["api_key_enc"] = db.encrypt(body.api_key.strip())
    if body.api_secret is not None and body.api_secret.strip():
        fields["api_secret_enc"] = db.encrypt(body.api_secret.strip())
    if body.size_usdt is not None:
        fields["size_usdt"] = max(10.0, float(body.size_usdt))
    if body.live is not None:
        fields["live"] = int(body.live)
    if body.active is not None:
        fields["active"] = int(body.active)
    if fields:
        db.update_settings(user_id, **fields)
    return get_settings(user_id)


@app.get("/api/bot/status")
def bot_status(user_id: int = Depends(auth.current_user)):
    positions = {}
    for symbol in trader.SYMBOLS:
        pos = db.get_position(user_id, symbol)
        if pos and pos["side"] != 0:
            positions[symbol] = {"side": pos["side"], "qty": pos["qty"], "entry": pos["entry_price"]}
    return {**trader.status(), "positions": positions}


@app.get("/api/orders")
def get_orders(user_id: int = Depends(auth.current_user)):
    return {"orders": [dict(r) for r in db.recent_orders(user_id)]}


# ---------- tradingview webhook ----------

@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request):
    """Receives TradingView alert webhooks (requires a paid TV plan to send)."""
    try:
        payload = await request.json()
    except Exception:
        payload = {"raw": (await request.body()).decode(errors="replace")}
    payload["received_at"] = int(time.time())
    tv_alerts.append(payload)
    return {"ok": True}


@app.get("/api/tv-alerts")
def get_tv_alerts():
    return {"alerts": list(tv_alerts)[::-1]}


# ---------- pages ----------

@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(DASHBOARD_DIR / "index.html")


@app.get("/account")
def account_page():
    return FileResponse(DASHBOARD_DIR / "account.html")


app.mount("/static", StaticFiles(directory=DASHBOARD_DIR), name="static")
