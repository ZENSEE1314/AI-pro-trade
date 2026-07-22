"""Strategy library. Each strategy maps an OHLCV DataFrame to a target position
series in {-1, 0, +1}. Signals use only current-and-past bars; the engine adds
the one-bar execution delay.

Subjective concepts (SMC, price action) are converted to explicit testable rules.
"""

import numpy as np
import pandas as pd

from . import indicators as ta

REGISTRY = {}


def strategy(name: str, category: str):
    def wrap(fn):
        REGISTRY[name] = {"fn": fn, "category": category}
        return fn
    return wrap


def _cross_state(fast: pd.Series, slow: pd.Series) -> pd.Series:
    return pd.Series(np.where(fast > slow, 1, -1), index=fast.index)


# ---------------- 1. Trend following ----------------

@strategy("SMA 50/200 Golden Cross", "Trend")
def sma_cross(df):
    return _cross_state(ta.sma(df["close"], 50), ta.sma(df["close"], 200))


@strategy("EMA 12/26 Crossover", "Trend")
def ema_cross(df):
    return _cross_state(ta.ema(df["close"], 12), ta.ema(df["close"], 26))


@strategy("EMA Ribbon (8>13>21>55)", "Trend")
def ema_ribbon(df):
    e8, e13, e21, e55 = (ta.ema(df["close"], n) for n in (8, 13, 21, 55))
    long = (e8 > e13) & (e13 > e21) & (e21 > e55)
    short = (e8 < e13) & (e13 < e21) & (e21 < e55)
    return pd.Series(np.where(long, 1, np.where(short, -1, 0)), index=df.index)


@strategy("MACD Trend", "Trend")
def macd_trend(df):
    line, sig, _ = ta.macd(df["close"])
    return _cross_state(line, sig)


@strategy("ADX Trend Filter + DI Cross", "Trend")
def adx_di(df):
    adx_v, plus, minus = ta.adx(df)
    raw = np.where(plus > minus, 1, -1)
    return pd.Series(np.where(adx_v > 25, raw, 0), index=df.index)


@strategy("Supertrend (10, 3)", "Trend")
def supertrend_strat(df):
    return ta.supertrend(df, 10, 3.0)


@strategy("Ichimoku Cloud", "Trend")
def ichimoku_strat(df):
    conv, base, span_a, span_b = ta.ichimoku(df)
    above = (df["close"] > span_a) & (df["close"] > span_b) & (conv > base)
    below = (df["close"] < span_a) & (df["close"] < span_b) & (conv < base)
    return pd.Series(np.where(above, 1, np.where(below, -1, 0)), index=df.index)


@strategy("Parabolic SAR", "Trend")
def psar_strat(df):
    return ta.psar(df)


@strategy("Pullback to EMA50 in Uptrend", "Trend")
def pullback_ema(df):
    e50, e200 = ta.ema(df["close"], 50), ta.ema(df["close"], 200)
    uptrend = e50 > e200
    entry = uptrend & (df["low"] <= e50) & (df["close"] > e50)
    exit_ = ~uptrend | (df["close"] < e200)
    pos = pd.Series(np.where(entry, 1, np.where(exit_, 0, np.nan)), index=df.index)
    return pos.ffill().fillna(0)


@strategy("Turtle (Donchian 20/10)", "Trend")
def turtle(df):
    up20, _, low20 = ta.donchian(df, 20)
    up10, _, low10 = ta.donchian(df, 10)
    close = df["close"]
    pos = np.zeros(len(df))
    state = 0
    u20, l20 = up20.shift(1).to_numpy(), low20.shift(1).to_numpy()
    u10, l10 = up10.shift(1).to_numpy(), low10.shift(1).to_numpy()
    c = close.to_numpy()
    for i in range(len(df)):
        if state == 0:
            if c[i] > u20[i]:
                state = 1
            elif c[i] < l20[i]:
                state = -1
        elif state == 1 and c[i] < l10[i]:
            state = 0
        elif state == -1 and c[i] > u10[i]:
            state = 0
        pos[i] = state
    return pd.Series(pos, index=df.index)


