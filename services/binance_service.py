import requests
from typing import Dict, Any, Optional


class BinanceService:
    BASE_URL = "https://api.binance.com"

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self._exchange_info_cache: Optional[Dict[str, Any]] = None
        self._ticker_cache: Optional[list[Dict[str, Any]]] = None

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.BASE_URL}{path}"
        response = requests.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_exchange_info(self) -> Dict[str, Any]:
        if self._exchange_info_cache is None:
            self._exchange_info_cache = self._get("/api/v3/exchangeInfo")
        return self._exchange_info_cache

    def get_24h_tickers(self) -> list[Dict[str, Any]]:
        if self._ticker_cache is None:
            self._ticker_cache = self._get("/api/v3/ticker/24hr")
        return self._ticker_cache

    def validate_spot_pair(self, base_asset: str, quote_assets: list[str]) -> Optional[Dict[str, Any]]:
        base_asset = base_asset.upper()
        quote_assets = [q.upper() for q in quote_assets]

        info = self.get_exchange_info()
        symbols = info.get("symbols", [])

        valid_symbols = [
            s for s in symbols
            if s.get("baseAsset") == base_asset
            and s.get("quoteAsset") in quote_assets
            and s.get("status") == "TRADING"
            and s.get("isSpotTradingAllowed") is True
        ]

        if not valid_symbols:
            return None

        preferred = sorted(valid_symbols, key=lambda x: quote_assets.index(x["quoteAsset"]))
        chosen = preferred[0]
        symbol_name = chosen["symbol"]

        tickers = self.get_24h_tickers()
        ticker = next((t for t in tickers if t.get("symbol") == symbol_name), None)

        result = {
            "exchange": "Binance",
            "symbol": symbol_name,
            "base_asset": chosen["baseAsset"],
            "quote_asset": chosen["quoteAsset"],
            "spot": True,
        }

        if ticker:
            try:
                result["quote_volume"] = float(ticker.get("quoteVolume", 0))
                result["price_change_percent"] = float(ticker.get("priceChangePercent", 0))
                result["last_price"] = float(ticker.get("lastPrice", 0))
            except ValueError:
                pass

        return result
