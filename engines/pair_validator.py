from typing import Optional, Dict, Any


class PairValidator:
    def __init__(
        self,
        validators: list,
        preferred_quotes: list[str],
        max_price_deviation_pct: float = 50.0,
        reject_price_mismatch: bool = True,
    ):
        self.validators = validators
        self.preferred_quotes = preferred_quotes
        self.max_price_deviation_pct = float(max_price_deviation_pct)
        self.reject_price_mismatch = bool(reject_price_mismatch)
        self.stats = {
            "validated": 0,
            "accepted_without_pair_price": 0,
            "rejected_price_mismatch": 0,
            "validator_errors": 0,
        }

    def validate(self, base_asset: str, reference_price: float | None = None) -> Optional[Dict[str, Any]]:
        """
        Valida en orden de prioridad de exchanges.

        Si el exchange entrega último precio, lo compara con el precio CoinGecko del activo.
        Esto reduce falsos matches de tickers ambiguos (por ejemplo, dos activos distintos con
        el mismo símbolo). Un par sin ticker puede aceptarse, pero queda marcado como no verificado.
        """
        for validator in self.validators:
            try:
                result = validator.validate_spot_pair(base_asset, self.preferred_quotes)
            except Exception:
                self.stats["validator_errors"] += 1
                result = None
            if not result:
                continue

            last_price = self._safe_float(result.get("last_price"))
            ref = self._safe_float(reference_price)
            if ref is not None and ref > 0 and last_price is not None and last_price > 0:
                deviation = abs(last_price - ref) / ref * 100
                result["pair_price_deviation_pct"] = deviation
                result["pair_identity_status"] = "price_sanity_verified"
                if self.reject_price_mismatch and deviation > self.max_price_deviation_pct:
                    self.stats["rejected_price_mismatch"] += 1
                    continue
            else:
                result["pair_price_deviation_pct"] = None
                result["pair_identity_status"] = "pair_found_price_unavailable"
                self.stats["accepted_without_pair_price"] += 1

            self.stats["validated"] += 1
            return result
        return None

    @staticmethod
    def _safe_float(value):
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None
