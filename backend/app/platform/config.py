"""Typed application settings loaded from environment / .env file.

`Settings` is constructed once per process via `get_settings()` and read
everywhere else. Nothing in the codebase should call `os.environ` directly.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class AppEnv(StrEnum):
    dev = "dev"
    staging = "staging"
    prod = "prod"


class LogFormat(StrEnum):
    console = "console"
    json = "json"


class SmsProviderKind(StrEnum):
    console = "console"
    messagepro = "messagepro"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Runtime
    app_env: AppEnv = AppEnv.dev
    app_debug: bool = True
    app_name: str = "iauto-backend"
    app_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    app_log_format: LogFormat = LogFormat.console

    # HTTP
    http_host: str = "0.0.0.0"  # noqa: S104 — dev default, bind behavior is deploy concern
    http_port: int = 8000
    # NoDecode stops pydantic-settings from trying to json-decode the raw env
    # string before the validator below splits it on commas.
    http_cors_origins: Annotated[list[AnyHttpUrl], NoDecode] = Field(default_factory=list)

    # Database
    database_url: PostgresDsn
    database_test_url: PostgresDsn | None = None
    database_pool_size: int = 10
    database_max_overflow: int = 10
    database_echo: bool = False

    # Redis
    redis_url: RedisDsn

    # Object storage (kept here even though we don't use it yet — reserving env keys)
    s3_endpoint_url: AnyHttpUrl | None = None
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    s3_bucket_media: str = "iauto-media"
    s3_use_path_style: bool = True

    # JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_ttl_days: int = 30
    jwt_issuer: str = "iauto"

    # Column-level encryption — both keys must be supplied, no dev defaults.
    #   app_data_key   — Fernet key (32 raw bytes, base64-urlsafe encoded,
    #                    44-char ASCII). Generate with:
    #                      python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    #   app_search_key — HMAC-SHA256 key (32 raw bytes, hex-encoded,
    #                    64-char ASCII). Generate with:
    #                      python -c "import secrets; print(secrets.token_hex(32))"
    # App fails to start if either is missing — see `app.platform.crypto`.
    app_data_key: str
    app_search_key: str

    # OTP
    otp_ttl_seconds: int = 300
    otp_length: int = 6
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60

    # SMS
    sms_provider: SmsProviderKind = SmsProviderKind.console
    messagepro_base_url: AnyHttpUrl | None = None
    messagepro_api_key: str = ""
    messagepro_sender: str = ""

    # Operator phone — pager destination for backend-side outage alerts
    # (e.g. smartcar.mn XYP gateway errors reported by mobile clients).
    # SMS body budget is 180 characters; see vehicles.alerts.
    operator_phone: str = ""
    xyp_alert_window_seconds: int = 900  # 15 min coalescing window

    # QPay v2 payment rail — see backend/docs/references/qpay_laravel_reference.md.
    # Sandbox base URL: https://merchant-sandbox.qpay.mn
    # Prod base URL:    https://merchant.qpay.mn
    qpay_base_url: AnyHttpUrl | None = None
    qpay_username: str = ""
    qpay_password: str = ""
    qpay_invoice_code: str = ""
    qpay_callback_url: str = ""
    # HMAC secret used to verify QPay's webhook payload. The QPay v2 callback
    # signing scheme is documented at https://developer.qpay.mn/ — until we
    # confirm it via context7, the receiver runs in "log-only" mode where
    # `signature_ok` is recorded but never blocks the status flip.
    qpay_callback_secret: str = ""

    # Admin panel (section H — not mounted yet)
    admin_panel_enabled: bool = False
    admin_panel_secret: str = ""

    # ---- AI Mechanic (Phase 3) --------------------------------------------
    # Gemini API key — routes through OpenAI Agents SDK's LiteLLM extension
    # via `LitellmModel(model="gemini/gemini-3-flash-preview", api_key=...)`.
    # The key shipped via env. Rotate before any production deploy — chat
    # leakage rule applies (same as MessagePro / QPay credentials).
    gemini_api_key: str = ""
    ai_mechanic_model: str = "gemini/gemini-3-flash-preview"
    ai_mechanic_embedding_model: str = "text-embedding-3-small"
    # Optional separate OpenAI key for embeddings — falls back to gemini_api_key
    # in dev. Phase 5 swaps to a Gemini-native embedding once available.
    openai_api_key: str = ""
    # Daily request cap per user — Redis key `ai:rl:{user_id}:{yyyy-mm-dd}`
    # INCR'd on each agent run. 30 requests/day is generous enough for
    # heavy use without risking a billing shock during phase 3 dogfooding.
    ai_daily_request_limit_per_user: int = 30
    # Live LLM calls in the test suite are gated. Default off so CI never
    # burns tokens; flip to `1` in `backend/.env` to run live smoke tests.
    ai_live_tests: bool = False
    # Daily AI spend budget in micro-MNT. The cost-alert cron sums the
    # trailing 24h of `ai_spend_events` and pages OPERATOR_PHONE if the
    # total exceeds this value. 0 disables the alert (cron still logs
    # the daily summary). Default 5000 MNT/day = 5_000_000_000 micro.
    ai_daily_spend_budget_micro_mnt: int = 5_000_000_000

    # Observability
    sentry_dsn: str | None = None
    otel_exporter_otlp_endpoint: str | None = None

    # ---- derived / helpers -------------------------------------------------

    @field_validator("http_cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @property
    def database_url_str(self) -> str:
        return str(self.database_url)

    @property
    def database_test_url_str(self) -> str | None:
        return str(self.database_test_url) if self.database_test_url else None

    @property
    def redis_url_str(self) -> str:
        return str(self.redis_url)

    @property
    def is_prod(self) -> bool:
        return self.app_env == AppEnv.prod


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
