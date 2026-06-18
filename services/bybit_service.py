import requests
from typing import Dict, Any, Optional


class BybitService:
    """
    Servicio público Bybit Spot.

    Endpoints usados:
    - GET https://api.bybit.com/v5/market/instruments-info?category=spot
    - GET https://api.bybit.com/v5/market/tickers?category=spot&symbol=<BASE><QUOTE>

    No usa API key. Solo valida presencia de par spot y ticker 24h.
    """

    BASE_URL = "https://api.bybit.com"

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self._symbols_cache: Optional[list[Dict[str, Any]]] = None

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.BASE_URL}{path}"
        response = requests.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()

        # Bybit usa retCode=0 como éxito.
        if isinstance(payload, dict) and payload.get("retCode") not in (0, None):
            raise RuntimeError(f"Bybit API error: {payload.get('retCode')} {payload.get('retMsg')}")

        return payload

    def get_spot_symbols(self) -> list[Dict[str, Any]]:
        if self._symbols_cache is not None:
            return self._symbols_cache

        payload = self._get("/v5/market/instruments-info", params={"category": "spot"})
        result = payload.get("result", {})
        self._symbols_cache = result.get("list", []) or []
        return self._symbols_cache

    def get_24h_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        try:
            payload = self._get(
                "/v5/market/tickers",
                params={"category": "spot", "symbol": symbol.upper()},
            )
            result = payload.get("result", {})
            items = result.get("list", []) or []
            if items:
                return items[0]
        except Exception:
            return None
        return None

    def validate_spot_pair(self, base_asset: str, quote_assets: list[str]) -> Optional[Dict[str, Any]]:
        base_asset = base_asset.upper()
        quote_assets = [q.upper() for q in quote_assets]

        symbols = self.get_spot_symbols()

        for quote in quote_assets:
            target_symbol = f"{base_asset}{quote}"
            match = next(
                (
                    s for s in symbols
                    if str(s.get("symbol", "")).upper() == target_symbol
                    and str(s.get("baseCoin", "")).upper() == base_asset
                    and str(s.get("quoteCoin", "")).upper() == quote
                    and str(s.get("status", "")).lower() == "trading"
                ),
                None,
            )

            if not match:
                continue

            ticker = self.get_24h_ticker(target_symbol)
            quote_volume = None
            price_change_percent = None
            last_price = None

            if ticker:
                try:
                    quote_volume = float(ticker.get("turnover24h", 0))
                except (TypeError, ValueError):
                    quote_volume = None

                try:
                    # Bybit devuelve price24hPcnt en formato decimal:
                    # 0.05 = 5%.
                    raw_change = float(ticker.get("price24hPcnt", 0))
                    price_change_percent = raw_change * 100
                except (TypeError, ValueError):
                    price_change_percent = None

                try:
                    last_price = float(ticker.get("lastPrice", 0))
                except (TypeError, ValueError):
                    last_price = None

            return {
                "exchange": "Bybit",
                "symbol": target_symbol,
                "base_asset": base_asset,
                "quote_asset": quote,
                "spot": True,
                "quote_volume": quote_volume,
                "price_change_percent": price_change_percent,
                "last_price": last_price,
            }

        return None
