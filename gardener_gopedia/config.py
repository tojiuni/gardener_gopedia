from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GARDENER_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./gardener.db"
    """When using PostgreSQL with a dedicated schema, set e.g. gardener_eval and create the schema in DB."""
    postgres_schema: str | None = None
    gopedia_base_url: str = "http://127.0.0.1:18787"
    default_top_k: int = 10
    default_query_timeout_s: float = 15.0
    default_ingest_poll_interval_s: float = 1.0
    default_ingest_poll_timeout_s: float = 3600.0
    gopedia_search_detail: str | None = None
    gopedia_search_fields: str | None = None
    gopedia_search_retryable_max_attempts: int = 3
    api_host: str = "0.0.0.0"
    api_port: int = 18880

    # Ragas / LLM evaluation
    ragas_enabled: bool = False
    ragas_answer_metrics: bool = False
    ragas_openai_model: str = "gpt-4o-mini"
    ragas_embedding_model: str = "text-embedding-3-small"
    ragas_batch_size: int = 4
    ragas_show_progress: bool = False

    # Phoenix OTLP HTTP exporter (self-host: docker-compose.phoenix.yml)
    phoenix_otlp_endpoint: str | None = None
    phoenix_service_name: str = "gardener-gopedia-eval"


@lru_cache
def get_settings() -> Settings:
    return Settings()
