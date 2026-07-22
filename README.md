# AI Pro Trade

Futures trading research stack for **Bitunix**: 36 rule-based strategies backtested on
BTC / ETH / SOL, a live liquidation feed, a TradingView MCP server, a paper/live
trading bot, and a results dashboard.

## What's inside

| Piece | File | What it does |
|---|---|---|
| Data | `app/data.py` | 1h OHLCV from Binance public data mirror (`data-api.binance.vision`), CSV-cached |
| Indicators | `app/indicators.py` | RSI, MACD, EMA/SMA, BB, ATR, ADX, Supertrend, PSAR, Ichimoku, Donchian, Stoch, CCI, W%R, VWAP, z-score |
| Strategies | `app/strategies.py` | 36 strategies: trend, breakout, mean-reversion, momentum, price-action, smart-money (rule-converted), benchmarks |
| Backtester | `app/engine.py` | Vectorized, 1-bar execution delay, 0.06% taker fee + 0.02% slippage per side, full metrics |
| Runner | `app/run_backtests.py` | All strategies × BTC/ETH/SOL → `results/*.json` |
| Liquidations | `app/liquidations.py` | Binance futures `!forceOrder` websocket collector |
| Bitunix | `app/bitunix.py` | Signed REST client (double-SHA256 auth); paper mode without keys |
| Bot | `app/bot.py` | Live/paper loop: strategy signal → Bitunix order with ATR SL/TP |
| MCP | `mcp_server/tradingview_mcp.py` | MCP tools: klines, indicator snapshot, all-strategy signals, TradingView recommendation |
| Dashboard | `app/server.py` + `dashboard/` | FastAPI site: leaderboard, equity curves, live liquidations, TV webhook receiver |

## Quick start

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
python -m app.run_backtests          # fetch data + backtest everything
uvicorn app.server:app --port 8000   # open http://localhost:8000
```

Paper-trade a strategy (no keys needed):

```bash
python -m app.bot --symbol BTCUSDT --strategy "Supertrend (10, 3)" --risk 0.01
```

Live trading: set `BITUNIX_API_KEY` / `BITUNIX_SECRET_KEY` env vars. **Start tiny.**

## MCP (Claude integration)

`.mcp.json` registers the `tradingview-trade` server. Tools:
`get_klines`, `get_indicators`, `get_strategy_signals`, `get_tradingview_analysis`.

TradingView **alert webhooks** post to `/webhook/tradingview` (TV paid plan required
to send webhooks); alerts are readable at `/api/tv-alerts`.

## Honest limitations

- **Other users' SL/TP/limit orders are private.** No exchange or API exposes them.
  The public proxies are the liquidation feed (`/api/liquidations`) and order-book depth.
- Backtests are on spot 1h candles; futures funding rates are not modeled.
- Vectorized engine assumes fills at next-bar close ± slippage; real fills differ.
- Subjective methods (ICT/SMC, price action) were converted to explicit rules —
  results reflect those rules, not any guru's discretion.
- Past performance does not predict future results. Nothing here is financial advice.
