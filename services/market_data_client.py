from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import math
import time
import requests


@dataclass
class Candle:
    exchange: str
    symbol: str
    interval: str
    open_time_ms: int
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def open_time_iso(self) -> str:
        return datetime.fromtimestamp(self.open_time_ms / 1000, tz=timezone.utc).isoformat()

    @property
    def close_time_iso(self) -> str:
        return datetime.fromtimestamp(self.close_time_ms / 1000, tz=timezone.utc).isoformat()


class MarketDataClient:
    """Cliente público para OHLC intradía.

    MVP 2.9.11:
    - prioriza el exchange original de la señal;
    - agrega LBank spot klines como fuente principal para señales validadas en LBank;
    - mantiene Binance/Bybit;
    - agrega fallback CoinGeckoRange por coin_id para backfill histórico preliminar.

    No usa API keys. El fallback CoinGeckoRange no es OHLC real: convierte puntos de precio
    en velas sintéticas open=high=low=close, por lo que sirve para retorno relativo y
    backfill preliminar, pero no para validar mechas intradía con máxima precisión.
    """

    BINANCE_BASE = "https://api.binance.com"
    BYBIT_BASE = "https://api.bybit.com"
    LBANK_BASE = "https://api.lbkex.com"
    COINGECKO_BASE = "https://api.coingecko.com/api/v3"

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.timeout = int(cfg.get("request_timeout_seconds", 20))
        self.retry_attempts = int(cfg.get("retry_attempts", 2))
        self.retry_sleep_seconds = float(cfg.get("retry_sleep_seconds", 1.0))
        self.blocked_retry_attempts = int(cfg.get("blocked_retry_attempts", 0))
        self._cache: dict[tuple[str, str, str, int, int, str], list[Candle]] = {}
        self._blocked_exchanges: set[str] = set()

    def get_klines(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        limit: int = 1000,
        coin_id: str | None = None,
    ) -> list[Candle]:
        exchange = self._normalize_exchange(exchange)
        symbol = self._normalize_symbol(symbol, exchange=exchange)
        start_ms = self._to_ms(start)
        end_ms = self._to_ms(end)
        coin_key = str(coin_id or "").strip().lower()
        key = (exchange, symbol, interval, start_ms, end_ms, coin_key)
        if key in self._cache:
            return self._cache[key]

        if exchange == "Binance":
            candles = self._get_binance_klines(symbol, interval, start_ms, end_ms, limit=limit)
        elif exchange == "Bybit":
            candles = self._get_bybit_klines(symbol, interval, start_ms, end_ms, limit=limit)
        elif exchange == "LBank":
            candles = self._get_lbank_klines(symbol, interval, start_ms, end_ms)
        elif exchange == "CoinGeckoRange":
            if not coin_key:
                raise ValueError("CoinGeckoRange requiere coin_id")
            candles = self._get_coingecko_range_candles(coin_key, symbol, interval, start_ms, end_ms)
        else:
            raise ValueError(f"Exchange OHLC no soportado: {exchange}")

        candles = sorted(candles, key=lambda c: c.open_time_ms)
        self._cache[key] = candles
        return candles

    def get_first_available_klines(
        self,
        preferred_exchanges: list[str],
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        coin_id: str | None = None,
    ) -> tuple[str | None, list[Candle], str]:
        errors = []
        for exchange in preferred_exchanges:
            normalized = self._normalize_exchange(exchange)
            if not normalized:
                continue
            if normalized in self._blocked_exchanges:
                errors.append(f"{normalized}:blocked_skip")
                continue
            if normalized == "CoinGeckoRange" and not coin_id:
                errors.append("CoinGeckoRange:sin_coin_id")
                continue
            try:
                candles = self.get_klines(normalized, symbol, interval, start, end, coin_id=coin_id)
                if candles:
                    return normalized, candles, ""
                errors.append(f"{normalized}:sin_velas")
            except Exception as exc:
                msg = f"{normalized}:{type(exc).__name__}:{exc}"
                errors.append(msg)
                if self._is_blocked_error(exc):
                    self._blocked_exchanges.add(normalized)
        return None, [], " | ".join(errors)

    def _get_binance_klines(self, symbol: str, interval: str, start_ms: int, end_ms: int, limit: int) -> list[Candle]:
        interval = self._binance_interval(interval)
        url = f"{self.BINANCE_BASE}/api/v3/klines"
        out: list[Candle] = []
        cursor = start_ms
        while cursor < end_ms:
            payload = self._get_json(url, params={
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": min(limit, 1000),
            })
            if not isinstance(payload, list) or not payload:
                break
            for item in payload:
                out.append(Candle(
                    exchange="Binance",
                    symbol=symbol,
                    interval=interval,
                    open_time_ms=int(item[0]),
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5]),
                    close_time_ms=int(item[6]),
                ))
            last_open = int(payload[-1][0])
            next_cursor = last_open + self._interval_ms(interval)
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(payload) < limit:
                break
        return self._filter_range(out, start_ms, end_ms)

    def _get_bybit_klines(self, symbol: str, interval: str, start_ms: int, end_ms: int, limit: int) -> list[Candle]:
        bybit_interval = self._bybit_interval(interval)
        url = f"{self.BYBIT_BASE}/v5/market/kline"
        out: list[Candle] = []
        cursor = start_ms
        while cursor < end_ms:
            payload = self._get_json(url, params={
                "category": "spot",
                "symbol": symbol,
                "interval": bybit_interval,
                "start": cursor,
                "end": end_ms,
                "limit": min(limit, 1000),
            })
            result = payload.get("result", {}) if isinstance(payload, dict) else {}
            items = result.get("list", []) or []
            if not items:
                break
            batch = []
            for item in items:
                open_ms = int(item[0])
                close_ms = open_ms + self._interval_ms(interval) - 1
                batch.append(Candle(
                    exchange="Bybit",
                    symbol=symbol,
                    interval=interval,
                    open_time_ms=open_ms,
                    close_time_ms=close_ms,
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5]),
                ))
            batch = sorted(batch, key=lambda c: c.open_time_ms)
            out.extend(batch)
            next_cursor = batch[-1].open_time_ms + self._interval_ms(interval)
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(items) < limit:
                break
        return self._filter_range(out, start_ms, end_ms)

    def _get_lbank_klines(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> list[Candle]:
        lbank_interval = self._lbank_interval(interval)
        symbol = self._lbank_symbol(symbol)
        url = f"{self.LBANK_BASE}/v1/kline.do"
        interval_ms = self._interval_ms(interval)
        bars_needed = max(1, math.ceil((end_ms - start_ms) / interval_ms) + 5)
        size = min(max(bars_needed, 1), 2880)
        # LBank usa time en segundos. En la documentación oficial el parámetro time
        # marca el timestamp de referencia y el endpoint devuelve barras históricas.
        payload = self._get_json(url, params={
            "symbol": symbol,
            "type": lbank_interval,
            "size": size,
            "time": int(end_ms / 1000),
        })
        if isinstance(payload, dict):
            items = payload.get("data", []) or []
        else:
            items = payload or []
        out: list[Candle] = []
        for item in items:
            if not isinstance(item, (list, tuple)) or len(item) < 6:
                continue
            open_ms = int(float(item[0])) * 1000
            a = float(item[2])
            b = float(item[3])
            out.append(Candle(
                exchange="LBank",
                symbol=symbol,
                interval=interval,
                open_time_ms=open_ms,
                close_time_ms=open_ms + interval_ms - 1,
                open=float(item[1]),
                high=max(a, b),
                low=min(a, b),
                close=float(item[4]),
                volume=float(item[5]),
            ))
        return self._filter_range(out, start_ms, end_ms)

    def _get_coingecko_range_candles(self, coin_id: str, symbol: str, interval: str, start_ms: int, end_ms: int) -> list[Candle]:
        url = f"{self.COINGECKO_BASE}/coins/{coin_id}/market_chart/range"
        payload = self._get_json(url, params={
            "vs_currency": "usd",
            "from": int(start_ms / 1000),
            "to": int(end_ms / 1000),
        })
        prices = payload.get("prices", []) if isinstance(payload, dict) else []
        interval_ms = self._interval_ms(interval)
        out: list[Candle] = []
        for item in prices:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            open_ms = int(float(item[0]))
            price = float(item[1])
            out.append(Candle(
                exchange="CoinGeckoRange",
                symbol=symbol or coin_id,
                interval=interval,
                open_time_ms=open_ms,
                close_time_ms=open_ms + interval_ms - 1,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=0.0,
            ))
        return self._filter_range(out, start_ms, end_ms)

    def _get_json(self, url: str, params: dict[str, Any]) -> Any:
        last_exc = None
        attempts = self.retry_attempts + 1
        for attempt in range(attempts):
            try:
                response = requests.get(url, params=params, timeout=self.timeout)
                if response.status_code in (403, 451):
                    raise RuntimeError(f"{response.status_code} blocked/restricted: {response.url}")
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_exc = exc
                if self._is_blocked_error(exc):
                    break
                if attempt < attempts - 1:
                    time.sleep(self.retry_sleep_seconds * (attempt + 1))
        raise RuntimeError(f"Market data request failed: {last_exc}")

    def _filter_range(self, candles: list[Candle], start_ms: int, end_ms: int) -> list[Candle]:
        return sorted([c for c in candles if start_ms <= c.open_time_ms <= end_ms], key=lambda c: c.open_time_ms)

    def _normalize_exchange(self, exchange: str) -> str:
        e = str(exchange or "").strip().lower()
        if e == "binance":
            return "Binance"
        if e == "bybit":
            return "Bybit"
        if e == "lbank":
            return "LBank"
        if e in {"coingeckorange", "coingecko", "cg", "coingecko_range"}:
            return "CoinGeckoRange"
        return str(exchange or "").strip() or ""

    def _normalize_symbol(self, symbol: str, exchange: str = "") -> str:
        value = str(symbol or "").replace("/", "").replace("_", "").upper().strip()
        if exchange == "LBank":
            return self._lbank_symbol(value)
        return value

    def _lbank_symbol(self, symbol: str) -> str:
        value = str(symbol or "").replace("/", "").replace("_", "").upper().strip()
        for quote in ("USDT", "USDC", "BTC", "ETH"):
            if value.endswith(quote) and len(value) > len(quote):
                return f"{value[:-len(quote)].lower()}_{quote.lower()}"
        return value.lower()

    def _to_ms(self, value: datetime) -> int:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp() * 1000)

    def _binance_interval(self, interval: str) -> str:
        value = str(interval).strip()
        if value in {"15", "15m"}:
            return "15m"
        if value in {"60", "1h"}:
            return "1h"
        if value in {"240", "4h"}:
            return "4h"
        if value in {"D", "1d"}:
            return "1d"
        return value

    def _bybit_interval(self, interval: str) -> str:
        value = str(interval).strip()
        mapping = {"15m": "15", "1h": "60", "60": "60", "4h": "240", "1d": "D"}
        return mapping.get(value, value)

    def _lbank_interval(self, interval: str) -> str:
        value = str(interval).strip()
        mapping = {
            "1": "minute1", "1m": "minute1",
            "5": "minute5", "5m": "minute5",
            "15": "minute15", "15m": "minute15",
            "30": "minute30", "30m": "minute30",
            "60": "hour1", "1h": "hour1",
            "240": "hour4", "4h": "hour4",
            "D": "day1", "1d": "day1",
        }
        return mapping.get(value, value)

    def _interval_ms(self, interval: str) -> int:
        value = str(interval).strip()
        mapping = {
            "1": 60_000,
            "1m": 60_000,
            "minute1": 60_000,
            "3": 180_000,
            "5": 300_000,
            "5m": 300_000,
            "minute5": 300_000,
            "15": 900_000,
            "15m": 900_000,
            "minute15": 900_000,
            "30": 1_800_000,
            "30m": 1_800_000,
            "minute30": 1_800_000,
            "60": 3_600_000,
            "1h": 3_600_000,
            "hour1": 3_600_000,
            "240": 14_400_000,
            "4h": 14_400_000,
            "hour4": 14_400_000,
            "D": 86_400_000,
            "1d": 86_400_000,
            "day1": 86_400_000,
        }
        return mapping.get(value, 900_000)

    def _is_blocked_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return "403" in text or "451" in text or "blocked" in text or "restricted" in text
