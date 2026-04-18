import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Weave Impact",
    description="Contributor impact analysis for PostHog/posthog",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

_STATIC = Path(__file__).parent / "presentation" / "static"
app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.on_event("startup")
async def _startup():
    from app.core.config import get_settings, _ENV_FILE
    s = get_settings()
    token_info = f"YES ({s.github_token[:10]}...)" if s.github_token else "NO"
    logger.info(".env: %s (exists=%s)", _ENV_FILE, _ENV_FILE.exists())
    logger.info("Token loaded: %s | Repo: %s", token_info, s.github_repo)


@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(_STATIC / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}
