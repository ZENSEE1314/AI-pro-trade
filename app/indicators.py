"""Technical indicators implemented on pandas Series/DataFrames (no TA-lib dependency)."""

import numpy as np
import pandas as pd


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length).mean()


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / length, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / length, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(series, fast) - ema(series, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def bollinger(series: pd.Series, length: int = 20, mult: float = 2.0):
    mid = sma(series, length)
    sd = series.rolling(length).std()
    return mid + mult * sd, mid, mid - mult * sd


def donchian(df: pd.DataFrame, length: int = 20):
    upper = df["high"].rolling(length).max()
    lower = df["low"].rolling(length).min()
    return upper, (upper + lower) / 2, lower


def stochastic(df: pd.DataFrame, k: int = 14, d: int = 3):
    low_min = df["low"].rolling(k).min()
    high_max = df["high"].rolling(k).max()
    pct_k = 100 * (df["close"] - low_min) / (high_max - low_min)
    return pct_k, pct_k.rolling(d).mean()


def williams_r(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high_max = df["high"].rolling(length).max()
    low_min = df["low"].rolling(length).min()
    return -100 * (high_max - df["close"]) / (high_max - low_min)


def cci(df: pd.DataFrame, length: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    ma = tp.rolling(length).mean()
    md = (tp - ma).abs().rolling(length).mean()
    return (tp - ma) / (0.015 * md)


def adx(df: pd.DataFrame, length: int = 14):
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = atr(df, length)
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / length, adjust=False).mean() / tr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / length, adjust=False).mean() / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1 / length, adjust=False).mean(), plus_di, minus_di


def supertrend(df: pd.DataFrame, length: int = 10, mult: float = 3.0) -> pd.Series:
    """Returns direction series: 1 = uptrend, -1 = downtrend."""
    hl2 = (df["high"] + df["low"]) / 2
    a = atr(df, length)
    upper = (hl2 + mult * a).to_numpy()
    lower = (hl2 - mult * a).to_numpy()
    close = df["close"].to_numpy()
    n = len(df)
    direction = np.ones(n)
    final_upper = upper.copy()
    final_lower = lower.copy()
    for i in range(1, n):
        final_upper[i] = min(upper[i], final_upper[i - 1]) if close[i - 1] <= final_upper[i - 1] else upper[i]
        final_lower[i] = max(lower[i], final_lower[i - 1]) if close[i - 1] >= final_lower[i - 1] else lower[i]
        if close[i] > final_upper[i]:
            direction[i] = 1
        elif close[i] < final_lower[i]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
    return pd.Series(direction, index=df.index)


def psar(df: pd.DataFrame, af_step: float = 0.02, af_max: float = 0.2) -> pd.Series:
    """Returns direction series: 1 = SAR below price (up), -1 = SAR above (down)."""
    high, low = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    direction = np.ones(n)
    sar = low[0]
    ep = high[0]
    af = af_step
    up = True
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if up:
            if low[i] < sar:
                up, sar, ep, af = False, ep, low[i], af_step
            elif high[i] > ep:
                ep, af = high[i], min(af + af_step, af_max)
        else:
            if high[i] > sar:
                up, sar, ep, af = True, ep, high[i], af_step
            elif low[i] < ep:
                ep, af = low[i], min(af + af_step, af_max)
        direction[i] = 1 if up else -1
    return pd.Series(direction, index=df.index)


def ichimoku(df: pd.DataFrame, tenkan: int = 9, kijun: int = 26, senkou_b: int = 52):
    conv = (df["high"].rolling(tenkan).max() + df["low"].rolling(tenkan).min()) / 2
    base = (df["high"].rolling(kijun).max() + df["low"].rolling(kijun).min()) / 2
    span_a = ((conv + base) / 2).shift(kijun)
    span_b = ((df["high"].rolling(senkou_b).max() + df["low"].rolling(senkou_b).min()) / 2).shift(kijun)
    return conv, base, span_a, span_b


def rolling_vwap(df: pd.DataFrame, length: int = 24) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    pv = (tp * df["volume"]).rolling(length).sum()
    return pv / df["volume"].rolling(length).sum()


def zscore(series: pd.Series, length: int = 48) -> pd.Series:
    mean = series.rolling(length).mean()
    sd = series.rolling(length).std()
    return (series - mean) / sd


def roc(series: pd.Series, length: int = 12) -> pd.Series:
    return series.pct_change(length) * 100
