"""Auto-trading engine.

Each token trades its best backtested strategy (highest Sharpe with >= MIN_TRADES
trades and drawdown above MAX_DD_FLOOR, benchmarks excluded), re-selected from
results/results.json at startup.

Every user with active=1 mirrors the strategy signal:
  live=0 -> paper orders (logged only)
  live=1 -> real market orders on Bitunix with the user's API keys

The loop re-evaluates signals once per hourly candle close.
"""

import asyncio
import json
import time
import traceback
from pathlib import Path

from . import db
from .bitunix import BitunixClient
from .data import load_klines
from .strategies import REGISTRY

RESULTS_PATH = Path(__file__).resolve().parent.parent / "results" / "results.json"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
MIN_TRADES = 20
MAX_DD_FLOOR = -65.0
QTY_DECIMALS = {"BTCUSDT": 4, "ETHUSDT": 3, "SOLUSDT": 1}
LOOP_SECONDS = 60

state = {
    "best": {},          # symbol -> strategy name
    "signals": {},       # symbol -> -1/0/1
    "prices": {},        # symbol -> last close
    "last_eval": None,
    "last_error": None,
}


def select_best_strategies() -> dict:
    data = json.loads(RESULTS_PATH.read_text())
    best = {}
    for symbol in SYMBOLS:
        rows = [r for r in data["results"]
                if r["symbol"] == symbol and r["category"] != "Benchmark"
                and r["num_trades"] >= MIN_TRADES and r["max_drawdown_pct"] > MAX_DD_FLOOR]
        rows.sort(key=lambda r: r["sharpe"], reverse=True)
        if rows:
            best[symbol] = rows[0]["strategy"]
    return best


async def engine():
    db.init()
    state["best"] = select_best_strategies()
    current_hour = None
    while True:
        try:
            hour = int(time.time() // 3600)
            if hour != current_hour:
                await asyncio.to_thread(evaluate_and_trade)
                current_hour = hour
                state["last_eval"] = int(time.time())
                state["last_error"] = None
        except Exception as exc:  # noqa: BLE001 - engine must survive
            state["last_error"] = str(exc)[:300]
            traceback.print_exc()
        await asyncio.sleep(LOOP_SECONDS)


def evaluate_and_trade():
    for symbol, strategy_name in state["best"].items():
        df = load_klines(symbol, refresh=True)
        signal = int(REGISTRY[strategy_name]["fn"](df).iloc[-1])
        price = float(df["close"].iloc[-1])
        state["signals"][symbol] = signal
        state["prices"][symbol] = price

    for settings in db.active_traders():
        try:
            _reconcile_user(settings)
        except Exception as exc:  # noqa: BLE001 - one user's failure shouldn't stop others
            db.log_order(settings["user_id"], "-", "-", 0, 0,
                         "live" if settings["live"] else "paper", "ERROR", str(exc))


def _reconcile_user(settings):
    user_id = settings["user_id"]
    is_live = bool(settings["live"]) and settings["api_key_enc"] and settings["api_secret_enc"]
    mode = "live" if is_live else "paper"
    client = None
    if is_live:
        client = BitunixClient(db.decrypt(settings["api_key_enc"]),
                               db.decrypt(settings["api_secret_enc"]))

    for symbol, target in state["signals"].items():
        price = state["prices"][symbol]
        pos = db.get_position(user_id, symbol)
        current = pos["side"] if pos else 0
        if target == current:
            continue

        if current != 0 and pos and pos["qty"] > 0:
            side = "SELL" if current > 0 else "BUY"
            _execute(client, user_id, symbol, side, pos["qty"], price, mode, reduce_only=True)

        qty = 0.0
        if target != 0:
            qty = round(settings["size_usdt"] / price, QTY_DECIMALS[symbol])
            if qty > 0:
                side = "BUY" if target > 0 else "SELL"
                _execute(client, user_id, symbol, side, qty, price, mode, reduce_only=False)
            else:
                target = 0
        db.set_position(user_id, symbol, target, qty, price if target != 0 else 0)


def _execute(client, user_id, symbol, side, qty, price, mode, reduce_only):
    if mode == "live":
        try:
            resp = client.place_order(symbol, side, qty, reduce_only=reduce_only)
            db.log_order(user_id, symbol, side, qty, price, mode, "SENT", json.dumps(resp)[:300])
        except Exception as exc:  # noqa: BLE001
            db.log_order(user_id, symbol, side, qty, price, mode, "FAILED", str(exc))
            raise
    else:
        db.log_order(user_id, symbol, side, qty, price, mode, "FILLED",
                     "paper " + ("close" if reduce_only else "open"))


def status() -> dict:
    return {
        "best_strategies": state["best"],
        "signals": state["signals"],
        "prices": state["prices"],
        "last_eval": state["last_eval"],
        "last_error": state["last_error"],
    }
