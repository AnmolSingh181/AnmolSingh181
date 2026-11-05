"""Application settings. All secrets come from environment variables (see .env.example)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # "production", "development", "demo" or "test". Demo records are only visible when APP_ENV=demo.
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/plastic_intel"
    cors_origins: str = "http://localhost:3000"

    # Auth: "local" (users table + JWT issued by this API) or "supabase" (verify Supabase JWTs).
    auth_mode: str = "local"
    jwt_secret: str = "change-me-in-production"
    jwt_expiry_hours: int = 24
    supabase_url: str | None = None
    supabase_jwt_secret: str | None = None  # legacy HS256 secret
    supabase_jwks_url: str | None = None    # asymmetric signing keys

    # AI
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    # off | fallback (only when rules are inconclusive) | always
    ai_classification_mode: str = "fallback"
    ai_max_input_chars: int = 12000
    ai_monthly_budget_usd: float = 10.0

    # Crawling etiquette
    crawler_user_agent: str = "PlasticIntelBot/1.0 (+contact: admin@yourcompany.com)"
    crawler_min_delay_seconds: float = 3.0
    crawler_timeout_seconds: float = 20.0
    crawler_max_pages_per_site: int = 8
    playwright_enabled: bool = False

    # Search APIs used for discovery (any one is enough)
    brave_search_api_key: str | None = None
    serper_api_key: str | None = None
    serpapi_api_key: str | None = None
    google_cse_api_key: str | None = None
    google_cse_cx: str | None = None

    # Trade data
    census_api_key: str | None = None
    comtrade_api_key: str | None = None
    importyeti_api_key: str | None = None
    volza_api_key: str | None = None
    panjiva_api_key: str | None = None
    tradedata_pro_api_key: str | None = None
    kompass_api_key: str | None = None

    # Market prices
    fred_api_key: str | None = None   # optional: FRED works key-free via its public CSV download
    dce_api_key: str | None = None    # Dalian Commodity Exchange data API
    dce_secret: str | None = None

    # Enrichment / verification
    apollo_api_key: str | None = None
    zerobounce_api_key: str | None = None

    # Alerts (e.g. an n8n webhook)
    alert_webhook_url: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def show_demo_data(self) -> bool:
        return self.app_env == "demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
