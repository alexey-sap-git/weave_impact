from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    github_token: Optional[str] = None
    github_repo: str = "PostHog/posthog"
    cache_ttl_seconds: int = 3600

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
    )

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs) -> tuple:
        # .env takes priority over system env vars (local dev wins);
        # system env vars are the fallback so Render/cloud deployments work.
        return (kwargs["dotenv_settings"], kwargs["env_settings"])


def get_settings() -> Settings:
    return Settings()
