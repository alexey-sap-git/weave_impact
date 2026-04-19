import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from app.infrastructure.github.client import GitHubClient

logger = logging.getLogger(__name__)

Progress = Callable[[int, str], None]

_BOT_SUFFIXES = ("[bot]", "-bot", "_bot")
_BOT_NAMES = {
    "dependabot", "renovate", "codecov", "github-actions",
    "snyk-bot", "stale", "allcontributors",
}


def _is_bot(login: str, user_type: str = "") -> bool:
    if user_type.lower() == "bot":
        return True
    low = login.lower()
    return (
        any(low.endswith(s) for s in _BOT_SUFFIXES)
        or any(low == name or low.startswith(name + "-") for name in _BOT_NAMES)
    )


def _parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_bug_fix(item: dict) -> bool:
    labels = {lbl.get("name", "").lower() for lbl in item.get("labels", [])}
    title = item.get("title", "").lower()
    return (
        "bug" in labels
        or title.startswith("fix:")
        or title.startswith("fix!")
        or "fix" in title
    )


def _total_score(prs_merged: int, bug_fixes: int, issues_closed: int) -> float:
    return bug_fixes * 3.0 + prs_merged * 1.0 + issues_closed * 0.5


def _tier(score: float) -> str:
    if score >= 200:
        return "Core Maintainer"
    if score >= 80:
        return "Major Contributor"
    if score >= 20:
        return "Active Contributor"
    if score >= 5:
        return "Contributor"
    return "Casual"


class AnalyzeContributorsUseCase:
    def __init__(self, github: GitHubClient):
        self._github = github

    async def execute(
        self,
        top_n: int = 50,
        days: int = 90,
        progress: Optional[Progress] = None,
    ) -> dict:
        def emit(pct: int, msg: str):
            if progress:
                progress(pct, msg)

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)
        iso_cutoff = cutoff.strftime("%Y-%m-%d")
        repo = self._github.repo

        logger.info("Analysis: %dd window since %s", days, iso_cutoff)

        # ── Summary dicts — aggregated per page, no full lists stored ───────────
        login_to_meta:  dict[str, dict] = {}
        pr_summary:     dict[str, dict] = defaultdict(lambda: {"opened": 0, "merged": 0})
        bug_summary:    dict[str, int]  = defaultdict(int)
        issue_summary:  dict[str, int]  = defaultdict(int)

        def _capture_meta(user: dict) -> None:
            login = user.get("login", "")
            if login and login not in login_to_meta:
                login_to_meta[login] = {
                    "avatar_url": user.get("avatar_url", f"https://avatars.githubusercontent.com/{login}"),
                    "html_url":   user.get("html_url",   f"https://github.com/{login}"),
                }

        def _agg_item(items: list) -> None:
            """Single aggregator for combined PR + Issue Search results."""
            for item in items:
                user = item.get("user") or {}
                login = user.get("login", "")
                if not login or _is_bot(login, user.get("type", "")):
                    continue

                pr_data = item.get("pull_request")

                if pr_data:
                    # ── Pull Request ──────────────────────────────────────────
                    created = _parse_dt(item.get("created_at", ""))
                    if not created or created < cutoff:
                        continue
                    _capture_meta(user)
                    is_merged = bool(pr_data.get("merged_at"))
                    pr_summary[login]["opened"] += 1
                    if is_merged:
                        pr_summary[login]["merged"] += 1
                        if _is_bug_fix(item):
                            bug_summary[login] += 1

                elif item.get("state") == "closed":
                    # ── Closed Issue ──────────────────────────────────────────
                    closed_at = _parse_dt(item.get("closed_at", ""))
                    if not closed_at or closed_at < cutoff:
                        continue
                    _capture_meta(user)
                    issue_summary[login] += 1

        emit(5, "Fetching via Search API (≤10 pages)…")

        # One combined search query — max 10 pages = 1000 items.
        # PRs and issues are returned together; _agg_item splits by pull_request key.
        repo_info, _ = await asyncio.gather(
            self._github.get_repo_info(),
            self._github.search_issues_aggregate(
                f"repo:{repo} created:>={iso_cutoff}",
                _agg_item,
            ),
        )

        emit(70, (
            f"Processed {len(pr_summary)} PR authors · "
            f"{len(issue_summary)} issue closers · "
            f"{sum(bug_summary.values())} bug fixes"
        ))
        emit(80, "Computing scores…")

        all_logins = set(pr_summary) | set(bug_summary) | set(issue_summary)

        def _score(login: str) -> float:
            return _total_score(
                pr_summary.get(login, {}).get("merged", 0),
                bug_summary.get(login, 0),
                issue_summary.get(login, 0),
            )

        top_logins = sorted(all_logins, key=_score, reverse=True)[:top_n]

        results = []
        for rank, login in enumerate(top_logins, 1):
            meta        = login_to_meta.get(login, {})
            pr          = pr_summary.get(login, {})
            bug_fixes   = bug_summary.get(login, 0)
            iss_closed  = issue_summary.get(login, 0)
            score       = _score(login)
            bug_score   = round(bug_fixes * 3.0, 2)

            results.append({
                "rank":       rank,
                "login":      login,
                "avatar_url": meta.get("avatar_url", f"https://avatars.githubusercontent.com/{login}"),
                "html_url":   meta.get("html_url",   f"https://github.com/{login}"),
                "tier":       _tier(score),
                "impact": {
                    "total":             round(score, 2),
                    "bug_crusher_score": bug_score,
                },
                # bug_crusher — always present even if 0
                "bug_crusher": {
                    "bug_fixes":        bug_fixes,
                    "bug_crusher_score": bug_score,
                },
                # raw counts for table / charts
                "prs_opened":    pr.get("opened", 0),
                "prs_merged":    pr.get("merged", 0),
                "issues_closed": iss_closed,
            })

        emit(95, f"Ranked {len(results)} contributors — done!")

        return {
            "repo":            repo_info,
            "since":           iso_cutoff,   # top-level — frontend reads json.since
            "days":            days,          # top-level — frontend reads json.days
            "total_analyzed":  len(results),
            "contributors":    results,
        }
