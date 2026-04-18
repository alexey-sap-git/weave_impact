# Weave Impact

A self-hosted contributor analytics dashboard that measures **review influence** across a GitHub repository. Instead of counting commits or lines of code, Weave Impact surfaces the engineers who elevate the quality of everyone else's work through thoughtful, substantive code review.

Built with FastAPI, async parallel fetching from the GitHub REST API, and a single-page dark-mode dashboard.

---

## How contributors are scored

Weave Impact uses a single scoring axis called **Knowledge Sharer**, composed of two signals:

| Signal | Points |
|---|---|
| Meaningful review comment (> 30 chars, non-trivial) | × 1.5 |
| Cross-subsystem PR review (files in 2+ top-level dirs) | × 5.0 |

**What "meaningful" means:** a comment longer than 30 characters that is not a stock phrase like `LGTM`, `+1`, `looks good`, `approved`, or similar. The threshold filters rubber-stamp approvals so only comments that carry actual substance — a bug spotted, an alternative proposed, an edge case raised — contribute to the score.

**What "cross-subsystem" means:** when a reviewer leaves comments on files that span two or more top-level directories in the same PR (e.g. both `frontend/` and `posthog/`), it signals broad architectural awareness. This is rare and highly valuable, so it carries the largest weight.

**Self-reviews are excluded.** A PR author's own comments on their PR do not count.

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
│   ├── domain/
│   │   ├── contributors/      # Core entities (Contributor, KnowledgeSharerActivity…)
│   │   └── scoring/           # ImpactScore, ImpactScoringService
│   ├── infrastructure/github/ # Async GitHub REST client, parallel pagination
│   ├── core/                  # Config (pydantic-settings), in-memory cache
│   └── presentation/static/  # Single-page dashboard (vanilla JS + Chart.js)
├── run.py                     # Entry point
├── .env.example
└── requirements.txt
```

The design follows Domain-Driven Design layering: the domain layer has no external dependencies, the infrastructure layer implements GitHub I/O, and the application layer wires them together.

---

## GitHub API usage

The service calls three GitHub REST v3 endpoints per analysis run:

| Endpoint | Purpose |
|---|---|
| `GET /repos/:owner/:repo/contributors` | Avatar URLs and login metadata |
| `GET /repos/:owner/:repo/pulls` | PR authors, merge status |
| `GET /repos/:owner/:repo/pulls/comments` | Review comment bodies and file paths |

Page 1 of each endpoint is fetched first to read the `Link` header and discover the total page count. All remaining pages are then fetched concurrently with `asyncio.gather`. A semaphore (`asyncio.Semaphore(8)`) keeps concurrent requests under GitHub's secondary rate limit.

Results are cached in memory for 1 hour (`cachetools.TTLCache`). The dashboard serves cached data instantly on repeat visits; a **Refresh** button forces a live re-fetch.

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

`GITHUB_TOKEN` is optional but strongly recommended. Without it, GitHub's unauthenticated rate limit (60 req/hour) will be exhausted quickly on large repositories. With a token the limit is 5 000 req/hour.

To generate a token: GitHub → Settings → Developer settings → Personal access tokens → Generate new token → select `public_repo`.

**3. Run**

```bash
python run.py
```

Open [http://localhost:8000](http://localhost:8000).

---

## Configuration

All settings are read exclusively from the `.env` file. System environment variables are intentionally ignored to avoid token conflicts when running alongside other tools.

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
- **Charts** — top-10 impact bar chart, score breakdown, tier distribution donut
- **Pagination** — 20 rows per page

---

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/contributors/analyze/stream` | SSE stream with progress + result |
| `GET` | `/api/v1/contributors/analyze` | Plain JSON result |
| `GET` | `/api/v1/contributors/rate-limit` | GitHub rate limit status |
| `GET` | `/health` | Health check |

Query parameters for both analyze endpoints:

| Parameter | Type | Range | Default |
|---|---|---|---|
| `top_n` | int | 5–100 | 50 |
| `days` | int | 7–180 | 90 |
| `refresh` | bool | — | false |

---

## Changing the target repository

Update `GITHUB_REPO` in `.env` to any public (or private, if your token has access) repository:

```env
GITHUB_REPO=facebook/react
```

Restart the server. The cache is in-memory so old results are automatically replaced on the next request.

---

## License

MIT
