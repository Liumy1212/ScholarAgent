from functools import cached_property
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime configuration loaded only from process environment variables."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=None,
        extra="ignore",
        validate_default=True,
    )

    deepseek_api_key: SecretStr = Field(default=SecretStr(""), alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com",
        alias="DEEPSEEK_BASE_URL",
    )
    deepseek_model: str = Field(default="deepseek-v4-flash", alias="DEEPSEEK_MODEL")
    deepseek_timeout_seconds: float = Field(
        default=90.0,
        alias="AIRESEARCHER_DEEPSEEK_TIMEOUT_SECONDS",
        gt=0,
        le=300,
    )

    db_host: str = Field(default="127.0.0.1", alias="AIRESEARCHER_DB_HOST")
    db_port: int = Field(default=3306, alias="AIRESEARCHER_DB_PORT", ge=1, le=65535)
    db_name: str = Field(default="airesearcher_agent", alias="AIRESEARCHER_DB_NAME")
    db_user: str = Field(default="airesearcher", alias="AIRESEARCHER_DB_USER")
    db_password: SecretStr = Field(default=SecretStr(""), alias="AIRESEARCHER_DB_PASSWORD")

    qdrant_url: str = Field(default="http://127.0.0.1:6333", alias="AIRESEARCHER_QDRANT_URL")
    qdrant_collection: str = Field(
        default="airesearcher_chunks_v1",
        alias="AIRESEARCHER_QDRANT_COLLECTION",
        min_length=1,
        max_length=255,
    )
    qdrant_timeout_seconds: float = Field(
        default=30.0,
        alias="AIRESEARCHER_QDRANT_TIMEOUT_SECONDS",
        gt=0,
        le=300,
    )

    storage_dir: Path = Field(
        default_factory=lambda: Path.home() / ".airesearcher" / "storage",
        alias="AIRESEARCHER_STORAGE_DIR",
    )
    paper_library_dir: Path = Field(
        default_factory=lambda: REPOSITORY_ROOT / ".private" / "paper-library",
        alias="AIRESEARCHER_PAPER_LIBRARY_DIR",
    )
    model_cache_dir: Path = Field(
        default_factory=lambda: Path.home() / ".cache" / "airesearcher" / "models",
        alias="AIRESEARCHER_MODEL_CACHE_DIR",
    )
    embedding_model: str = Field(
        default="BAAI/bge-m3",
        alias="AIRESEARCHER_EMBEDDING_MODEL",
    )
    reranker_model: str = Field(
        default="BAAI/bge-reranker-v2-m3",
        alias="AIRESEARCHER_RERANKER_MODEL",
    )
    model_device: str = Field(default="auto", alias="AIRESEARCHER_MODEL_DEVICE")
    embedding_batch_size: int = Field(
        default=8,
        alias="AIRESEARCHER_EMBEDDING_BATCH_SIZE",
        ge=1,
        le=128,
    )
    reranker_batch_size: int = Field(
        default=4,
        alias="AIRESEARCHER_RERANKER_BATCH_SIZE",
        ge=1,
        le=64,
    )
    vector_size: int = Field(default=1024, alias="AIRESEARCHER_VECTOR_SIZE", ge=1)

    retrieval_candidate_count: int = Field(
        default=20,
        alias="AIRESEARCHER_RETRIEVAL_CANDIDATES",
        ge=5,
        le=100,
    )
    rerank_default_top_k: int = Field(
        default=5,
        alias="AIRESEARCHER_RERANK_TOP_K",
        ge=1,
        le=10,
    )
    chunk_size: int = Field(default=1200, alias="AIRESEARCHER_CHUNK_SIZE", ge=200, le=8000)
    chunk_overlap: int = Field(default=160, alias="AIRESEARCHER_CHUNK_OVERLAP", ge=0)

    worker_poll_seconds: float = Field(
        default=2.0,
        alias="AIRESEARCHER_WORKER_POLL_SECONDS",
        ge=0.1,
        le=60,
    )
    worker_lease_seconds: int = Field(
        default=300,
        alias="AIRESEARCHER_WORKER_LEASE_SECONDS",
        ge=30,
        le=3600,
    )
    ingestion_max_attempts: int = Field(
        default=3,
        alias="AIRESEARCHER_INGESTION_MAX_ATTEMPTS",
        ge=1,
        le=10,
    )

    upload_max_bytes: int = 50 * 1024 * 1024
    upload_max_pages: int = 500
    agent_max_tool_rounds: int = 3
    max_question_chars: int = 16000

    @field_validator("deepseek_base_url", "qdrant_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("URL must not be empty")
        return normalized

    @field_validator("storage_dir", "model_cache_dir")
    @classmethod
    def resolve_runtime_path(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @field_validator("paper_library_dir")
    @classmethod
    def resolve_paper_library_path(cls, value: Path) -> Path:
        expanded = value.expanduser()
        if not expanded.is_absolute():
            expanded = REPOSITORY_ROOT / expanded
        return expanded.resolve()

    @model_validator(mode="after")
    def validate_runtime_boundaries(self) -> Self:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("AIRESEARCHER_CHUNK_OVERLAP must be smaller than chunk size")
        for name, runtime_path in (
            ("AIRESEARCHER_STORAGE_DIR", self.storage_dir),
            ("AIRESEARCHER_MODEL_CACHE_DIR", self.model_cache_dir),
        ):
            if runtime_path == REPOSITORY_ROOT or runtime_path.is_relative_to(REPOSITORY_ROOT):
                raise ValueError(f"{name} must be outside the repository")
        private_root = (REPOSITORY_ROOT / ".private").resolve()
        if self.paper_library_dir.is_relative_to(REPOSITORY_ROOT) and (
            self.paper_library_dir == private_root
            or not self.paper_library_dir.is_relative_to(private_root)
        ):
            raise ValueError(
                "AIRESEARCHER_PAPER_LIBRARY_DIR inside the repository must be below .private"
            )
        return self

    @cached_property
    def database_url(self) -> URL:
        return URL.create(
            drivername="mysql+pymysql",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"charset": "utf8mb4"},
        )

    @cached_property
    def paper_library_originals_dir(self) -> Path:
        return self.paper_library_dir / "originals"

    @cached_property
    def paper_library_staging_dir(self) -> Path:
        return self.paper_library_dir / ".staging"

    def ensure_paper_library_directories(self) -> None:
        (self.paper_library_originals_dir / "uploads").mkdir(parents=True, exist_ok=True)
        self.paper_library_staging_dir.mkdir(parents=True, exist_ok=True)

    def ensure_runtime_directories(self) -> None:
        (self.storage_dir / "papers").mkdir(parents=True, exist_ok=True)
        (self.storage_dir / "uploads").mkdir(parents=True, exist_ok=True)
        self.model_cache_dir.mkdir(parents=True, exist_ok=True)
