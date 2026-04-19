# Weave Impact

A self-hosted contributor analytics dashboard that measures **impact** across a GitHub repository — who ships the most, fixes the most bugs, and closes the most issues — surfaced in a real-time dark-mode dashboard.

Built with FastAPI, async parallel fetching from the GitHub Search API, and a single-page dark-mode dashboard.

---

## How contributors are scored

### Impact Score

```
impact = bug_fixes × 3.0 + prs_merged × 1.0 + issues_closed × 0.5
```

| Signal | Weight |
|---|---|
| Bug fix merged | × 3.0 |
| PR merged | × 1.0 |
| Issue closed | × 0.5 |

### Bug Crusher

A merged PR counts as a bug fix when **either** condition is true:

- The PR carries a **`bug`** label
- The PR title starts with `fix:` or `fix!`, or contains the word `fix`

**Bots are excluded.** Accounts with a `[bot]` suffix, type `Bot`, or known automation names (dependabot, renovate, github-actions, snyk-bot, codecov…) are filtered at every data ingestion point.

### Tiers

| Tier | Threshold |
|---|---|
| Core Maintainer | ≥ 200 pts |
| Major Contributor | ≥ 80 pts |
| Active Contributor | ≥ 20 pts |
| Contributor | ≥ 5 pts |
| Casual | < 5 pts |

---

## Architecture

```
weave_impact/
├── app/
│   ├── api/v1/endpoints/      # FastAPI route handlers (SSE stream + JSON)
│   ├── application/use_cases/ # Orchestration: fetch → aggregate → score
│   ├── infrastructure/github/ # Async GitHub Search API client
│   ├── core/                  # Config (pydantic-settings), in-memory TTL cache
│   └── presentation/static/  # Single-page dashboard (vanilla JS + Chart.js)
├── run.py                     # Entry point — reads $PORT for Render compatibility
├── .env.example
└── requirements.txt
```

---

## GitHub API usage

The service makes **at most 11 requests** per analysis run:

| Request | Purpose |
|---|---|
| `GET /repos/:owner/:repo` | Repo metadata (stars, language) |
| `GET /search/issues?q=repo:…+created:>=DATE` (≤ 10 pages) | PRs and issues in one combined query |

The Search API returns both PRs (identified by the presence of a `pull_request` key) and issues in a single paginated response. This is capped at **10 pages / 1 000 items** — GitHub's hard Search API limit.

All pages are fetched concurrently with `asyncio.gather` under `asyncio.Semaphore(5)`. For result sets over 2 000 items the client falls back to sequential batches of 5 pages to stay within memory limits.

Results are cached in memory for 1 hour (`cachetools.TTLCache`). A **Refresh** button forces a live re-fetch.

---

## Requirements

- Python 3.11+
- A GitHub personal access token (classic, `public_repo` scope is enough for public repos)

---

## Setup

**1. Clone and install dependencies**

```bash
git clone https://github.com/your-org/weave_impact
cd weave_impact
pip install -r requirements.txt
```

**2. Create a `.env` file**

```bash
cp .env.example .env
```

Edit `.env`:

```env
GITHUB_TOKEN=ghp_your_token_here
GITHUB_REPO=PostHog/posthog
CACHE_TTL_SECONDS=3600
```

`GITHUB_TOKEN` is optional but strongly recommended. Without it, GitHub's unauthenticated rate limit (60 req/hour) will be exhausted quickly. With a token the limit is 5 000 req/hour.

To generate a token: GitHub → Settings → Developer settings → Personal access tokens → Generate new token → select `public_repo`.

**3. Run**

```bash
python run.py
```

Open [http://localhost:8000](http://localhost:8000).

The server reads the `PORT` environment variable automatically, so it works on Render and other PaaS platforms without changes.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `GITHUB_TOKEN` | _(empty)_ | GitHub PAT for authenticated API calls |
| `GITHUB_REPO` | `PostHog/posthog` | Repository to analyse (`owner/repo`) |
| `CACHE_TTL_SECONDS` | `3600` | How long to cache analysis results (seconds) |

---

## Dashboard features

- **Days selector** — analyse the last 30, 90, or 180 days
- **Top-N selector** — show the top 25, 50, or 100 contributors
- **Live progress bar** — real-time fetch progress streamed via Server-Sent Events
- **Cache badge** — shows whether the current result is live or served from cache
- **Tier filter pills** — click to filter the table by contributor tier
- **Search** — instant filter by GitHub login
- **Sortable columns** — click any column header to sort
- **Charts** — top-10 impact score bar, top-10 bug fixes bar, tier distribution donut
- **Pagination** — 20 rows per page

### Table columns

| Column | Description |
|---|---|
| Impact | Total weighted score |
| PRs Merged | Count of merged pull requests |
| 🐛 Bug Fixes | Merged PRs matching the bug-fix criteria |

---

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/contributors/analyze/stream` | SSE stream with progress + result |
| `GET` | `/api/v1/contributors/analyze` | Plain JSON result |
| `GET` | `/api/v1/contributors/rate-limit` | GitHub rate limit status |
| `GET` | `/health` | Health check |

Query parameters:

| Parameter | Type | Range | Default |
|---|---|---|---|
| `top_n` | int | 5–100 | 50 |
| `days` | int | 7–180 | 90 |
| `refresh` | bool | — | false |

### Response shape (per contributor)

```json
{
  "rank": 1,
  "login": "username",
  "avatar_url": "https://avatars.githubusercontent.com/...",
  "html_url": "https://github.com/username",
  "tier": "Active Contributor",
  "impact": {
    "total": 21.0,
    "bug_crusher_score": 9.0
  },
  "bug_crusher": {
    "bug_fixes": 3,
    "bug_crusher_score": 9.0
  },
  "prs_opened": 8,
  "prs_merged": 6,
  "issues_closed": 2
}
```

---

## Changing the target repository

Update `GITHUB_REPO` in `.env`:

```env
GITHUB_REPO=facebook/react
```

Restart the server. The in-memory cache is cleared automatically on restart.

---

## License

MIT
