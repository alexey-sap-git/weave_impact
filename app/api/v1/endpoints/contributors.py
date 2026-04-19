import asyncio
import json
import logging
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from app.application.use_cases.analyze_contributors import AnalyzeContributorsUseCase
from app.core.cache import get_cached, set_cached
from app.infrastructure.github.client import GitHubClient, GitHubRateLimitError

router = APIRouter(prefix="/contributors", tags=["contributors"])
logger = logging.getLogger(__name__)


def _make_use_case() -> AnalyzeContributorsUseCase:
    from app.core.config import get_settings
    settings = get_settings()
    client = GitHubClient(token=settings.github_token, repo=settings.github_repo)
    return AnalyzeContributorsUseCase(github=client)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/analyze/stream")
async def analyze_stream(
    top_n: Annotated[int, Query(ge=5, le=100)] = 50,
    days: Annotated[int, Query(ge=7, le=180)] = 90,
    refresh: bool = False,
):
    cache_key = f"analysis:{top_n}:{days}"

    async def event_stream() -> AsyncIterator[str]:
        if not refresh:
            cached = get_cached(cache_key)
            if cached is not None:
                yield _sse("progress", {"percent": 100, "message": "Loaded from cache"})
                yield _sse("result", {"source": "cache", **cached})
                return

        use_case = _make_use_case()
        queue: asyncio.Queue = asyncio.Queue()

        def on_progress(pct: int, msg: str):
            queue.put_nowait({"percent": pct, "message": msg})

        async def run():
            try:
                result = await use_case.execute(top_n=top_n, days=days, progress=on_progress)
                queue.put_nowait({"__result__": result})
            except Exception as e:
                queue.put_nowait({"__error__": str(e)})
            finally:
                await use_case._github.close()

        task = asyncio.create_task(run())

        try:
            while True:
                item = await asyncio.wait_for(queue.get(), timeout=60.0)
                if "__result__" in item:
                    result = item["__result__"]
                    set_cached(cache_key, result)
                    yield _sse("progress", {"percent": 100, "message": "Complete!"})
                    yield _sse("result", {"source": "live", **result})
                    break
                elif "__error__" in item:
                    yield _sse("error", {"message": item["__error__"]})
                    break
                else:
                    yield _sse("progress", item)
        except asyncio.TimeoutError:
            yield _sse("error", {"message": "Request timed out"})
        finally:
            task.cancel()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/analyze")
async def analyze(
    top_n: Annotated[int, Query(ge=5, le=100)] = 50,
    days: Annotated[int, Query(ge=7, le=180)] = 90,
    refresh: bool = False,
):
    cache_key = f"analysis:{top_n}:{days}"
    if not refresh:
        cached = get_cached(cache_key)
        if cached is not None:
            return JSONResponse(content={"source": "cache", **cached})

    use_case = _make_use_case()
    try:
        result = await use_case.execute(top_n=top_n, days=days)
        set_cached(cache_key, result)
        return JSONResponse(content={"source": "live", **result})
    except GitHubRateLimitError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        logger.exception("Analysis failed")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await use_case._github.close()


@router.get("/rate-limit")
async def rate_limit():
    from app.core.config import get_settings
    settings = get_settings()
    client = GitHubClient(token=settings.github_token, repo=settings.github_repo)
    try:
        return await client.get_rate_limit()
    finally:
        await client.close()
