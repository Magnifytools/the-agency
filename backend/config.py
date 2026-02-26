from __future__ import annotations
import logging
import os
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings
from pathlib import Path


DEFAULT_SECRET_KEY = "dev-secret-change-in-production"


def _is_production() -> bool:
    """Detect production environment via Railway or explicit ENV var."""
    return bool(
        os.environ.get("RAILWAY_ENVIRONMENT")
        or os.environ.get("RAILWAY_PROJECT_ID")
        or os.environ.get("PRODUCTION")
    )


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://agency:agency@localhost:5432/the_agency"
    SECRET_KEY: str = DEFAULT_SECRET_KEY
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    ALGORITHM: str = "HS256"
    DISCORD_WEBHOOK_URL: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    HOLDED_API_KEY: Optional[str] = None
    DEFAULT_HOURLY_RATE: float = 40.0

    model_config = {"env_file": str(Path(__file__).resolve().parent.parent / ".env")}

    @model_validator(mode="after")
    def _validate_secret_key(self) -> "Settings":
        if self.SECRET_KEY == DEFAULT_SECRET_KEY:
            if _is_production():
                raise ValueError(
                    "FATAL: SECRET_KEY is using the default value in a production environment. "
                    "Set a strong SECRET_KEY (min 32 chars) in your environment variables."
                )
            logging.warning(
                "SECRET_KEY está usando el valor por defecto. "
                "Configura SECRET_KEY en .env para producción."
            )
        elif _is_production() and len(self.SECRET_KEY) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters in production. "
                f"Current length: {len(self.SECRET_KEY)}"
            )
        return self


settings = Settings()
