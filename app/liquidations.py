"""Collect live futures liquidation orders (public forced-liquidation feeds).

NOTE: exchanges only publish LIQUIDATION events. Individual users' SL/TP/limit
orders are private and not observable by anyone; the closest public proxies are
this liquidation feed plus order-book depth.

Primary source: Binance futures !forceOrder@arr websocket.
Runs as an asyncio background task inside the FastAPI server; if the host
network blocks the exchange (common for local ISPs), it retries with backoff
and the API simply reports an empty/stale feed.
"""

import asyncio
import json
import time
from collections import deque

WS_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"
WATCHED = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
MAX_EVENTS = 2000
RETRY_BASE_SEC = 5
RETRY_MAX_SEC = 300

events: deque = deque(maxlen=MAX_EVENTS)
status = {"connected": False, "last_event_ts": None, "error": None}


async def collector():
    import websockets
    backoff = RETRY_BASE_SEC
    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20) as ws:
                status.update(connected=True, error=None)
                backoff = RETRY_BASE_SEC
                async for raw in ws:
                    msg = json.loads(raw)
                    order = msg.get("o", {})
                    symbol = order.get("s", "")
                    if symbol not in WATCHED:
                        continue
                    events.append({
                        "symbol": symbol,
                        "side": order.get("S"),          # SELL = long liquidated
                        "price": float(order.get("ap", 0)),
                        "qty": float(order.get("q", 0)),
                        "value_usd": float(order.get("ap", 0)) * float(order.get("q", 0)),
                        "time": order.get("T"),
                    })
                    status["last_event_ts"] = int(time.time())
        except Exception as exc:  # noqa: BLE001 - keep feed alive on any network error
            status.update(connected=False, error=str(exc)[:200])
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, RETRY_MAX_SEC)


def snapshot(limit: int = 200) -> dict:
    recent = list(events)[-limit:]
    summary = {}
    for e in recent:
        s = summary.setdefault(e["symbol"], {"long_liqs_usd": 0.0, "short_liqs_usd": 0.0, "count": 0})
        if e["side"] == "SELL":
            s["long_liqs_usd"] += e["value_usd"]
        else:
            s["short_liqs_usd"] += e["value_usd"]
        s["count"] += 1
    return {"status": status, "summary": summary, "events": recent[::-1]}
