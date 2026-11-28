"""Settings read from the environment (defaults match docker-compose.yml and .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["debug", "info", "warning", "error", "critical"]


class Settings(BaseSettings):
    # hide_input_in_errors: a settings error is logged at startup, and its input holds every
    # value read from the environment, passwords and the session secret included.
    model_config = SettingsConfigDict(env_file=None, extra="ignore", hide_input_in_errors=True)

    app_env: Literal["development", "test", "production"] = "development"
    version: str = "0.1.0"

    # Databases. The API logs in as eos_app; migrations and seed as eos_owner;
    # the banner as eos_readonly (plan 3.15).
    database_url: str = "postgresql+asyncpg://eos_app:eos_app_dev_pw@db:5432/eos"
    owner_database_url: str = "postgresql+asyncpg://eos_owner:eos_owner_dev_pw@db:5432/eos"
    readonly_database_url: str = "postgresql+asyncpg://eos_readonly:eos_readonly_dev_pw@db:5432/eos"
    # Scratch database the rules report migrates, wipes and seeds on every run (Phase 3).
    report_database_url: str = "postgresql+asyncpg://eos_owner:eos_owner_dev_pw@db:5432/eos_report"

    # Connection pool (plan 3.12)
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout_s: float = 5.0
    db_pool_recycle_s: int = 1800
    db_statement_timeout_ms: int = 5000
    db_idle_in_tx_timeout_ms: int = 10000

    # Redis cache-aside read layer (layer L3, plan 3.14). Off: every read goes to Postgres.
    redis_url: str = "redis://:redis_dev_pw@redis:6379/0"
    cache_enabled: bool = True
    cache_ttl_team: int = 600  # team read models (keyed by the team's cache_version)
    cache_ttl_ref: int = 3600  # reference data (replaced on every seed)
    # Redis rate limits on writes (layer L4, plan 3.15; app/ratelimit.py). Off: no limits.
    rate_limit_enabled: bool = True

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

    # Session and request guards (plan 3.15)
    # Dev-only default (refused when APP_ENV=production, see the validator below).
    session_secret: str = "dev-only-session-secret-change-me-0000000000000000"  # noqa: S105
    session_max_age_s: int = 12 * 3600
    cookie_secure: bool = False  # true behind HTTPS; plain http://localhost can't use it
    # Browser origins allowed to write (comma-separated); compose derives the default.
    web_origin: str = "http://localhost:3000"
    max_body_bytes: int = 64 * 1024

    # Values printed by the startup banner
    public_host: str = "localhost"
    web_port: int = 3000
    api_port: int = 8000
    db_port: int = 5433
    logs_port: int = 8080
    redis_port: int = 6379
    # Process counts (layers L1 and L2, plan 3.11 and 3.13). The Dockerfiles read the same
    # variables; these copies only label the banner. The web ones are plain strings on
    # purpose: the web container checks them (start.sh), and a value only the web server
    # understands, such as WEB_INSTANCES=max, must never stop the API from starting.
    api_workers: int = 2
    web_runner: str = "pm2"
    web_instances: str = "2"

    @field_validator("log_level", mode="before")
    @classmethod
    def _lowercase_level(cls, value: object) -> object:
        # Accept INFO / Info as well; anything not in LogLevel fails with a clear message.
        return value.strip().lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _no_dev_secret_in_production(self) -> "Settings":
        if self.app_env == "production" and (
            self.session_secret.startswith("dev-only") or len(self.session_secret) < 32
        ):
            raise ValueError("SESSION_SECRET must be a real secret of 32+ characters in production")
        return self

    @property
    def web_origin_list(self) -> tuple[str, ...]:
        return tuple(o.strip().rstrip("/") for o in self.web_origin.split(",") if o.strip())

    @property
    def trusted_proxy_host_list(self) -> tuple[str, ...]:
        return tuple(h.strip() for h in self.trusted_proxy_hosts.split(",") if h.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
