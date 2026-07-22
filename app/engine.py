"""Vectorized backtest engine.

Strategies produce a target position series in {-1, 0, +1} (short / flat / long).
The engine applies a one-bar execution delay, charges fees + slippage on every
position change, and computes portfolio metrics and per-trade statistics.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TAKER_FEE = 0.0006          # Bitunix futures taker fee per side
SLIPPAGE = 0.0002           # assumed slippage per side
HOURS_PER_YEAR = 24 * 365


@dataclass
class BacktestResult:
    strategy: str
    symbol: str
    metrics: dict = field(default_factory=dict)
    equity: pd.Series = None


def run_backtest(df: pd.DataFrame, position: pd.Series, strategy: str, symbol: str) -> BacktestResult:
    pos = position.reindex(df.index).fillna(0).clip(-1, 1)
    pos = pos.shift(1).fillna(0)                      # trade executes on next bar
    ret = df["close"].pct_change().fillna(0)

    turnover = pos.diff().abs().fillna(pos.abs())
    cost = turnover * (TAKER_FEE + SLIPPAGE)
    strat_ret = pos * ret - cost
    equity = (1 + strat_ret).cumprod()

    metrics = _compute_metrics(strat_ret, equity, pos, df)
    return BacktestResult(strategy=strategy, symbol=symbol, metrics=metrics, equity=equity)


def _compute_metrics(strat_ret: pd.Series, equity: pd.Series, pos: pd.Series, df: pd.DataFrame) -> dict:
    n_hours = len(strat_ret)
    years = n_hours / HOURS_PER_YEAR
    total_return = equity.iloc[-1] - 1
    cagr = (equity.iloc[-1]) ** (1 / years) - 1 if years > 0 and equity.iloc[-1] > 0 else -1.0

    ann_factor = np.sqrt(HOURS_PER_YEAR)
    vol = strat_ret.std()
    sharpe = (strat_ret.mean() / vol * ann_factor) if vol > 0 else 0.0
    downside = strat_ret[strat_ret < 0].std()
    sortino = (strat_ret.mean() / downside * ann_factor) if downside and downside > 0 else 0.0

    peak = equity.cummax()
    drawdown = equity / peak - 1
    max_dd = drawdown.min()
    calmar = cagr / abs(max_dd) if max_dd < 0 else 0.0

    trades = _extract_trades(pos, df["close"])
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": round(float(sharpe), 2),
        "sortino": round(float(sortino), 2),
        "max_drawdown_pct": round(float(max_dd) * 100, 2),
        "calmar": round(float(calmar), 2),
        "num_trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 1) if trades else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0),
        "avg_trade_pct": round(100 * float(np.mean(trades)), 3) if trades else 0.0,
        "expectancy_pct": round(100 * float(np.mean(trades)), 3) if trades else 0.0,
        "exposure_pct": round(100 * float((pos != 0).mean()), 1),
        "years": round(years, 2),
    }


def _extract_trades(pos: pd.Series, close: pd.Series) -> list:
    """Split the position series into trades; return net return per trade (after costs)."""
    trades = []
    current = 0
    entry_price = None
    for price, p in zip(close.to_numpy(), pos.to_numpy()):
        if p != current:
            if current != 0 and entry_price:
                raw = (price / entry_price - 1) * current
                trades.append(raw - 2 * (TAKER_FEE + SLIPPAGE))
            entry_price = price if p != 0 else None
            current = p
    return trades
