from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class Sector:
    id: str
    name: str
    market_cap_usd: Optional[float] = None
    volume_24h_usd: Optional[float] = None
    change_24h_pct: Optional[float] = None
    change_7d_pct: Optional[float] = None
    top_3_coins: List[str] = field(default_factory=list)
    source: str = "unknown"
    score: int = 0
    status: str = "sin_clasificar"
    notes: List[str] = field(default_factory=list)
