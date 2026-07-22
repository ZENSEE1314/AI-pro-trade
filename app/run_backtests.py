"""Run every registered strategy against BTC/ETH/SOL and write results JSON."""

import json
import sys
import traceback
from pathlib import Path

from .data import load_klines
from .engine import run_backtest
from .strategies import REGISTRY

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
EQUITY_POINTS = 500  # downsampled points per equity curve for the dashboard


def main():
    RESULTS_DIR.mkdir(exist_ok=True)
    all_results = []
    equity_curves = {}

    for symbol in SYMBOLS:
        print(f"Loading {symbol}...", flush=True)
        df = load_klines(symbol)
        print(f"  {len(df)} candles: {df.index[0]} -> {df.index[-1]}", flush=True)

        for name, meta in REGISTRY.items():
            try:
                position = meta["fn"](df)
                result = run_backtest(df, position, name, symbol)
            except Exception:
                print(f"  FAILED {name}", flush=True)
                traceback.print_exc()
                continue
            row = {"strategy": name, "category": meta["category"], "symbol": symbol}
            row.update(result.metrics)
            all_results.append(row)

            step = max(1, len(result.equity) // EQUITY_POINTS)
            sampled = result.equity.iloc[::step]
            equity_curves.setdefault(symbol, {})[name] = {
                "t": [ts.strftime("%Y-%m-%d %H:%M") for ts in sampled.index],
                "v": [round(float(v), 4) for v in sampled.to_numpy()],
            }
            print(f"  {name}: {result.metrics['total_return_pct']}% "
                  f"(sharpe {result.metrics['sharpe']})", flush=True)

    (RESULTS_DIR / "results.json").write_text(json.dumps({
        "symbols": SYMBOLS,
        "results": all_results,
    }, indent=1))
    for symbol, curves in equity_curves.items():
        (RESULTS_DIR / f"equity_{symbol}.json").write_text(json.dumps(curves))
    print(f"Wrote {len(all_results)} results to {RESULTS_DIR}")


if __name__ == "__main__":
    sys.exit(main())
