"""Fetch OHLCV klines from Binance public data mirror with local CSV cache."""

import time
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://data-api.binance.vision/api/v3/klines"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data_cache"
MAX_LIMIT = 1000
REQUEST_PAUSE_SEC = 0.25

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
]


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    rows = []
    cursor = start_ms
    while cursor < end_ms:
        resp = requests.get(BASE_URL, params={
            "symbol": symbol, "interval": interval,
            "startTime": cursor, "endTime": end_ms, "limit": MAX_LIMIT,
        }, timeout=30)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        rows.extend(batch)
        cursor = batch[-1][6] + 1
        if len(batch) < MAX_LIMIT:
            break
        time.sleep(REQUEST_PAUSE_SEC)

    df = pd.DataFrame(rows, columns=KLINE_COLUMNS)
    for col in ("open", "high", "low", "close", "volume", "quote_volume"):
        df[col] = df[col].astype(float)
    df["time"] = pd.to_datetime(df["open_time"], unit="ms")
    df = df[["time", "open", "high", "low", "close", "volume", "quote_volume"]]
    return df.drop_duplicates(subset="time").set_index("time")


def load_klines(symbol: str, interval: str = "1h",
                start: str = "2021-01-01", refresh: bool = False) -> pd.DataFrame:
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"{symbol}_{interval}.csv"
    end_ms = int(time.time() * 1000)

    if cache_file.exists():
        df = pd.read_csv(cache_file, parse_dates=["time"], index_col="time")
        if not refresh:
            return df
        # incremental update: refetch from the last cached candle onward
        last_ms = int(df.index[-1].timestamp() * 1000)
        fresh = fetch_klines(symbol, interval, last_ms, end_ms)
        df = pd.concat([df[df.index < fresh.index[0]], fresh]) if len(fresh) else df
    else:
        start_ms = int(pd.Timestamp(start).timestamp() * 1000)
        df = fetch_klines(symbol, interval, start_ms, end_ms)

    df.to_csv(cache_file)
    return df
