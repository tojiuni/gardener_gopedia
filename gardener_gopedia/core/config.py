from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# gardener_gopedia/core/config.py -> parents[2] == project root (where .env lives)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GARDENER_",
        env_file=str(_REPO_ROOT / ".env"),
        extra="ignore",
    )

    database_url: str = ""
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

    # Langfuse (self-host): traces, scores, usage/cost KPIs
    langfuse_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("GARDENER_LANGFUSE_ENABLED", "LANGFUSE_ENABLED"),
    )
    """When true and keys+host are set, export eval traces to Langfuse after each run."""
    langfuse_host: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GARDENER_LANGFUSE_HOST",
            "LANGFUSE_BASE_URL",
            "LANGFUSE_HOST",
        ),
    )
    """SDK/API base URL, e.g. http://127.0.0.1:3000"""
    langfuse_public_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GARDENER_LANGFUSE_PUBLIC_KEY",
            "LANGFUSE_PUBLIC_KEY",
        ),
    )
    langfuse_secret_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GARDENER_LANGFUSE_SECRET_KEY",
            "LANGFUSE_SECRET_KEY",
        ),
    )

    # AI label routing (Silver → auto_accept vs human queue)
    label_auto_accept_single_min_confidence: float = 0.9
    label_consensus_min_models: int = 2
    label_consensus_min_confidence: float = 0.7

    # Qrel resolution (target_data → l3_id/doc_id via Gopedia search)
    qrel_resolve_search_detail: str = "full"  # was "standard" — need surrounding_context for substring match
    qrel_resolve_min_vector_score: float = 0.25
    qrel_resolve_min_combined_score: float = 0.35
    qrel_resolve_max_hits_to_score: int = 20
    # When True, hits whose surrounding_context contains the target_data
    # excerpt verbatim get an override score that dominates vector ranking.
    # Counters the v0.22.x regression where Q&A injection's question-text
    # snippets fooled the resolver into picking wrong chunks.
    qrel_resolve_substring_override: bool = True
    qrel_resolve_substring_min_len: int = 40  # excerpt must be ≥40 chars to use substring signal

    # Compose Postgres (no GARDENER_ prefix — matches typical docker .env)
    postgres_user: str | None = Field(default=None, validation_alias="POSTGRES_USER")
    postgres_password: str | None = Field(default=None, validation_alias="POSTGRES_PASSWORD")
    postgres_host: str | None = Field(default=None, validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, validation_alias="POSTGRES_PORT")
    postgres_db: str | None = Field(default=None, validation_alias="POSTGRES_DB")
    postgres_sslmode: str | None = Field(default="disable", validation_alias="POSTGRES_SSLMODE")

    @model_validator(mode="after")
    def _resolve_database_url(self):
        """PostgreSQL only: full URL or POSTGRES_* components."""
        url = (self.database_url or "").strip()
        if not url:
            u = self.postgres_user
            p = self.postgres_password
            h = self.postgres_host
            d = self.postgres_db
            if u and p is not None and h and d:
                pw = quote_plus(p)
                ssl = (self.postgres_sslmode or "disable").strip() or "disable"
                port = int(self.postgres_port or 5432)
                self.database_url = (
                    f"postgresql+psycopg://{u}:{pw}@{h}:{port}/{d}?sslmode={ssl}"
                )
            else:
                raise ValueError(
                    "Gardener requires PostgreSQL. Set GARDENER_DATABASE_URL to a "
                    "postgresql+psycopg://… connection string, or set POSTGRES_USER, "
                    "POSTGRES_PASSWORD, POSTGRES_HOST, and POSTGRES_DB."
                )
        elif not url.startswith("postgresql"):
            raise ValueError(
                "Gardener requires PostgreSQL; GARDENER_DATABASE_URL must use the "
                "postgresql scheme (refusing non-PostgreSQL URL)."
            )
        return self

@lru_cache
def get_settings() -> Settings:
    # Ensure values from project-root ".env" are also present in os.environ for places that
    # read directly from environment variables (e.g., Ragas/OpenAI).
    # Without this, Pydantic can populate Settings but os.environ may stay empty.
    load_dotenv(dotenv_path=_REPO_ROOT / ".env", override=False)
    return Settings()
