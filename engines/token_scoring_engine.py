from models.token import TokenCandidate
from app.color_theme import color_5_from_score


class TokenScoringEngine:
    def __init__(self, config: dict):
        self.config = config
        self.points = config.get("token_scoring", {})
        self.categories = config.get("categories", {})
        self.filters = config.get("token_filters", {})
        self.gates = config.get("token_quality_gates", {})
        self.preferred_exchanges = set(config.get("exchanges", {}).get("preferred", []))

    def score(self, token: TokenCandidate, sector_status: str = "observacion") -> TokenCandidate:
        score = 0
        notes: list[str] = []

        if sector_status == "prioritario":
            score += self.points.get("points_sector_priority", 3)
            notes.append("Pertenece a sector prioritario.")
        elif sector_status == "interesante":
            score += self.points.get("points_sector_interesting", 2)
            notes.append("Pertenece a sector interesante.")

        if token.spot_pair:
            score += self.points.get("points_spot_pair_confirmed", 3)
            notes.append("Par spot confirmado.")
        else:
            notes.append("Sin par spot USDT/USDC validado: no puede ser B o superior.")

        preferred_quotes = set(self.filters.get("preferred_quotes", ["USDT", "USDC"]))
        if token.quote_asset in preferred_quotes:
            score += self.points.get("points_preferred_quote", 3)
            notes.append(f"Quote preferido: {token.quote_asset}.")

        min_mcap = self.filters.get("min_market_cap_usd", 100_000_000)
        ideal_mcap = self.filters.get("ideal_market_cap_usd", 500_000_000)
        min_vol = self.filters.get("min_volume_24h_usd", 10_000_000)
        ideal_vol = self.filters.get("ideal_volume_24h_usd", 50_000_000)

        mcap = token.market_cap_usd or 0
        vol = token.volume_24h_usd or 0

        if mcap >= ideal_mcap:
            score += self.points.get("points_market_cap_above_500m", 2)
            notes.append("Market cap > 500M.")
        elif mcap >= min_mcap:
            score += self.points.get("points_market_cap_above_100m", 1)
            notes.append("Market cap > 100M.")

        if vol >= ideal_vol:
            score += self.points.get("points_volume_above_50m", 2)
            notes.append("Volumen 24h > 50M.")
        elif vol >= min_vol:
            score += self.points.get("points_volume_above_10m", 1)
            notes.append("Volumen 24h > 10M.")
        else:
            score += self.points.get("penalty_low_volume", -3)
            notes.append("Volumen bajo.")

        ch30 = token.change_30d_pct
        if ch30 is not None:
            if ch30 > self.filters.get("ideal_30d_change", 20):
                score += self.points.get("points_30d_above_20", 3)
                notes.append("30D > 20%.")
            elif ch30 > self.filters.get("desired_30d_change", 10):
                score += self.points.get("points_30d_above_10", 2)
                notes.append("30D > 10%.")
            elif ch30 > self.filters.get("accepted_30d_change", 5):
                score += self.points.get("points_30d_above_5", 1)
                notes.append("30D > 5%.")

        ch7 = token.change_7d_pct
        if ch7 is not None and ch7 > self.filters.get("min_7d_change", 5):
            score += self.points.get("points_7d_above_5", 2)
            notes.append("7D > 5%.")

        ch24 = token.change_24h_pct
        if ch24 is not None:
            if 2 <= ch24 <= 15:
                score += self.points.get("points_24h_between_2_and_15", 2)
                notes.append("24h entre 2% y 15%.")
            elif ch24 > 30:
                score += self.points.get("penalty_vertical_extension", -2)
                notes.append("Subida 24h muy extendida.")

        if token.exchange in self.preferred_exchanges:
            score += self.points.get("points_preferred_exchange", 2)
            notes.append(f"Exchange preferido: {token.exchange}.")

        token.score = score
        token.notes = notes

        token.category = self._category_from_score(score)

        # GATES: corrigen falsos positivos.
        if self.gates.get("require_spot_pair_for_b_or_higher", True) and not token.spot_pair:
            token.category = self._min_category(token.category, "C Descartada")
            notes.append("Gate: sin spot validado, máximo C.")

        if self.gates.get("require_min_market_cap_for_b_or_higher", True) and mcap < min_mcap:
            token.category = self._min_category(token.category, "C Descartada")
            notes.append("Gate: market cap bajo, máximo C.")

        if self.gates.get("require_min_volume_for_b_or_higher", True) and vol < min_vol:
            token.category = self._min_category(token.category, "C Descartada")
            notes.append("Gate: volumen bajo, máximo C.")

        min_24h = self.gates.get("block_24h_below_for_b_or_higher", -10)
        if ch24 is not None and ch24 < min_24h:
            token.category = self._min_category(token.category, "C Descartada")
            notes.append(f"Gate: 24h < {min_24h}%, máximo C.")

        cap_to_b = self.gates.get("cap_to_b_if_24h_above", 20)
        if ch24 is not None and ch24 > cap_to_b:
            token.category = self._min_category(token.category, "B Vigilancia")
            notes.append(f"Cap: 24h > {cap_to_b}%, máximo B por extensión.")

        cap_to_a = self.gates.get("cap_to_a_if_24h_above", 15)
        if ch24 is not None and ch24 > cap_to_a:
            token.category = self._min_category(token.category, "A Candidata fuerte")
            notes.append(f"Cap: 24h > {cap_to_a}%, máximo A por extensión.")

        token.color_level = self._color_level_from_category(token.category, score)
        return token

    def _category_from_score(self, score: int) -> str:
        if score >= self.categories.get("a_plus_min_score", 18):
            return "A+ Prioridad alta"
        if score >= self.categories.get("a_min_score", 14):
            return "A Candidata fuerte"
        if score >= self.categories.get("b_min_score", 10):
            return "B Vigilancia"
        return "C Descartada"

    def _rank(self, category: str) -> int:
        if category.startswith("A+"):
            return 4
        if category.startswith("A "):
            return 3
        if category.startswith("B "):
            return 2
        return 1

    def _category_by_rank(self, rank: int) -> str:
        return {
            4: "A+ Prioridad alta",
            3: "A Candidata fuerte",
            2: "B Vigilancia",
            1: "C Descartada",
        }.get(rank, "C Descartada")

    def _min_category(self, current: str, cap: str) -> str:
        return self._category_by_rank(min(self._rank(current), self._rank(cap)))

    def _color_level_from_category(self, category: str, score: int) -> int:
        if category.startswith("A+"):
            return 5
        if category.startswith("A "):
            return 4
        if category.startswith("B "):
            return 3
        if score >= 7:
            return 2
        return 1
