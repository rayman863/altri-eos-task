"""Settings read from the environment (defaults match docker-compose.yml and .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["debug", "info", "warning", "error", "critical"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    version: str = "0.1.0"

    # Databases. The API logs in as eos_app; migrations and seed as eos_owner;
    # the banner as eos_readonly (plan 3.15).
    database_url: str = "postgresql+asyncpg://eos_app:eos_app_dev_pw@db:5432/eos"
    owner_database_url: str = "postgresql+asyncpg://eos_owner:eos_owner_dev_pw@db:5432/eos"
    readonly_database_url: str = "postgresql+asyncpg://eos_readonly:eos_readonly_dev_pw@db:5432/eos"

    # Connection pool (plan 3.12)
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout_s: float = 5.0
    db_pool_recycle_s: int = 1800
    db_statement_timeout_ms: int = 5000
    db_idle_in_tx_timeout_ms: int = 10000

    # Seed file (compose mounts ./seed at /seed)
    seed_path: str = "/seed/seed.json"

    # Clock (plan 3.2)
    app_now: str = "2026-11-11T15:00:00Z"
    app_clock_mode: Literal["ticking", "frozen"] = "ticking"

    # Logging (plan 3.10)
    log_level: LogLevel = "info"
    log_payloads: bool = True
    log_body_limit: int = 8192
    # Only these peers may set X-Request-ID / X-Forwarded-For (comma-separated host
    # names or IPs; default: the Next.js server's compose service).
    trusted_proxy_hosts: str = "web"

    # Values printed by the startup banner
    public_host: str = "localhost"
    web_port: int = 3000
    api_port: int = 8000
    db_port: int = 5433
    logs_port: int = 8080
    api_workers: int = 1

    @field_validator("log_level", mode="before")
    @classmethod
    def _lowercase_level(cls, value: object) -> object:
        # Accept INFO / Info as well; anything not in LogLevel fails with a clear message.
        return value.strip().lower() if isinstance(value, str) else value

    @property
    def trusted_proxy_host_list(self) -> tuple[str, ...]:
        return tuple(h.strip() for h in self.trusted_proxy_hosts.split(",") if h.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
