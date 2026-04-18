import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Callable, Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.github.com"
_PER_PAGE = 100
_MAX_CONCURRENT = 8  # stay under GitHub secondary rate limit

Progress = Callable[[int, str], None]


class GitHubRateLimitError(Exception):
    pass


def _make_client(token: Optional[str] = None) -> httpx.AsyncClient:
    headers: dict = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.AsyncClient(base_url=_BASE, headers=headers, timeout=30.0)


def _parse_last_page(link_header: str) -> Optional[int]:
    m = re.search(r'[?&]page=(\d+)[^>]*>;\s*rel="last"', link_header)
    return int(m.group(1)) if m else None


def _parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class GitHubClient:
    def __init__(self, token: Optional[str] = None, repo: str = "PostHog/posthog"):
        self.repo = repo
        self._token = token
        self._client = _make_client(token)
        self._anon_client: Optional[httpx.AsyncClient] = None
        self._sem = asyncio.Semaphore(_MAX_CONCURRENT)

    async def close(self):
        await self._client.aclose()
        if self._anon_client:
            await self._anon_client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> tuple[Any, dict]:
        async with self._sem:
            resp = await self._client.get(path, params=params)
            if resp.status_code == 401 and self._token:
                logger.warning("GitHub token invalid, falling back to unauthenticated")
                if self._anon_client is None:
                    self._anon_client = _make_client(None)
                resp = await self._anon_client.get(path, params=params)
            if resp.status_code in (403, 429):
                raise GitHubRateLimitError(
                    "GitHub API rate limit exceeded. Set a valid GITHUB_TOKEN for higher limits."
                )
            resp.raise_for_status()
            return resp.json(), dict(resp.headers)

    async def _get_json(self, path: str, params: dict | None = None) -> Any:
        data, _ = await self._get(path, params)
        return data

    async def _get_page(self, path: str, params: dict) -> tuple[list, Optional[int]]:
        data, headers = await self._get(path, params)
        if not isinstance(data, list):
            return [], None
        return data, _parse_last_page(headers.get("link", ""))

    async def _fetch_all_pages(
        self,
        path: str,
        base_params: dict,
        since: Optional[datetime] = None,
        progress_label: str = "",
    ) -> list:
        """Fetch page 1, discover total via Link header, gather rest concurrently."""
        page1, last_page = await self._get_page(path, {**base_params, "page": 1})
        logger.info("%s: page 1/%s fetched (%d items)", progress_label, last_page or "?", len(page1))

        if not last_page or last_page == 1:
            return self._filter_since(page1, since)

        remaining = await asyncio.gather(*[
            self._get_page(path, {**base_params, "page": p})
            for p in range(2, last_page + 1)
        ])
        logger.info("%s: all %d pages fetched", progress_label, last_page)

        all_items = page1[:]
        for items, _ in remaining:
            all_items.extend(items)

        return self._filter_since(all_items, since)

    def _filter_since(self, items: list, since: Optional[datetime]) -> list:
        if not since:
            return items
        return [
            i for i in items
            if not (dt := _parse_dt(i.get("created_at", ""))) or dt >= since
        ]

    async def get_contributors(self, max_pages: int = 3) -> list[dict]:
        base = {"per_page": _PER_PAGE, "anon": "false"}
        page1, last_page = await self._get_page(
            f"/repos/{self.repo}/contributors", {**base, "page": 1}
        )
        cap = min(last_page or 1, max_pages)
        if cap == 1:
            return page1
        rest = await asyncio.gather(*[
            self._get_page(f"/repos/{self.repo}/contributors", {**base, "page": p})
            for p in range(2, cap + 1)
        ])
        all_items = page1[:]
        for items, _ in rest:
            all_items.extend(items)
        return all_items

    async def get_pull_requests(self, since: datetime, state: str = "all") -> list[dict]:
        return await self._fetch_all_pages(
            f"/repos/{self.repo}/pulls",
            {"state": state, "per_page": _PER_PAGE, "sort": "created", "direction": "desc"},
            since=since,
            progress_label="pull_requests",
        )

    async def get_review_comments(self, since: datetime) -> list[dict]:
        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        return await self._fetch_all_pages(
            f"/repos/{self.repo}/pulls/comments",
            {"per_page": _PER_PAGE, "since": since_str,
             "sort": "created", "direction": "desc"},
            since=None,
            progress_label="review_comments",
        )

    async def get_repo_info(self) -> dict:
        return await self._get_json(f"/repos/{self.repo}")

    async def get_rate_limit(self) -> dict:
        return await self._get_json("/rate_limit")
