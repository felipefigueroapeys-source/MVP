from typing import Dict, Any


class MarketContextEngine:
    def __init__(self, config: dict):
        self.config = config

    def classify(self, btc_change_24h: float | None, eth_change_24h: float | None) -> Dict[str, Any]:
        thresholds = self.config.get("market_mode", {})
        btc_active = thresholds.get("btc_active_threshold_24h", 1.0)
        btc_defensive = thresholds.get("btc_defensive_threshold_24h", -1.5)
        eth_defensive = thresholds.get("eth_defensive_threshold_24h", -2.0)

        if btc_change_24h is None:
            return {
                "mode": "desconocido",
                "color": "🟡",
                "notes": ["No se pudo clasificar BTC por falta de datos."]
            }

        if btc_change_24h >= btc_active:
            mode = "busqueda_activa"
            color = "🟢"
            notes = ["BTC alcista: se permite búsqueda activa de longs spot."]
        elif btc_change_24h <= btc_defensive or (eth_change_24h is not None and eth_change_24h <= eth_defensive):
            mode = "defensivo_selectivo"
            color = "🟡"
            notes = ["BTC/ETH débiles: solo activos fuertes, no agresivos, preparar DCA."]
        else:
            mode = "selectivo"
            color = "🟡"
            notes = ["Mercado lateral o mixto: operar selectivo."]

        return {
            "mode": mode,
            "color": color,
            "btc_change_24h": btc_change_24h,
            "eth_change_24h": eth_change_24h,
            "notes": notes,
        }