@strategy("Time-Series Momentum (30d)", "Trend")
def tsmom(df):
    lookback = 24 * 30
    return pd.Series(np.where(df["close"] > df["close"].shift(lookback), 1, -1), index=df.index)


@strategy("Multi-Timeframe Trend (1h+4h+1d)", "Trend")
def mtf_trend(df):
    e1h = ta.ema(df["close"], 50)
    e4h = ta.ema(df["close"], 200)
    e1d = ta.ema(df["close"], 600)
    long = (df["close"] > e1h) & (df["close"] > e4h) & (df["close"] > e1d)
    short = (df["close"] < e1h) & (df["close"] < e4h) & (df["close"] < e1d)
    return pd.Series(np.where(long, 1, np.where(short, -1, 0)), index=df.index)


# ---------------- 2. Breakout ----------------

@strategy("Donchian 55 Breakout", "Breakout")
def donchian_breakout(df):
    up, mid, low = ta.donchian(df, 55)
    close = df["close"]
    sig = pd.Series(np.nan, index=df.index)
    sig[close > up.shift(1)] = 1
    sig[close < low.shift(1)] = -1
    sig[(close < mid) & (close.shift(1) >= mid)] = 0
    return sig.ffill().fillna(0)


@strategy("Bollinger Squeeze Breakout", "Breakout")
def bb_squeeze(df):
    upper, mid, lower = ta.bollinger(df["close"], 20, 2)
    width = (upper - lower) / mid
    squeeze = width < width.rolling(120).quantile(0.2)
    long = squeeze.shift(1) & (df["close"] > upper)
    short = squeeze.shift(1) & (df["close"] < lower)
    exit_ = (df["close"] < mid) & (df["close"].shift(1) >= mid) | (df["close"] > mid) & (df["close"].shift(1) <= mid)
    pos = pd.Series(np.where(long, 1, np.where(short, -1, np.where(exit_, 0, np.nan))), index=df.index)
    return pos.ffill().fillna(0)


@strategy("Prev-Day High/Low Breakout", "Breakout")
def prev_day_breakout(df):
    day_high = df["high"].rolling(24).max().shift(1)
    day_low = df["low"].rolling(24).min().shift(1)
    long = df["close"] > day_high
    short = df["close"] < day_low
    return pd.Series(np.where(long, 1, np.where(short, -1, 0)), index=df.index)


@strategy("Volume-Confirmed Breakout", "Breakout")
def volume_breakout(df):
    up, _, low = ta.donchian(df, 48)
    vol_ok = df["volume"] > 1.5 * df["volume"].rolling(48).mean()
    long = (df["close"] > up.shift(1)) & vol_ok
    short = (df["close"] < low.shift(1)) & vol_ok
    e21 = ta.ema(df["close"], 21)
    exit_long = df["close"] < e21
    exit_short = df["close"] > e21
    pos = pd.Series(np.nan, index=df.index)
    pos[long] = 1
    pos[short] = -1
    pos = pos.ffill().fillna(0)
    pos[(pos == 1) & exit_long] = 0
    pos[(pos == -1) & exit_short] = 0
    return pos


@strategy("ATH Breakout", "Breakout")
def ath_breakout(df):
    ath = df["close"].cummax().shift(1)
    long = df["close"] >= ath
    exit_ = df["close"] < ta.ema(df["close"], 100)
    pos = pd.Series(np.where(long, 1, np.where(exit_, 0, np.nan)), index=df.index)
    return pos.ffill().fillna(0)


@strategy("Failed Breakout Reversal", "Breakout")
def failed_breakout(df):
    up, _, low = ta.donchian(df, 48)
    poked_high = df["high"] > up.shift(1)
    closed_back = df["close"] < up.shift(1)
    short = poked_high & closed_back
    poked_low = df["low"] < low.shift(1)
    closed_up = df["close"] > low.shift(1)
    long = poked_low & closed_up
    pos = pd.Series(np.where(long, 1, np.where(short, -1, np.nan)), index=df.index)
    return pos.ffill(limit=24).fillna(0)


# ---------------- 3. Mean reversion ----------------

