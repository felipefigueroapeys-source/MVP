from models.sector import Sector


class SectorScoringEngine:
    def __init__(self, config: dict):
        self.config = config
        self.points = config.get("sector_scoring", {})

    def score(self, sector: Sector) -> Sector:
        score = 0
        notes: list[str] = []

        ch24 = sector.change_24h_pct
        ch7 = sector.change_7d_pct
        mcap = sector.market_cap_usd or 0
        vol = sector.volume_24h_usd or 0

        if ch24 is not None:
            if ch24 > 5:
                score += self.points.get("points_24h_above_5", 3)
                notes.append("24h > 5%.")
            elif ch24 > 2:
                score += self.points.get("points_24h_above_2", 2)
                notes.append("24h > 2%.")
            elif ch24 < 0:
                score += self.points.get("penalty_sector_negative", -3)
                notes.append("Sector negativo 24h.")

        if ch7 is not None:
            if ch7 > 15:
                score += self.points.get("points_7d_above_15", 3)
                notes.append("7D > 15%.")
            elif ch7 > 10:
                score += self.points.get("points_7d_above_10", 2)
                notes.append("7D > 10%.")
            elif ch7 >= 5:
                score += self.points.get("points_7d_5_to_10", 1)
                notes.append("7D entre 5% y 10%.")

        if vol >= 50_000_000:
            score += self.points.get("points_volume_strong", 2)
            notes.append("Volumen sectorial alto.")

        if mcap >= 1_000_000_000:
            score += self.points.get("points_market_cap_above_1b", 2)
            notes.append("Market cap sectorial > 1B.")
        elif mcap >= 500_000_000:
            score += self.points.get("points_market_cap_above_500m", 1)
            notes.append("Market cap sectorial > 500M.")

        sector.score = score
        sector.notes = notes

        if score >= 10:
            sector.status = "prioritario"
        elif score >= 7:
            sector.status = "interesante"
        elif score >= 4:
            sector.status = "observacion"
        else:
            sector.status = "descartar"

        return sector
