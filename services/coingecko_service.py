import time
import requests
from typing import Any, Dict, List


class CoinGeckoService:
    BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self, timeout: int = 20, retry_attempts: int = 3, retry_sleep_seconds: float = 3.0):
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.retry_sleep_seconds = retry_sleep_seconds

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.BASE_URL}{path}"
        last_error = None

        for attempt in range(1, self.retry_attempts + 1):
            try:
                response = requests.get(url, params=params, timeout=self.timeout)

                if response.status_code == 429:
                    sleep_for = self.retry_sleep_seconds * attempt
                    time.sleep(sleep_for)
                    last_error = requests.HTTPError(f"429 Too Many Requests: {url}")
                    continue

                response.raise_for_status()
                return response.json()

            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.retry_attempts:
                    time.sleep(self.retry_sleep_seconds * attempt)
                else:
                    break

        raise last_error

    def get_global_market(self) -> Dict[str, Any]:
        return self._get("/global")

    def get_categories(self) -> List[Dict[str, Any]]:
        return self._get("/coins/categories")

    def get_markets_by_category(self, category_id: str, per_page: int = 50) -> List[Dict[str, Any]]:
        return self._get(
            "/coins/markets",
            params={
                "vs_currency": "usd",
                "category": category_id,
                "order": "market_cap_desc",
                "per_page": per_page,
                "page": 1,
                "sparkline": "false",
                "price_change_percentage": "24h,7d,30d",
            },
        )

    def get_market_context_tokens(self) -> Dict[str, Dict[str, Any]]:
        data = self._get(
            "/coins/markets",
            params={
                "vs_currency": "usd",
                "ids": "bitcoin,ethereum",
                "order": "market_cap_desc",
                "per_page": 2,
                "page": 1,
                "sparkline": "false",
                "price_change_percentage": "24h",
            },
        )
        return {item["id"]: item for item in data}

    def get_trending(self) -> Dict[str, Any]:
        return self._get("/search/trending")

    def get_prices_by_ids(self, coin_ids: list[str], chunk_size: int = 200) -> dict[str, float]:
        """Obtiene precios USD por CoinGecko ID en lotes; evita búsquedas ambiguas por ticker."""
        clean = []
        seen = set()
        for coin_id in coin_ids:
            value = str(coin_id or "").strip().lower()
            if value and value not in seen:
                clean.append(value)
                seen.add(value)

        prices: dict[str, float] = {}
        for start in range(0, len(clean), max(1, int(chunk_size))):
            chunk = clean[start:start + max(1, int(chunk_size))]
            payload = self._get(
                "/simple/price",
                {"ids": ",".join(chunk), "vs_currencies": "usd"},
            )
            if not isinstance(payload, dict):
                continue
            for coin_id in chunk:
                try:
                    value = payload.get(coin_id, {}).get("usd")
                    if value is not None:
                        prices[coin_id] = float(value)
                except (TypeError, ValueError):
                    continue
        return prices

    def get_price_by_id(self, coin_id: str):
        prices = self.get_prices_by_ids([coin_id])
        return prices.get(str(coin_id or "").strip().lower())


    def get_coin_market_data(self, symbol: str) -> dict:
        """
        Busca precio actual por símbolo usando /search + /simple/price.
        Uso: performance tracker.
        """
        symbol = str(symbol).upper().replace("USDT", "").replace("USDC", "")
        search = self._get("/search", {"query": symbol})
        coins = search.get("coins", []) if isinstance(search, dict) else []

        coin_id = None
        for coin in coins:
            if str(coin.get("symbol", "")).upper() == symbol:
                coin_id = coin.get("id")
                break

        if not coin_id and coins:
            coin_id = coins[0].get("id")

        if not coin_id:
            return {}

        price_data = self._get("/simple/price", {"ids": coin_id, "vs_currencies": "usd"})
        usd = price_data.get(coin_id, {}).get("usd") if isinstance(price_data, dict) else None
        return {"id": coin_id, "symbol": symbol, "current_price": usd}

    def get_price(self, symbol: str):
        data = self.get_coin_market_data(symbol)
        return data.get("current_price")
