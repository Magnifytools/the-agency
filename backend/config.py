from __future__ import annotations
from typing import Optional

from pydantic_settings import BaseSettings
from pathlib import Path


DEFAULT_SECRET_KEY = "dev-secret-change-in-production"


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://agency:agency@localhost:5432/the_agency"
    SECRET_KEY: str = DEFAULT_SECRET_KEY
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    ALGORITHM: str = "HS256"
    DISCORD_WEBHOOK_URL: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None

    model_config = {"env_file": str(Path(__file__).resolve().parent.parent / ".env")}


settings = Settings()
