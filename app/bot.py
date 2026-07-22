"""Live/paper trading loop: runs one strategy on fresh candles and mirrors the
target position on Bitunix futures.

Defaults to paper mode (no API keys). Position sizing is fixed-fraction with an
ATR stop; leverage is intentionally NOT amplified beyond 1x notional by default.

Usage:
    python -m app.bot --symbol BTCUSDT --strategy "Supertrend (10, 3)" --risk 0.01
"""

import argparse
import time

from .bitunix import BitunixClient
from .data import load_klines
from .engine import TAKER_FEE
from .indicators import atr
from .strategies import REGISTRY

POLL_SECONDS = 60
ATR_STOP_MULT = 2.0
ATR_TP_MULT = 3.0


def run(symbol: str, strategy_name: str, risk_fraction: float, equity_usdt: float):
    meta = REGISTRY[strategy_name]
    client = BitunixClient()
    mode = "PAPER" if client.paper_mode else "LIVE"
    print(f"[{mode}] {strategy_name} on {symbol}, risk {risk_fraction:.1%}/trade")

    current_position = 0
    while True:
        df = load_klines(symbol, refresh=True)
        target = int(meta["fn"](df).iloc[-1])
        price = float(df["close"].iloc[-1])
        bar_atr = float(atr(df).iloc[-1])

        if target != current_position:
            if current_position != 0:
                side = "SELL" if current_position > 0 else "BUY"
                qty = round(equity_usdt * risk_fraction * ATR_STOP_MULT / bar_atr, 4)
                print(f"close {current_position:+d} via {side} {qty} @ ~{price}")
                client.place_order(symbol, side, qty, reduce_only=True)
            if target != 0:
                side = "BUY" if target > 0 else "SELL"
                stop = price - target * ATR_STOP_MULT * bar_atr
                take = price + target * ATR_TP_MULT * bar_atr
                qty = round(equity_usdt * risk_fraction / (ATR_STOP_MULT * bar_atr), 4)
                print(f"open {target:+d}: {side} {qty} @ ~{price} SL {stop:.2f} TP {take:.2f} "
                      f"(fee/side {TAKER_FEE:.2%})")
                client.place_order(symbol, side, qty, stop_loss=stop, take_profit=take)
            current_position = target
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--strategy", default="Supertrend (10, 3)")
    parser.add_argument("--risk", type=float, default=0.01)
    parser.add_argument("--equity", type=float, default=1000.0)
    args = parser.parse_args()
    run(args.symbol, args.strategy, args.risk, args.equity)
