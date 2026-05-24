"""
QuantBot AI — Binance Service
Wrapper completo para a Binance API (Spot + Futures).
Suporta ordens, klines, saldo, posições e WebSocket de preços.
"""

import asyncio
import hmac
import hashlib
import time
import logging
from typing import List, Dict, Optional
from urllib.parse import urlencode

import aiohttp

logger = logging.getLogger(__name__)

BASE_URL = "https://api.binance.com"
FUTURES_URL = "https://fapi.binance.com"
TESTNET_URL = "https://testnet.binance.vision"


class BinanceService:
    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = TESTNET_URL if testnet else BASE_URL
        self.session: Optional[aiohttp.ClientSession] = None

    @classmethod
    def from_user(cls, user) -> "BinanceService":
        """Criar instância a partir das credenciais do usuário (descriptografadas)."""
        key, secret = user.get_binance_credentials()
        return cls(api_key=key, api_secret=secret)

    def _sign(self, params: dict) -> str:
        query = urlencode(params)
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def _get_session(self) -> aiohttp.ClientSession:
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    "X-MBX-APIKEY": self.api_key,
                    "Content-Type": "application/json",
                }
            )
        return self.session

    async def _request(self, method: str, path: str, params: dict = None, signed: bool = False) -> dict:
        session = await self._get_session()
        params = params or {}
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["signature"] = self._sign(params)

        url = f"{self.base_url}{path}"
        try:
            async with session.request(method, url, params=params if method == "GET" else None,
                                       json=params if method != "GET" else None) as resp:
                data = await resp.json()
                if resp.status != 200:
                    logger.error(f"Binance API error {resp.status}: {data}")
                    raise Exception(f"Binance error: {data.get('msg', 'Unknown')}")
                return data
        except aiohttp.ClientError as e:
            logger.error(f"HTTP error: {e}")
            raise

    # ─── CONEXÃO ────────────────────────────────────────────────────────────

    async def test_connection(self) -> bool:
        try:
            await self._request("GET", "/api/v3/ping")
            await self._request("GET", "/api/v3/account", signed=True)
            return True
        except Exception:
            return False

    # ─── CONTA ──────────────────────────────────────────────────────────────

    async def get_account_info(self) -> Dict:
        data = await self._request("GET", "/api/v3/account", signed=True)
        balances = [b for b in data.get("balances", []) if float(b["free"]) > 0]
        return {
            "can_trade": data.get("canTrade"),
            "maker_commission": data.get("makerCommission"),
            "taker_commission": data.get("takerCommission"),
            "balances": [
                {"asset": b["asset"], "free": float(b["free"]), "locked": float(b["locked"])}
                for b in balances
            ],
        }

    async def get_usdt_balance(self) -> float:
        data = await self._request("GET", "/api/v3/account", signed=True)
        for b in data.get("balances", []):
            if b["asset"] == "USDT":
                return float(b["free"])
        return 0.0

    # ─── PREÇOS & KLINES ────────────────────────────────────────────────────

    async def get_price(self, symbol: str) -> float:
        data = await self._request("GET", "/api/v3/ticker/price", {"symbol": symbol})
        return float(data["price"])

    async def get_all_tickers(self, symbols: List[str]) -> List[Dict]:
        """Preços de múltiplos pares de uma vez."""
        data = await self._request("GET", "/api/v3/ticker/24hr")
        result = [
            {
                "symbol": t["symbol"],
                "price": float(t["lastPrice"]),
                "change_pct": float(t["priceChangePercent"]),
                "volume": float(t["quoteVolume"]),
                "high": float(t["highPrice"]),
                "low": float(t["lowPrice"]),
            }
            for t in data if t["symbol"] in symbols
        ]
        return result

    async def get_klines(self, symbol: str, interval: str = "15m", limit: int = 200) -> List[Dict]:
        """Candles OHLCV."""
        data = await self._request("GET", "/api/v3/klines", {
            "symbol": symbol, "interval": interval, "limit": limit
        })
        return [
            {
                "time": int(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
            }
            for c in data
        ]

    async def get_historical_klines(self, symbol: str, interval: str,
                                     start_date: str, end_date: str) -> List[Dict]:
        """Klines históricos para backtest."""
        import datetime
        start_ts = int(datetime.datetime.fromisoformat(start_date).timestamp() * 1000)
        end_ts = int(datetime.datetime.fromisoformat(end_date).timestamp() * 1000)
        all_candles = []
        current = start_ts

        while current < end_ts:
            data = await self._request("GET", "/api/v3/klines", {
                "symbol": symbol, "interval": interval,
                "startTime": current, "endTime": end_ts, "limit": 1000,
            })
            if not data:
                break
            candles = [
                {"time": int(c[0]), "open": float(c[1]), "high": float(c[2]),
                 "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])}
                for c in data
            ]
            all_candles.extend(candles)
            current = candles[-1]["time"] + 1
            await asyncio.sleep(0.1)  # Rate limit

        return all_candles

    # ─── ORDENS ─────────────────────────────────────────────────────────────

    async def place_order(self, symbol: str, side: str, quantity: float,
                          order_type: str = "MARKET", price: float = None,
                          stop_price: float = None) -> Dict:
        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": quantity,
        }
        if order_type == "LIMIT" and price:
            params["price"] = price
            params["timeInForce"] = "GTC"
        if stop_price:
            params["stopPrice"] = stop_price

        return await self._request("POST", "/api/v3/order", params=params, signed=True)

    async def place_oco_order(self, symbol: str, side: str, quantity: float,
                               price: float, stop_price: float, stop_limit_price: float) -> Dict:
        """OCO: Take Profit + Stop Loss em uma ordem."""
        params = {
            "symbol": symbol, "side": side.upper(), "quantity": quantity,
            "price": price, "stopPrice": stop_price,
            "stopLimitPrice": stop_limit_price, "stopLimitTimeInForce": "GTC",
        }
        return await self._request("POST", "/api/v3/order/oco", params=params, signed=True)

    async def cancel_order(self, symbol: str, order_id: int) -> Dict:
        return await self._request("DELETE", "/api/v3/order",
                                   params={"symbol": symbol, "orderId": order_id}, signed=True)

    async def get_open_orders(self, symbol: str = None) -> List[Dict]:
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/api/v3/openOrders", params=params, signed=True)

    async def get_open_positions(self) -> List[Dict]:
        """Posições abertas (Spot: ordens pendentes)."""
        orders = await self.get_open_orders()
        return [
            {
                "symbol": o["symbol"],
                "side": o["side"],
                "quantity": float(o["origQty"]),
                "price": float(o["price"]),
                "type": o["type"],
                "status": o["status"],
                "order_id": o["orderId"],
            }
            for o in orders
        ]

    async def get_trade_history(self, symbol: str = None, limit: int = 50) -> List[Dict]:
        """Histórico de trades executados."""
        if not symbol:
            symbol = "BTCUSDT"  # Default
        data = await self._request("GET", "/api/v3/myTrades",
                                   params={"symbol": symbol, "limit": limit}, signed=True)
        return [
            {
                "symbol": t["symbol"],
                "side": "BUY" if t["isBuyer"] else "SELL",
                "price": float(t["price"]),
                "quantity": float(t["qty"]),
                "commission": float(t["commission"]),
                "time": t["time"],
            }
            for t in data
        ]
