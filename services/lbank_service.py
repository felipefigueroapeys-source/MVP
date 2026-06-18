import requests
from typing import Dict, Any, Optional


class LBankService:
    """
    Servicio público LBank Spot.

    Endpoints usados:
    - GET https://api.lbkex.com/v2/currencyPairs.do
    - GET https://api.lbkex.com/v2/ticker/24hr.do?symbol=<base>_<quote>

    No usa API key. Solo valida presencia de par spot y ticker 24h.
    """

    BASE_URL = "https://api.lbkex.com"

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self._pairs_cache: Optional[set[str]] = None
        self._ticker_cache: Optional[dict[str, Dict[str, Any]]] = None

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.BASE_URL}{path}"
        response = requests.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        return payload

    def get_currency_pairs(self) -> set[str]:
        if self._pairs_cache is not None:
            return self._pairs_cache

        payload = self._get("/v2/currencyPairs.do")
        data = payload.get("data", [])
        self._pairs_cache = {str(p).lower() for p in data}
        return self._pairs_cache

    def get_24h_ticker_all(self) -> dict[str, Dict[str, Any]]:
        """
        LBank permite symbol=all en el ticker 24h.
        Si el endpoint falla para all, el validador puede consultar por símbolo puntual.
        """
        if self._ticker_cache is not None:
            return self._ticker_cache

        try:
            payload = self._get("/v2/ticker/24hr.do", params={"symbol": "all"})
            data = payload.get("data", [])
            cache = {}
            if isinstance(data, list):
                for item in data:
                    symbol = str(item.get("symbol", "")).lower()
                    if symbol:
                        cache[symbol] = item
            self._ticker_cache = cache
        except Exception:
            self._ticker_cache = {}

        return self._ticker_cache

    def get_24h_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        symbol = symbol.lower()
        all_cache = self.get_24h_ticker_all()
        if symbol in all_cache:
            return all_cache[symbol]

        try:
            payload = self._get("/v2/ticker/24hr.do", params={"symbol": symbol})
            data = payload.get("data")
            if isinstance(data, list) and data:
                return data[0]
            if isinstance(data, dict):
                return data
        except Exception:
            return None

        return None

    def validate_spot_pair(self, base_asset: str, quote_assets: list[str]) -> Optional[Dict[str, Any]]:
        base_asset = base_asset.upper()
        quote_assets = [q.upper() for q in quote_assets]
        pairs = self.get_currency_pairs()

        for quote in quote_assets:
            lbank_symbol = f"{base_asset.lower()}_{quote.lower()}"
            if lbank_symbol not in pairs:
                continue

            ticker_item = self.get_24h_ticker(lbank_symbol)
            quote_volume = None
            price_change_percent = None
            last_price = None

            if ticker_item:
                ticker = ticker_item.get("ticker", ticker_item)
                try:
                    quote_volume = float(ticker.get("turnover", 0))
                except (TypeError, ValueError):
                    quote_volume = None
                try:
                    price_change_percent = float(ticker.get("change", 0))
                except (TypeError, ValueError):
                    price_change_percent = None
                try:
                    raw_last = ticker.get("latest", ticker.get("last", ticker.get("close")))
                    last_price = float(raw_last) if raw_last is not None else None
                except (TypeError, ValueError):
                    last_price = None

            return {
                "exchange": "LBank",
                "symbol": f"{base_asset}{quote}",
                "raw_symbol": lbank_symbol,
                "base_asset": base_asset,
                "quote_asset": quote,
                "spot": True,
                "quote_volume": quote_volume,
                "price_change_percent": price_change_percent,
                "last_price": last_price,
            }

        return None