@strategy("RSI(2) Mean Reversion", "Mean Reversion")
def rsi2_mr(df):
    r = ta.rsi(df["close"], 2)
    e200 = ta.ema(df["close"], 200)
    long = (r < 10) & (df["close"] > e200)
    exit_ = r > 60
    pos = pd.Series(np.where(long, 1, np.where(exit_, 0, np.nan)), index=df.index)
    return pos.ffill().fillna(0)


@strategy("RSI 30/70 Reversal", "Mean Reversion")
def rsi_3070(df):
    r = ta.rsi(df["close"], 14)
    pos = pd.Series(np.nan, index=df.index)
    pos[r < 30] = 1
    pos[r > 70] = -1
    pos[(r > 45) & (r < 55)] = 0
    return pos.ffill().fillna(0)


@strategy("Bollinger Band Reversion", "Mean Reversion")
def bb_mr(df):
    upper, mid, lower = ta.bollinger(df["close"], 20, 2)
    long = df["close"] < lower
    short = df["close"] > upper
    exit_ = ((df["close"] >= mid) & (df["close"].shift(1) < mid)) | ((df["close"] <= mid) & (df["close"].shift(1) > mid))
    pos = pd.Series(np.where(long, 1, np.where(short, -1, np.where(exit_, 0, np.nan))), index=df.index)
    return pos.ffill().fillna(0)


@strategy("Z-Score Reversion", "Mean Reversion")
def zscore_mr(df):
    z = ta.zscore(df["close"], 48)
    pos = pd.Series(np.nan, index=df.index)
    pos[z < -2] = 1
    pos[z > 2] = -1
    pos[z.abs() < 0.3] = 0
    return pos.ffill().fillna(0)


@strategy("VWAP Reversion (24h)", "Mean Reversion")
def vwap_mr(df):
    vwap = ta.rolling_vwap(df, 24)
    dev = (df["close"] - vwap) / vwap
    pos = pd.Series(np.nan, index=df.index)
    pos[dev < -0.02] = 1
    pos[dev > 0.02] = -1
    pos[dev.abs() < 0.003] = 0
    return pos.ffill().fillna(0)


@strategy("Stochastic Reversal", "Mean Reversion")
def stoch_rev(df):
    k, d = ta.stochastic(df)
    long = (k < 20) & (k > d)
    short = (k > 80) & (k < d)
    exit_ = (k > 45) & (k < 55)
    pos = pd.Series(np.where(long, 1, np.where(short, -1, np.where(exit_, 0, np.nan))), index=df.index)
    return pos.ffill().fillna(0)


@strategy("CCI Reversal", "Mean Reversion")
def cci_rev(df):
    c = ta.cci(df)
    pos = pd.Series(np.nan, index=df.index)
    pos[c < -150] = 1
    pos[c > 150] = -1
    pos[c.abs() < 30] = 0
    return pos.ffill().fillna(0)


@strategy("Williams %R Reversal", "Mean Reversion")
def willr_rev(df):
    w = ta.williams_r(df)
    pos = pd.Series(np.nan, index=df.index)
    pos[w < -90] = 1
    pos[w > -10] = -1
    pos[(w > -60) & (w < -40)] = 0
    return pos.ffill().fillna(0)


# ---------------- 4. Momentum ----------------

@strategy("ROC Momentum (7d)", "Momentum")
def roc_mom(df):
    r = ta.roc(df["close"], 24 * 7)
    return pd.Series(np.where(r > 3, 1, np.where(r < -3, -1, 0)), index=df.index)


@strategy("RSI Momentum (>55/<45)", "Momentum")
def rsi_mom(df):
    r = ta.rsi(df["close"], 14)
    pos = pd.Series(np.nan, index=df.index)
    pos[r > 55] = 1
    pos[r < 45] = -1
    return pos.ffill().fillna(0)


@strategy("52-Week High Proximity", "Momentum")
def week52_high(df):
    high52 = df["close"].rolling(24 * 365, min_periods=24 * 90).max()
    prox = df["close"] / high52
    long = prox > 0.95
    exit_ = prox < 0.85
    pos = pd.Series(np.where(long, 1, np.where(exit_, 0, np.nan)), index=df.index)
    return pos.ffill().fillna(0)


# ---------------- 5. Price action ----------------

