from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    google_api_key: str = Field(default="")
    gemini_model_name: str = Field(default="gemma-4-31b-it")
    merchant_name: str = Field(default="Acme Mart")
    invoice_gst_rate_bps: int = Field(default=500)
    invoice_shipping_paise: int = Field(default=4000)
    invoice_free_shipping_min_paise: int = Field(default=50000)

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/merchant_ai"
    )
    offer_database_url: str | None = Field(default=None)
    postgres_user: str = Field(default="postgres")
    postgres_password: str = Field(default="postgres")
    postgres_db: str = Field(default="merchant_ai")

    redis_url: str = Field(default="redis://localhost:6379/0")
    offer_redis_url: str | None = Field(default=None)
    trusted_mandate_issuers: str = Field(default="issuer-a,issuer-b")
    allow_global_trusted_issuers_fallback: bool = Field(default=False)
    mandate_max_age_seconds: int = Field(default=300)

    gateway_host: str = Field(default="0.0.0.0")
    gateway_port: int = Field(default=8000)
    worker_url: str = Field(default="http://localhost:8001")
    agent_url: str = Field(default="http://localhost:8002")
    admin_host: str = Field(default="0.0.0.0")
    admin_port: int = Field(default=8003)
    offer_engine_url: str = Field(default="http://localhost:8004")
    auth_service_url: str = Field(default="http://localhost:8006")

    credential_encryption_key: str = Field(default="")
    jwt_secret: str = Field(default="dev-jwt-secret-change-me-please-32")
    jwt_expiry_minutes: int = Field(default=1440)
    default_merchant_id: str = Field(default="")

    reservation_ttl_seconds: int = Field(default=480)
    reservation_scan_interval_seconds: int = Field(default=30)
    reservation_service_url: str = Field(default="http://localhost:8005")
    payment_service_url: str = Field(default="http://localhost:8007")
    payment_log_service_url: str = Field(default="http://localhost:8008")
    kafka_bootstrap_servers: str = Field(default="localhost:9092")
    razorpay_mode: str = Field(default="fake")
    razorpay_webhook_secret: str = Field(default="")
    payment_link_ttl_seconds: int = Field(default=300)
    react_loop_max: int = Field(default=4)
    langchain_tracing_v2: bool = Field(default=False)
    langchain_api_key: str = Field(default="")
    langchain_project: str = Field(default="merchant-ai-phase2")

    rate_limit_per_minute: int = Field(default=60)
    catalog_cache_ttl_seconds: int = Field(default=600)
    session_ttl_seconds: int = Field(default=1800)
    reservation_hold_ttl_seconds: int = Field(default=300)

    log_level: str = Field(default="INFO")
    environment: str = Field(default="development")

    @property
    def trusted_mandate_issuers_list(self) -> list[str]:
        return [issuer.strip() for issuer in self.trusted_mandate_issuers.split(",") if issuer.strip()]

    @property
    def offer_database_url_resolved(self) -> str:
        return self.offer_database_url or self.database_url

    @property
    def offer_redis_url_resolved(self) -> str:
        return self.offer_redis_url or self.redis_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
