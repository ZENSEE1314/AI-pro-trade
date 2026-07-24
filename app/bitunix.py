"""Bitunix Futures REST client.

Auth follows Bitunix's double-SHA256 scheme:
  digest = sha256(nonce + timestamp + api_key + query_params + body)
  sign   = sha256(digest + secret_key)

Set BITUNIX_API_KEY / BITUNIX_SECRET_KEY env vars. Without them the client
runs in paper mode: market data works, order calls are simulated locally.
"""

import hashlib
import json
import os
import time
import uuid

import requests

BASE_URL = "https://fapi.bitunix.com"


class BitunixClient:
    def __init__(self, api_key: str | None = None, secret_key: str | None = None):
        self.api_key = api_key or os.environ.get("BITUNIX_API_KEY", "")
        self.secret_key = secret_key or os.environ.get("BITUNIX_SECRET_KEY", "")
        self.paper_mode = not (self.api_key and self.secret_key)
        self.paper_orders: list[dict] = []

    # ---- public market data ----

    def get_kline(self, symbol: str, interval: str = "1h", limit: int = 200) -> list:
        return self._get("/api/v1/futures/market/kline", {
            "symbol": symbol, "interval": interval, "limit": limit,
        })

    def get_ticker(self, symbol: str) -> dict:
        return self._get("/api/v1/futures/market/tickers", {"symbols": symbol})

    def get_depth(self, symbol: str, limit: int = 50) -> dict:
        return self._get("/api/v1/futures/market/depth", {"symbol": symbol, "limit": limit})

    def get_funding_rate(self, symbol: str) -> dict:
        return self._get("/api/v1/futures/market/funding_rate", {"symbol": symbol})

    # ---- signed account/trade endpoints ----

    def get_account(self, margin_coin: str = "USDT") -> dict:
        if self.paper_mode:
            return {"paper": True, "available": 10000.0, "marginCoin": margin_coin}
        return self._signed("GET", "/api/v1/futures/account", {"marginCoin": margin_coin})

    def get_positions(self, symbol: str | None = None) -> dict:
        if self.paper_mode:
            return {"paper": True, "positions": []}
        params = {"symbol": symbol} if symbol else {}
        return self._signed("GET", "/api/v1/futures/position/get_pending_positions", params)

    def place_order(self, symbol: str, side: str, qty: float, *,
                    order_type: str = "MARKET", price: float | None = None,
                    take_profit: float | None = None, stop_loss: float | None = None,
                    reduce_only: bool = False) -> dict:
        body = {
            "symbol": symbol,
            "side": side.upper(),            # BUY / SELL
            "qty": str(qty),
            "orderType": order_type,
            "tradeSide": "OPEN" if not reduce_only else "CLOSE",
            "reduceOnly": reduce_only,
            "clientId": uuid.uuid4().hex[:20],
        }
        if price is not None:
            body["price"] = str(price)
        if take_profit is not None:
            body["tpPrice"] = str(take_profit)
            body["tpStopType"] = "MARK_PRICE"
        if stop_loss is not None:
            body["slPrice"] = str(stop_loss)
            body["slStopType"] = "MARK_PRICE"

        if self.paper_mode:
            order = {"paper": True, "status": "FILLED", **body, "ts": int(time.time() * 1000)}
            self.paper_orders.append(order)
            return order
        return self._signed("POST", "/api/v1/futures/trade/place_order", body=body)

    def get_open_positions_map(self) -> dict:
        """symbol -> {side: 1/-1, qty, position_id, entry} for all open positions."""
        if self.paper_mode:
            return {}
        resp = self.get_positions()
        data = resp.get("data", resp) if isinstance(resp, dict) else resp
        if isinstance(data, dict):
            data = [data]
        out = {}
        for p in data or []:
            try:
                qty = float(p.get("qty", 0))
            except (TypeError, ValueError):
                qty = 0.0
            if qty <= 0:
                continue
            side = 1 if str(p.get("side", "")).upper() in ("LONG", "BUY") else -1
            try:
                entry = float(p.get("avgOpenPrice") or 0)
            except (TypeError, ValueError):
                entry = 0.0
            out[p.get("symbol")] = {"side": side, "qty": qty,
                                    "position_id": p.get("positionId"), "entry": entry}
        return out

    def get_leverage(self, symbol: str, margin_coin: str = "USDT") -> int | None:
        """Current leverage set for a symbol (not changed by the bot)."""
        if self.paper_mode:
            return None
        resp = self._signed("GET", "/api/v1/futures/account/get_leverage_margin_mode",
                            {"symbol": symbol, "marginCoin": margin_coin})
        data = resp.get("data", {}) if isinstance(resp, dict) else {}
        try:
            return int(data.get("leverage"))
        except (TypeError, ValueError):
            return None

    def flash_close_position(self, position_id: str) -> dict:
        """Market-close an entire position by its Bitunix positionId."""
        if self.paper_mode:
            return {"code": 0, "paper": True, "closed": position_id}
        return self._signed("POST", "/api/v1/futures/trade/flash_close_position",
                            body={"positionId": str(position_id)})

    def cancel_all(self, symbol: str) -> dict:
        if self.paper_mode:
            return {"paper": True, "cancelled": symbol}
        return self._signed("POST", "/api/v1/futures/trade/cancel_all_orders",
                            body={"symbol": symbol})

    # ---- internals ----

    def _get(self, path: str, params: dict) -> dict:
        resp = requests.get(BASE_URL + path, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _signed(self, method: str, path: str, params: dict | None = None,
                body: dict | None = None) -> dict:
        nonce = uuid.uuid4().hex
        timestamp = str(int(time.time() * 1000))
        query_str = "".join(f"{k}{v}" for k, v in sorted((params or {}).items()))
        body_str = json.dumps(body, separators=(",", ":")) if body else ""
        digest = hashlib.sha256(
            (nonce + timestamp + self.api_key + query_str + body_str).encode()
        ).hexdigest()
        sign = hashlib.sha256((digest + self.secret_key).encode()).hexdigest()
        headers = {
            "api-key": self.api_key,
            "nonce": nonce,
            "timestamp": timestamp,
            "sign": sign,
            "Content-Type": "application/json",
        }
        if method == "GET":
            resp = requests.get(BASE_URL + path, params=params, headers=headers, timeout=15)
        else:
            resp = requests.post(BASE_URL + path, data=body_str, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
