from app.domain.contributors.entities import Contributor
from app.domain.scoring.entities import ImpactScore


class ImpactScoringService:

    def calculate(self, contributor: Contributor) -> ImpactScore:
        ks = contributor.knowledge_sharer

        knowledge_sharer_score = (
            ks.meaningful_comments * 1.5
            + ks.cross_subsystem_prs * 5.0
        )

        return ImpactScore(
            login=contributor.login,
            total=round(knowledge_sharer_score, 2),
            knowledge_sharer_score=round(knowledge_sharer_score, 2),
        )

    def rank(self, scores: list[ImpactScore]) -> list[ImpactScore]:
        sorted_scores = sorted(scores, key=lambda s: s.total, reverse=True)
        for i, score in enumerate(sorted_scores, start=1):
            score.rank = i
        return sorted_scores
