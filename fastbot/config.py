from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    fastbot_host: str = "127.0.0.1"
    fastbot_port: int = 5012
    fastbot_database: Path = Path(".data/fastbot.db")
    fastbot_single_user: bool = True
    fastbot_session_secret: str = "dev-only-secret"
    fastbot_computer_backend: str = "docker"
    fastbot_workspace_root: Path = Path(".data/workspaces")
    model_provider: str = "xai"
    model_name: str = "grok-4-1-fast-reasoning"
    xai_api_key: str = ""
    xai_base_url: str = "https://api.x.ai/v1"


@lru_cache
def settings() -> Settings:
    return Settings()
