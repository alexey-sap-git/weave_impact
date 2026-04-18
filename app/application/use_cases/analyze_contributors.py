import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from app.domain.contributors.entities import (
    Contributor,
    ContributorProfile,
    GitHubLogin,
    KnowledgeSharerActivity,
    PullRequestActivity,
)
from app.domain.scoring.entities import ImpactScore
from app.domain.scoring.service import ImpactScoringService
from app.infrastructure.github.client import GitHubClient

logger = logging.getLogger(__name__)

Progress = Callable[[int, str], None]

_TRIVIAL_REVIEWS = {"lgtm", "looks good", "looks good to me", "approved", "+1", "👍", ":+1:", "nice", "great", "ok", "okay"}

_BOT_SUFFIXES = ("[bot]", "-bot", "_bot")
_BOT_NAMES = {"dependabot", "renovate", "codecov", "github-actions", "snyk-bot", "stale", "allcontributors"}


def _is_bot(login: str, user_type: str = "") -> bool:
    if user_type.lower() == "bot":
        return True
    low = login.lower()
    if any(low.endswith(s) for s in _BOT_SUFFIXES):
        return True
    if any(low == name or low.startswith(name + "-") for name in _BOT_NAMES):
        return True
    return False


def _is_meaningful_comment(body: str) -> bool:
    text = (body or "").strip()
    if len(text) < 30:
        return False
    return text.lower() not in _TRIVIAL_REVIEWS


def _top_dir(path: str) -> str:
    """Extract top-level directory from a file path."""
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else "__root__"


class AnalyzeContributorsUseCase:
    def __init__(self, github: GitHubClient, scoring: ImpactScoringService):
        self._github = github
        self._scoring = scoring

    async def execute(
        self,
        top_n: int = 50,
        days: int = 90,
        progress: Optional[Progress] = None,
    ) -> dict:
        def emit(pct: int, msg: str):
            if progress:
                progress(pct, msg)

        since = datetime.now(timezone.utc) - timedelta(days=days)
        logger.info("Analyzing contributors since %s (%d days)", since.date(), days)

        emit(5, "Fetching all data in parallel…")
        (contributors_list, repo_info), (prs, review_comments) = await asyncio.gather(
            asyncio.gather(
                self._github.get_contributors(max_pages=3),
                self._github.get_repo_info(),
            ),
            asyncio.gather(
                self._github.get_pull_requests(since=since, state="all"),
                self._github.get_review_comments(since=since),
            ),
        )
        emit(70, f"Got {len(prs)} PRs · {len(review_comments)} review comments")

        login_to_meta = {
            c["login"]: c for c in contributors_list
            if not _is_bot(c["login"], c.get("type", ""))
        }

        # ── PR activity + build pr_url→author map ─────────────────────────────
        pr_map: dict[str, PullRequestActivity] = defaultdict(PullRequestActivity)
        pr_url_to_author: dict[str, str] = {}

        for pr in prs:
            user = pr.get("user")
            if not user:
                continue
            login = user["login"]
            if _is_bot(login, user.get("type", "")):
                continue
            act = pr_map[login]
            act.opened += 1
            if pr.get("merged_at"):
                act.merged += 1
            pr_url_to_author[pr.get("url", "")] = login

        # ── Knowledge Sharer axis ─────────────────────────────────────────────
        reviewer_pr_dirs: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
        reviewer_meaningful: dict[str, int] = defaultdict(int)

        for comment in review_comments:
            user = comment.get("user")
            if not user:
                continue
            login = user["login"]
            if _is_bot(login, user.get("type", "")):
                continue
            body = comment.get("body", "")
            path = comment.get("path", "")
            pr_url = comment.get("pull_request_url", "")

            # Skip self-reviews
            if pr_url and pr_url_to_author.get(pr_url) == login:
                continue

            if _is_meaningful_comment(body):
                reviewer_meaningful[login] += 1

            if path and pr_url:
                reviewer_pr_dirs[login][pr_url].add(_top_dir(path))

        ks_map: dict[str, KnowledgeSharerActivity] = {}
        all_reviewers = set(reviewer_pr_dirs.keys()) | set(reviewer_meaningful.keys())
        for login in all_reviewers:
            pr_dirs = reviewer_pr_dirs.get(login, {})
            cross_subsystem = sum(1 for dirs in pr_dirs.values() if len(dirs) >= 2)
            ks_map[login] = KnowledgeSharerActivity(
                meaningful_comments=reviewer_meaningful.get(login, 0),
                cross_subsystem_prs=cross_subsystem,
            )

        emit(80, "Computing impact scores…")

        # ── Build contributor objects ──────────────────────────────────────────
        all_logins = set(pr_map.keys()) | set(ks_map.keys())
        sorted_logins = sorted(
            all_logins,
            key=lambda l: ks_map[l].total_weighted if l in ks_map else 0,
            reverse=True,
        )[:top_n]

        contributors: list[Contributor] = []
        for login in sorted_logins:
            meta = login_to_meta.get(login, {})
            try:
                profile = ContributorProfile(
                    login=GitHubLogin(login),
                    avatar_url=meta.get("avatar_url", f"https://avatars.githubusercontent.com/{login}"),
                    html_url=meta.get("html_url", f"https://github.com/{login}"),
                )
            except ValueError:
                continue
            contributors.append(Contributor(
                profile=profile,
                pr_activity=pr_map.get(login, PullRequestActivity()),
                knowledge_sharer=ks_map.get(login, KnowledgeSharerActivity()),
            ))

        scores = [self._scoring.calculate(c) for c in contributors]
        ranked = self._scoring.rank(scores)
        contributor_map = {c.login: c for c in contributors}
        emit(95, f"Ranked {len(ranked)} contributors — done!")

        return {
            "repo": repo_info,
            "since": since.date().isoformat(),
            "days": days,
            "total_analyzed": len(ranked),
            "contributors": [
                _serialize(ranked[i], contributor_map[ranked[i].login])
                for i in range(len(ranked))
                if ranked[i].login in contributor_map
            ],
        }


def _serialize(score: ImpactScore, contributor: Contributor) -> dict:
    pr = contributor.pr_activity
    ks = contributor.knowledge_sharer
    return {
        "rank": score.rank,
        "login": score.login,
        "avatar_url": contributor.profile.avatar_url,
        "html_url": contributor.profile.html_url,
        "tier": score.tier,
        "impact": {
            "total": score.total,
            "knowledge_sharer_score": score.knowledge_sharer_score,
        },
        "knowledge_sharer": {
            "meaningful_comments": ks.meaningful_comments,
            "cross_subsystem_prs": ks.cross_subsystem_prs,
            "weighted_score": round(ks.total_weighted, 2),
        },
    }
