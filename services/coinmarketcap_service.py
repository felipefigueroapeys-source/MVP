import os
import requests
from typing import Any, Dict, List, Optional


class CoinMarketCapService:
    """
    Servicio opcional CoinMarketCap Pro API.

    Requiere API key:
    - Variable de entorno CMC_API_KEY, o
    - config.yaml -> coinmarketcap.api_key

    Si no hay API key, el controlador omite CoinMarketCap y sigue con CoinGecko.
    """

    BASE_URL = "https://pro-api.coinmarketcap.com/v1"

    def __init__(self, api_key: str | None = None, timeout: int = 20):
        self.api_key = api_key
        self.timeout = timeout

    @classmethod
    def from_config(cls, config: dict):
        cmc_cfg = config.get("coinmarketcap", {})
        env_name = cmc_cfg.get("api_key_env", "CMC_API_KEY")
        api_key = cmc_cfg.get("api_key") or os.getenv(env_name)
        return cls(api_key=api_key)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        if not self.api_key:
            raise RuntimeError("CoinMarketCap API key no configurada.")

        url = f"{self.BASE_URL}{path}"
        headers = {
            "Accepts": "application/json",
            "X-CMC_PRO_API_KEY": self.api_key,
        }
        response = requests.get(url, headers=headers, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_categories(self) -> List[Dict[str, Any]]:
        payload = self._get("/cryptocurrency/categories")
        return payload.get("data", []) or []

    def get_category_tokens(self, category_id: str) -> Dict[str, Any]:
        """
        Devuelve detalle de una categoría y sus tokens cuando el plan/API key lo permite.
        """
        payload = self._get("/cryptocurrency/category", params={"id": category_id})
        return payload.get("data", {}) or {}
