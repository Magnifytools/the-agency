from __future__ import annotations
import logging
import os
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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
    REDIS_URL: Optional[str] = None
    SECRET_KEY: str = DEFAULT_SECRET_KEY
    # Dedicated vault encryption key. When unset, the vault falls back to
    # SECRET_KEY (back-compat). Set this so JWT signing key can rotate
    # independently of the credential vault.
    VAULT_KEY: Optional[str] = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    ALGORITHM: str = "HS256"
    AUTH_COOKIE_NAME: str = "agency_access_token"
    CSRF_COOKIE_NAME: str = "agency_csrf_token"
    AUTH_COOKIE_SECURE: bool = _is_production()
    AUTH_COOKIE_DOMAIN: Optional[str] = None
    AUTH_COOKIE_SAMESITE: str = "lax"
    AUTH_COOKIE_PATH: str = "/"
    DISCORD_WEBHOOK_URL: Optional[str] = None
    DISCORD_OWNER_USER_ID: Optional[str] = None
    # Enable only after older direct-sender instances have drained.
    DELIVERY_WORKER_ENABLED: bool = False
    SCHEDULED_COMMUNICATIONS_ENABLED: bool = False
    INCIDENTS_ENABLED: bool = False
    ANTHROPIC_API_KEY: Optional[str] = None
    HOLDED_API_KEY: Optional[str] = None
    DEFAULT_HOURLY_RATE: float = 40.0
    ENGINE_API_URL: Optional[str] = None
    ENGINE_SERVICE_KEY: Optional[str] = None
    ENGINE_SYNC_INTERVAL_HOURS: int = 6
    ENGINE_SYNC_ENABLED: bool = True
    ENGINE_FRONTEND_URL: Optional[str] = None
    # Semáforo SEO: incidencia cuando los clics de 30 días caen este % o más
    # frente a los 30 anteriores, si el periodo anterior llegaba a este mínimo.
    SEO_DROP_ALERT_PCT: float = 20.0
    SEO_DROP_MIN_CLICKS: int = 100
    # Webs: disponibilidad (job ``uptime``, lock 15). Apagado por defecto: en
    # Railway se enciende con UPTIME_ENABLED=true. Umbrales en
    # backend/services/web/uptime.py (CLAUDE.md, "Webs: disponibilidad").
    UPTIME_ENABLED: bool = False
    UPTIME_INTERVAL_SECONDS: int = 300
    UPTIME_RECHECK_SECONDS: int = 60
    UPTIME_FAILURES_TO_ALERT: int = 2
    UPTIME_RECOVERIES_TO_CLOSE: int = 2
    UPTIME_BLOCKED_ALERT_MINUTES: int = 60
    # Canario de conectividad: si NINGUNA responde, el problema es nuestro y no
    # se mira nada en ese ciclo. Separadas por comas.
    UPTIME_CANARY_URLS: str = "https://www.google.com/generate_204,https://www.cloudflare.com/cdn-cgi/trace"
    # Webs: vigilancia de cambios (job ``web_sweep``, lock 16). Apagado por
    # defecto: sin él, ni el barrido diario ni "Comprobar ahora" se ejecutan.
    # El diario de cada cliente arranca a partir de esta hora (Europe/Madrid),
    # un cliente por ciclo, en los días de su calendario.
    WEB_SWEEP_ENABLED: bool = False
    WEB_SWEEP_LOCAL_TIME: str = "06:30"
    # Webs: salud diaria (job ``web_health``, lock 18). No tiene interruptor
    # propio: la caducidad de certificado y dominio corre con UPTIME_ENABLED y
    # robots.txt + sitemap con WEB_SWEEP_ENABLED (backend/services/web/health.py).
    # Revisión tras publicar (job ``publish_checks``, lock 19): mira el enlace de
    # cada tarea completada. Apagada por defecto; en Railway, PUBLISH_CHECK_ENABLED=true.
    PUBLISH_CHECK_ENABLED: bool = False
    VOYAGE_API_KEY: Optional[str] = None
    AGENCY_TIMEZONE: str = "Europe/Madrid"

    # Google Calendar OAuth2
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: str = "https://agency.magnifytools.com/api/calendar/callback"
    # Search Console usa el mismo cliente OAuth con su propio callback.
    GSC_REDIRECT_URI: str = "https://agency.magnifytools.com/api/gsc/callback"

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

        cookie_samesite = self.AUTH_COOKIE_SAMESITE.lower()
        if cookie_samesite not in {"lax", "strict", "none"}:
            raise ValueError("AUTH_COOKIE_SAMESITE must be one of: lax, strict, none")
        self.AUTH_COOKIE_SAMESITE = cookie_samesite
        if _is_production() and not self.AUTH_COOKIE_SECURE:
            raise ValueError("AUTH_COOKIE_SECURE must be true in production")
        if self.AUTH_COOKIE_SAMESITE == "none" and not self.AUTH_COOKIE_SECURE:
            logging.warning("AUTH_COOKIE_SAMESITE=none usually requires AUTH_COOKIE_SECURE=true")

        try:
            ZoneInfo(self.AGENCY_TIMEZONE)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown AGENCY_TIMEZONE: {self.AGENCY_TIMEZONE}") from exc

        return self


settings = Settings()
