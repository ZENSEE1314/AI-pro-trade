"""FastAPI server: dashboard + results API + live liquidation feed + TV webhook."""

import asyncio
import json
import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import liquidations

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"
DASHBOARD_DIR = ROOT / "dashboard"
MAX_WEBHOOK_ALERTS = 500

app = FastAPI(title="AI Pro Trade")
tv_alerts: deque = deque(maxlen=MAX_WEBHOOK_ALERTS)


@app.on_event("startup")
async def start_collector():
    asyncio.create_task(liquidations.collector())


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


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(DASHBOARD_DIR / "index.html")


app.mount("/static", StaticFiles(directory=DASHBOARD_DIR), name="static")
