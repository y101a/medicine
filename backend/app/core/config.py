from functools import lru_cache
from typing import Annotated
from urllib.parse import quote_plus, urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "病理诊断科普助手"
    app_environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )

    postgres_user: str = "medical_app"
    postgres_password: str
    postgres_db: str = "medical_assistant"
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432

    jwt_secret_key: str
    field_encryption_key: str
    fingerprint_secret: str
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    cookie_secure: bool = False

    # Legacy single-provider configuration; retained until model routing is migrated.
    ai_api_key: SecretStr | None = None
    ai_base_url: str = "https://api.openai.com/v1"
    ai_model: str | None = None
    ai_timeout_seconds: float = 90
    avatar_storage_dir: str = "data/avatars"

    # Named providers. Keys are SecretStr so settings repr/logging masks their values.
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"

    qwen_api_key: SecretStr | None = None
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "qwen3.7-text-embedding-flash"
    embedding_dimensions: int = 1024
    embedding_version: str = "2026-09-01"
    embedding_timeout_seconds: float = 30
    # The current OpenAI-compatible flash endpoint returns index=0 for every item
    # in a multi-input response. Keep one input per request to preserve mapping.
    embedding_batch_size: int = 1

    # Server-controlled speech recognition. User-provided model credentials are
    # intentionally never used for audio uploads.
    asr_api_key: SecretStr | None = None
    asr_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    asr_model: str = "qwen3-asr-flash"
    asr_timeout_seconds: float = Field(default=45, ge=5, le=60)
    asr_max_bytes: int = Field(default=2 * 1024 * 1024, ge=64 * 1024, le=2 * 1024 * 1024)
    asr_max_seconds: float = Field(default=60, ge=1, le=60)

    kimi_api_key: SecretStr | None = None
    kimi_base_url: str = "https://api.moonshot.cn/v1"

    # Retained for existing local environments, but no longer exposed by the
    # active model registry after provider smoke tests failed.
    zhipuai_api_key: SecretStr | None = None
    zhipuai_base_url: str = "https://open.bigmodel.cn/api/paas/v4"

    siliconflow_api_key: SecretStr | None = None
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"

    # Only generic, locally extracted medical topics may leave the server.
    tavily_api_key: SecretStr | None = None
    tavily_base_url: str = "https://api.tavily.com"

    # Development-only, read-only MCP adapters. The server is never mounted in
    # production even when MCP_ENABLED is accidentally left on.
    mcp_enabled: bool = True
    external_tool_timeout_seconds: float = 10
    pubmed_api_key: SecretStr | None = None
    pubmed_tool_name: str = "medical_assistant"
    pubmed_email: str | None = None
    amap_api_key: SecretStr | None = None

    @field_validator("qwen_base_url", mode="before")
    @classmethod
    def default_qwen_base_url(cls, value: object) -> object:
        if value is None or not str(value).strip():
            return "https://dashscope.aliyuncs.com/compatible-mode/v1"
        return value

    @field_validator("embedding_dimensions")
    @classmethod
    def validate_embedding_dimensions(cls, value: int) -> int:
        if value != 1024:
            raise ValueError("当前 pgvector 表结构固定要求 1024 维向量")
        return value

    @field_validator("embedding_batch_size")
    @classmethod
    def validate_embedding_batch_size(cls, value: int) -> int:
        if value < 1 or value > 20:
            raise ValueError("阿里云同步向量接口每批必须为 1-20 条")
        return value

    @field_validator("asr_base_url")
    @classmethod
    def validate_asr_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        hostname = (parsed.hostname or "").lower()
        allowed_host = hostname in {
            "dashscope.aliyuncs.com",
            "dashscope-intl.aliyuncs.com",
        } or hostname.endswith(".maas.aliyuncs.com")
        if (
            parsed.scheme != "https"
            or not allowed_host
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
            or parsed.query
            or parsed.fragment
            or parsed.path != "/compatible-mode/v1"
        ):
            raise ValueError("ASR_BASE_URL 必须是阿里云百炼 HTTPS 兼容接口地址")
        return normalized

    @field_validator("asr_model")
    @classmethod
    def validate_asr_model(cls, value: str) -> str:
        if value.strip() != "qwen3-asr-flash":
            raise ValueError("当前只允许 qwen3-asr-flash 语音识别模型")
        return value.strip()

    @field_validator("external_tool_timeout_seconds")
    @classmethod
    def validate_external_tool_timeout(cls, value: float) -> float:
        if value < 1 or value > 30:
            raise ValueError("外部只读工具超时必须为 1-30 秒")
        return value

    @field_validator("kimi_base_url", mode="before")
    @classmethod
    def default_kimi_base_url(cls, value: object) -> object:
        if value is None or not str(value).strip():
            return "https://api.moonshot.cn/v1"
        return value

    @field_validator("zhipuai_base_url", mode="before")
    @classmethod
    def default_zhipuai_base_url(cls, value: object) -> object:
        if value is None or not str(value).strip():
            return "https://open.bigmodel.cn/api/paas/v4"
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def database_url(self) -> str:
        username = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql+asyncpg://{username}:{password}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
