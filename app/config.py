"""Settings from environment variables (or a local .env). One cached instance per process."""
from __future__ import annotations

import logging
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_KEY = "dev-only-insecure-secret-change-me"

log = logging.getLogger("loomledger.config")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/loomledger"
    SECRET_KEY: str = DEV_SECRET_KEY
    TOKEN_TTL_HOURS: int = 12
    CORS_ORIGINS: str = "http://localhost:5173"   # comma-separated

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.SECRET_KEY == DEV_SECRET_KEY:
        log.warning("SECRET_KEY is the development default; set SECRET_KEY before deploying")
    return settings
