"""Typed configuration loaded independently of the terminal's working directory."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from psycopg.conninfo import make_conninfo
from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="forbid",
        hide_input_in_errors=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_mode: Literal["single_user_local"] = "single_user_local"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    storage_root: Path = Path(".local-data")

    db_host: str = "127.0.0.1"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "research"
    db_user: str = "research"
    db_password: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)

    llm_mode: Literal["mock", "live"] = "mock"
    llm_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    llm_base_url: AnyHttpUrl | None = None
    llm_screen_model: str = ""
    llm_research_model: str = ""
    llm_output_mode: Literal["json_schema", "function_calling", "json_prompt"] = "json_schema"
    llm_timeout_seconds: float = Field(default=120, gt=0)
    llm_max_input_bytes: int = Field(default=120000, ge=10000)
    llm_screen_max_output_tokens: int = Field(default=1024, gt=0)
    llm_research_max_output_tokens: int = Field(default=4096, gt=0)

    source_mode: Literal["mock", "live"] = "mock"
    mock_corpus_profile: Literal["minimal", "extended", "frozen"] = "minimal"
    frozen_corpus_path: Path | None = None
    research_strategy: Literal["B0", "B1", "B2", "A1", "A2"] = "B2"
    openalex_base_url: AnyHttpUrl = AnyHttpUrl("https://api.openalex.org")
    openalex_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    arxiv_base_url: AnyHttpUrl = AnyHttpUrl("https://export.arxiv.org/api/query")
    contact_email: str = ""
    http_user_agent: str = "AcademicWorkbench/0.1"
    enable_arxiv: bool = False
    planner_mode: Literal["legacy", "coverage"] = "legacy"
    max_research_rounds: int = Field(default=4, ge=1, le=8)
    max_actions_per_round: int = Field(default=6, ge=1, le=6)
    max_citation_neighbors: int = Field(default=15, ge=1, le=30)
    max_search_in_paper_calls_per_paper: int = Field(default=3, ge=1, le=6)
    embedding_mode: Literal["off", "mock", "live"] = "mock"
    embedding_dimensions: int = Field(default=256, ge=32, le=3072)
    semantic_scholar_base_url: AnyHttpUrl = AnyHttpUrl(
        "https://api.semanticscholar.org/graph/v1"
    )
    semantic_scholar_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    enable_semantic_scholar: bool = False

    mcp_enabled: bool = False
    mcp_allowed_hosts: list[str] = Field(default_factory=lambda: ["127.0.0.1:*", "localhost:*"])
    mcp_allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )

    max_candidates: int = Field(default=200, gt=0)
    max_screen_papers: int = Field(default=60, gt=0)
    max_deep_read_papers: int = Field(default=20, gt=0)
    max_source_requests: int = Field(default=20, gt=0)
    max_source_retries: int = Field(default=1, ge=0, le=3)
    read_concurrency: int = Field(default=3, gt=0, le=20)
    max_llm_calls: int = Field(default=150, gt=0)
    max_estimated_total_tokens: int = Field(default=400000, gt=0)
    max_research_seconds: int = Field(default=1200, gt=0)
    max_supplement_rounds: int = Field(default=1, ge=0)
    max_revision_rounds: int = Field(default=1, ge=0)
    max_model_retries: int = Field(default=1, ge=0, le=3)
    max_download_mb: int = Field(default=30, gt=0)
    max_pdf_pages: int = Field(default=120, gt=0)
    pdf_parse_timeout_seconds: float = Field(default=60, gt=0)
    max_chunks_per_paper: int = Field(default=12, gt=0)
    chunks_per_extraction_call: int = Field(default=4, gt=0)
    chunk_target_tokens: int = Field(default=700, gt=0)

    @model_validator(mode="before")
    @classmethod
    def normalize_empty_optional_url(cls, values: object) -> object:
        if isinstance(values, dict) and values.get("llm_base_url") == "":
            return {**values, "llm_base_url": None}
        return values

    @model_validator(mode="after")
    def validate_environment(self) -> Self:
        if not self.storage_root.is_absolute():
            self.storage_root = PROJECT_ROOT / self.storage_root
        self.storage_root = self.storage_root.resolve()
        if self.app_env == "test" and not self.db_name.endswith("_test"):
            raise ValueError("test environment requires a database name ending in _test")
        if self.llm_mode == "live":
            required = {
                "llm_api_key": bool(self.llm_api_key.get_secret_value().strip()),
                "llm_base_url": self.llm_base_url is not None,
                "llm_screen_model": bool(self.llm_screen_model.strip()),
                "llm_research_model": bool(self.llm_research_model.strip()),
            }
            missing = [name for name, present in required.items() if not present]
            if missing:
                raise ValueError("live mode requires fields: " + ", ".join(missing))
        return self

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )

    @property
    def checkpoint_dsn(self) -> str:
        return make_conninfo(
            host=self.db_host,
            port=self.db_port,
            dbname=self.db_name,
            user=self.db_user,
            password=self.db_password.get_secret_value(),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