@strategy("Engulfing Candle", "Price Action")
def engulfing(df):
    o, c = df["open"], df["close"]
    prev_o, prev_c = o.shift(1), c.shift(1)
    bull = (prev_c < prev_o) & (c > o) & (c > prev_o) & (o < prev_c)
    bear = (prev_c > prev_o) & (c < o) & (c < prev_o) & (o > prev_c)
    trend = ta.ema(c, 100)
    long = bull & (c > trend)
    short = bear & (c < trend)
    pos = pd.Series(np.where(long, 1, np.where(short, -1, np.nan)), index=df.index)
    return pos.ffill(limit=12).fillna(0)


@strategy("Inside Bar Breakout", "Price Action")
def inside_bar(df):
    inside = (df["high"] < df["high"].shift(1)) & (df["low"] > df["low"].shift(1))
    mother_high = df["high"].shift(1)
    mother_low = df["low"].shift(1)
    long = inside.shift(1) & (df["close"] > mother_high.shift(1))
    short = inside.shift(1) & (df["close"] < mother_low.shift(1))
    pos = pd.Series(np.where(long, 1, np.where(short, -1, np.nan)), index=df.index)
    return pos.ffill(limit=12).fillna(0)


@strategy("Pin Bar Reversal", "Price Action")
def pin_bar(df):
    body = (df["close"] - df["open"]).abs()
    rng = df["high"] - df["low"]
    lower_wick = df[["open", "close"]].min(axis=1) - df["low"]
    upper_wick = df["high"] - df[["open", "close"]].max(axis=1)
    bull_pin = (lower_wick > 2 * body) & (lower_wick > 0.6 * rng)
    bear_pin = (upper_wick > 2 * body) & (upper_wick > 0.6 * rng)
    e100 = ta.ema(df["close"], 100)
    long = bull_pin & (df["close"] < e100)
    short = bear_pin & (df["close"] > e100)
    pos = pd.Series(np.where(long, 1, np.where(short, -1, np.nan)), index=df.index)
    return pos.ffill(limit=12).fillna(0)


# ---------------- 6. Smart money / liquidity (rule-converted) ----------------

@strategy("Liquidity Sweep Reversal", "Smart Money")
def liquidity_sweep(df):
    swing_low = df["low"].rolling(48).min().shift(1)
    swing_high = df["high"].rolling(48).max().shift(1)
    swept_low = (df["low"] < swing_low) & (df["close"] > swing_low)
    swept_high = (df["high"] > swing_high) & (df["close"] < swing_high)
    pos = pd.Series(np.where(swept_low, 1, np.where(swept_high, -1, np.nan)), index=df.index)
    return pos.ffill(limit=24).fillna(0)


@strategy("Fair Value Gap Fill", "Smart Money")
def fvg_fill(df):
    bull_gap = df["low"] > df["high"].shift(2)
    bear_gap = df["high"] < df["low"].shift(2)
    gap_mid_bull = (df["high"].shift(2) + df["low"]) / 2
    gap_mid_bear = (df["low"].shift(2) + df["high"]) / 2
    long_zone = bull_gap.shift(1).rolling(24).max().astype(bool) & (df["close"] <= gap_mid_bull.ffill())
    short_zone = bear_gap.shift(1).rolling(24).max().astype(bool) & (df["close"] >= gap_mid_bear.ffill())
    e100 = ta.ema(df["close"], 100)
    long = long_zone & (df["close"] > e100)
    short = short_zone & (df["close"] < e100)
    pos = pd.Series(np.where(long, 1, np.where(short, -1, np.nan)), index=df.index)
    return pos.ffill(limit=24).fillna(0)


# ---------------- 7. Crypto-specific & benchmarks ----------------

@strategy("Grid Proxy (BB position sizing)", "Crypto")
def grid_proxy(df):
    upper, mid, lower = ta.bollinger(df["close"], 48, 2)
    band_pos = (df["close"] - lower) / (upper - lower)
    pos = pd.Series(np.where(band_pos < 0.3, 1, np.where(band_pos > 0.7, -1, 0)), index=df.index)
    return pos


@strategy("Buy & Hold", "Benchmark")
def buy_hold(df):
    return pd.Series(1.0, index=df.index)
