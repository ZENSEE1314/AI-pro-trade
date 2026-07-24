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
PAPER_WALLET_USDT = 1000.0
PAPER_LEVERAGE = 10          # assumed leverage for paper-mode notional
MIN_ORDER_USDT = 5.0         # minimum notional Bitunix will accept

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
    live_map = {}
    if is_live:
        client = BitunixClient(db.decrypt(settings["api_key_enc"]),
                               db.decrypt(settings["api_secret_enc"]))
        live_map = client.get_open_positions_map()
        _sync_db_from_exchange(user_id, live_map)

    margin_usdt = _position_margin_usdt(settings, client, user_id)

    for symbol, target in state["signals"].items():
        price = state["prices"][symbol]
        pos = db.get_position(user_id, symbol)
        current = pos["side"] if pos else 0
        if target == current:
            continue

        if current != 0 and pos and pos["qty"] > 0:
            _close(client, user_id, symbol, current, pos["qty"], price, mode, live_map)

        qty = 0.0
        if target != 0 and margin_usdt > 0:
            # margin is what the user commits; notional = margin x leverage
            leverage = PAPER_LEVERAGE if client is None else client.get_leverage(symbol)
            if not leverage:
                db.log_order(user_id, symbol, "-", 0, price, mode, "SKIPPED",
                             "could not read leverage for symbol")
                target = 0
            else:
                notional = margin_usdt * leverage
                qty = round(notional / price, QTY_DECIMALS[symbol])
                if notional >= MIN_ORDER_USDT and qty > 0:
                    side = "BUY" if target > 0 else "SELL"
                    _open(client, user_id, symbol, side, qty, price, mode,
                          note=f"margin {margin_usdt:.2f} x {leverage}x = {notional:.2f} notional")
                else:
                    db.log_order(user_id, symbol, "-", 0, price, mode, "SKIPPED",
                                 f"notional {notional:.2f} below minimum {MIN_ORDER_USDT}")
                    target = 0
        elif target != 0:
            db.log_order(user_id, symbol, "-", 0, price, mode, "SKIPPED",
                         "margin size is zero (check wallet balance)")
            target = 0
        db.set_position(user_id, symbol, target, qty, price if target != 0 else 0)


def _sync_db_from_exchange(user_id: int, live_map: dict):
    """Exchange is source of truth for live positions: adopt orphans opened outside
    the DB's knowledge, and drop positions closed externally, so the bot never
    double-opens or abandons a live position."""
    for symbol in SYMBOLS:
        lp = live_map.get(symbol)
        db_pos = db.get_position(user_id, symbol)
        if lp:
            entry = lp["entry"] or (db_pos["entry_price"] if db_pos else 0)
            db.set_position(user_id, symbol, lp["side"], lp["qty"], entry)
        elif db_pos and db_pos["side"] != 0:
            db.set_position(user_id, symbol, 0, 0, 0)


def _position_margin_usdt(settings, client, user_id) -> float:
    """USDT margin committed per token: a fixed amount, or size_pct% of total wallet
    equity (live: real Bitunix account). Notional = this x leverage."""
    if settings["size_mode"] != "percent":
        return float(settings["size_usdt"])
    pct = float(settings["size_pct"]) / 100.0
    if client is None:
        return PAPER_WALLET_USDT * pct
    equity = _wallet_equity(client)
    if equity is None:
        db.log_order(user_id, "-", "-", 0, 0, "live", "ERROR",
                     "could not read wallet balance; skipping this cycle")
        return 0.0
    return equity * pct


def _wallet_equity(client) -> float | None:
    """Total account equity in USDT (available + locked margin + unrealized PnL)."""
    try:
        resp = client.get_account()
    except Exception:  # noqa: BLE001
        return None
    node = resp.get("data", resp)
    if isinstance(node, list):
        node = node[0] if node else {}
    if not isinstance(node, dict) or node.get("available") is None:
        return None

    def num(key: str) -> float:
        try:
            return float(node.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0

    return (num("available") + num("frozen") + num("margin")
            + num("crossUnrealizedPNL") + num("isolationUnrealizedPNL"))


def _ok(resp) -> bool:
    """Bitunix returns code == 0 on success (HTTP is 200 even on rejection)."""
    return isinstance(resp, dict) and str(resp.get("code", "0")) == "0"


def _open(client, user_id, symbol, side, qty, price, mode, note=""):
    if mode != "live":
        db.log_order(user_id, symbol, side, qty, price, mode, "FILLED", "paper open " + note)
        return
    try:
        resp = client.place_order(symbol, side, qty)      # tradeSide=OPEN, MARKET
    except Exception as exc:  # noqa: BLE001
        db.log_order(user_id, symbol, side, qty, price, mode, "FAILED", str(exc))
        raise
    if _ok(resp):
        db.log_order(user_id, symbol, side, qty, price, mode, "SENT", (note + " " + json.dumps(resp))[:300])
    else:
        db.log_order(user_id, symbol, side, qty, price, mode, "FAILED", json.dumps(resp)[:300])
        raise RuntimeError(f"open rejected: {resp.get('msg')}")


def _close(client, user_id, symbol, current, qty, price, mode, live_map):
    """Close via Bitunix flash_close_position (needs the live positionId)."""
    if mode != "live":
        db.log_order(user_id, symbol, "SELL" if current > 0 else "BUY", qty, price,
                     mode, "FILLED", "paper close")
        return
    lp = live_map.get(symbol)
    if not lp or not lp.get("position_id"):
        db.log_order(user_id, symbol, "CLOSE", qty, price, mode, "SKIPPED",
                     "no live position found to close")
        return
    try:
        resp = client.flash_close_position(lp["position_id"])
    except Exception as exc:  # noqa: BLE001
        db.log_order(user_id, symbol, "CLOSE", qty, price, mode, "FAILED", str(exc))
        raise
    if _ok(resp):
        db.log_order(user_id, symbol, "CLOSE", qty, price, mode, "SENT", json.dumps(resp)[:300])
    else:
        db.log_order(user_id, symbol, "CLOSE", qty, price, mode, "FAILED", json.dumps(resp)[:300])
        raise RuntimeError(f"close rejected: {resp.get('msg')}")


def status() -> dict:
    return {
        "best_strategies": state["best"],
        "signals": state["signals"],
        "prices": state["prices"],
        "last_eval": state["last_eval"],
        "last_error": state["last_error"],
    }
