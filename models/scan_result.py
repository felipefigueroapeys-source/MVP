from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any

from models.sector import Sector
from models.token import TokenCandidate


@dataclass
class ScanResult:
    created_at: datetime
    market_mode: str
    market_context: Dict[str, Any] = field(default_factory=dict)
    sectors: List[Sector] = field(default_factory=list)
    tokens: List[TokenCandidate] = field(default_factory=list)
