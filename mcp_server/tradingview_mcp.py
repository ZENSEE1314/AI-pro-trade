"""TradingView-linked MCP server.

Exposes market data + computed indicator tools to Claude (or any MCP client):
  - get_klines: OHLCV candles for any Binance symbol
  - get_indicators: full indicator snapshot (RSI, MACD, EMAs, BB, ATR, ADX, ...)
  - get_strategy_signals: current signal of every strategy in the library
  - get_tradingview_analysis: TradingView's own aggregated recommendation
    (via the public scanner endpoint used by tradingview-ta)

TradingView alert *webhooks* (from Pine scripts) are received by the FastAPI
server at POST /webhook/tradingview — note TV requires a paid plan to send them.

Run:  python -m mcp_server.tradingview_mcp          (stdio transport)
Register in .mcp.json (see repo root).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from mcp.server.fastmcp import FastMCP

from app import indicators as ta
from app.data import load_klines
from app.strategies import REGISTRY

server = FastMCP("tradingview-trade")

TV_SCANNER_URL = "https://scanner.tradingview.com/crypto/scan"


@server.tool()
def get_klines(symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 100) -> str:
    """Return recent OHLCV candles for a symbol (BTCUSDT, ETHUSDT, SOLUSDT, ...)."""
    df = load_klines(symbol, interval).tail(limit)
    return df.to_csv()


@server.tool()
def get_indicators(symbol: str = "BTCUSDT", interval: str = "1h") -> str:
    """Compute a full indicator snapshot for the latest candle."""
    df = load_klines(symbol, interval, refresh=True)
    close = df["close"]
    macd_line, macd_sig, macd_hist = ta.macd(close)
    bb_up, bb_mid, bb_low = ta.bollinger(close)
    adx_v, plus_di, minus_di = ta.adx(df)
    k, d = ta.stochastic(df)
    snap = {
        "symbol": symbol,
        "time": str(df.index[-1]),
        "close": float(close.iloc[-1]),
        "rsi_14": round(float(ta.rsi(close).iloc[-1]), 2),
        "macd": round(float(macd_line.iloc[-1]), 4),
        "macd_signal": round(float(macd_sig.iloc[-1]), 4),
        "macd_hist": round(float(macd_hist.iloc[-1]), 4),
        "ema_20": round(float(ta.ema(close, 20).iloc[-1]), 2),
        "ema_50": round(float(ta.ema(close, 50).iloc[-1]), 2),
        "ema_200": round(float(ta.ema(close, 200).iloc[-1]), 2),
        "bb_upper": round(float(bb_up.iloc[-1]), 2),
        "bb_lower": round(float(bb_low.iloc[-1]), 2),
        "atr_14": round(float(ta.atr(df).iloc[-1]), 2),
        "adx_14": round(float(adx_v.iloc[-1]), 2),
        "plus_di": round(float(plus_di.iloc[-1]), 2),
        "minus_di": round(float(minus_di.iloc[-1]), 2),
        "stoch_k": round(float(k.iloc[-1]), 2),
        "stoch_d": round(float(d.iloc[-1]), 2),
        "supertrend_dir": int(ta.supertrend(df).iloc[-1]),
        "williams_r": round(float(ta.williams_r(df).iloc[-1]), 2),
        "cci_20": round(float(ta.cci(df).iloc[-1]), 2),
    }
    return json.dumps(snap, indent=1)


@server.tool()
def get_strategy_signals(symbol: str = "BTCUSDT") -> str:
    """Current position signal (-1 short / 0 flat / +1 long) from every strategy."""
    df = load_klines(symbol, refresh=True)
    signals = {}
    for name, meta in REGISTRY.items():
        try:
            signals[name] = int(meta["fn"](df).iloc[-1])
        except Exception as exc:  # noqa: BLE001
            signals[name] = f"error: {exc}"
    longs = sum(1 for v in signals.values() if v == 1)
    shorts = sum(1 for v in signals.values() if v == -1)
    return json.dumps({
        "symbol": symbol, "long_votes": longs, "short_votes": shorts,
        "consensus": "LONG" if longs > shorts else ("SHORT" if shorts > longs else "NEUTRAL"),
        "signals": signals,
    }, indent=1)


@server.tool()
def get_tradingview_analysis(symbol: str = "BTCUSDT", exchange: str = "BINANCE") -> str:
    """TradingView's aggregated Buy/Sell recommendation and oscillator/MA ratings."""
    payload = {
        "symbols": {"tickers": [f"{exchange}:{symbol}"], "query": {"types": []}},
        "columns": [
            "Recommend.All", "Recommend.MA", "Recommend.Other",
            "RSI", "MACD.macd", "MACD.signal", "ADX", "close", "volume",
        ],
    }
    resp = requests.post(TV_SCANNER_URL, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()["data"]
    if not data:
        return json.dumps({"error": f"no TradingView data for {exchange}:{symbol}"})
    values = dict(zip(payload["columns"], data[0]["d"]))
    rec = values["Recommend.All"]
    label = ("STRONG_BUY" if rec > 0.5 else "BUY" if rec > 0.1 else
             "STRONG_SELL" if rec < -0.5 else "SELL" if rec < -0.1 else "NEUTRAL")
    values["recommendation"] = label
    return json.dumps(values, indent=1)


if __name__ == "__main__":
    server.run()
