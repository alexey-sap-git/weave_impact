from dataclasses import dataclass


@dataclass
class ImpactScore:
    login: str
    total: float
    knowledge_sharer_score: float
    rank: int = 0
    tier: str = ""

    def __post_init__(self):
        self.tier = self._compute_tier()

    def _compute_tier(self) -> str:
        if self.total >= 200:
            return "Core Maintainer"
        if self.total >= 80:
            return "Major Contributor"
        if self.total >= 20:
            return "Active Contributor"
        if self.total >= 5:
            return "Contributor"
        return "Casual"
