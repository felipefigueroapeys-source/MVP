from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class TokenCandidate:
    id: str
    symbol: str
    name: str
    sector_name: str
    sector_score: int = 0
    market_cap_usd: Optional[float] = None
    volume_24h_usd: Optional[float] = None
    change_24h_pct: Optional[float] = None
    change_7d_pct: Optional[float] = None
    change_30d_pct: Optional[float] = None
    spot_pair: Optional[str] = None
    quote_asset: Optional[str] = None
    exchange: Optional[str] = None
    pair_volume_24h_usd: Optional[float] = None
    pair_last_price: Optional[float] = None
    pair_price_deviation_pct: Optional[float] = None
    pair_identity_status: str = ""
    score: int = 0
    category: str = "sin_clasificar"
    color_level: int = 1
    notes: List[str] = field(default_factory=list)
    trend_signal: str = "-"
    trend_score: int = 0
    trend_sources: List[str] = field(default_factory=list)
    price_usd: Optional[float] = None
    action: str = ""
    operational_reason: str = ""
    operational_bucket: str = ""
    alerts: str = ""
    priority_tier: str = ""
