from functools import lru_cache
from typing import Annotated, Self
from urllib.parse import quote_plus, urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
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

    # Development/test can use the local fake provider. Production must use
    # an explicitly configured real provider and a dedicated code HMAC secret.
    sms_provider: str = "fake"
    sms_code_secret: SecretStr | None = None
    sms_code_expire_seconds: int = Field(default=300, ge=60, le=900)
    sms_token_expire_seconds: int = Field(default=600, ge=60, le=1800)
    sms_resend_seconds: int = Field(default=60, ge=30, le=300)
    sms_max_attempts: int = Field(default=5, ge=1, le=10)
    sms_limit_phone_hourly: int = Field(default=5, ge=1, le=20)
    sms_limit_phone_daily: int = Field(default=10, ge=1, le=100)
    sms_limit_ip_10m: int = Field(default=10, ge=1, le=100)
    sms_limit_ip_daily: int = Field(default=30, ge=1, le=500)
    aliyun_pnvs_access_key_id: SecretStr | None = None
    aliyun_pnvs_access_key_secret: SecretStr | None = None
    aliyun_pnvs_endpoint: str = "dypnsapi.aliyuncs.com"
    aliyun_pnvs_sign_name: str | None = None
    aliyun_pnvs_template_code: str | None = None

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

    # Server-controlled medical image analysis. User model credentials are never used.
    image_analysis_api_key: SecretStr | None = None
    image_analysis_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    image_analysis_model: str = "qwen3.8-flash"
    image_analysis_timeout_seconds: float = Field(default=45, ge=5, le=60)
    image_max_bytes: int = Field(default=5 * 1024 * 1024, ge=64 * 1024, le=5 * 1024 * 1024)
    image_max_pixels: int = Field(default=20_000_000, ge=1_000_000, le=20_000_000)
    image_max_dimension: int = Field(default=2_400, ge=512, le=2_400)
    image_retention_days: int = Field(default=90, ge=1, le=365)
    image_orphan_hours: int = Field(default=24, ge=1, le=168)
    image_storage_dir: str = "data/medical_images"

    # Server-controlled AI educational illustration generation. User-supplied
    # chat credentials are never used, and the native MaaS URL is not the
    # OpenAI-compatible QWEN_BASE_URL.
    image_generation_api_key: SecretStr | None = None
    image_generation_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    image_generation_model: str = "wan2.6-t2i"
    image_generation_provider_code: str = "medical-assistant-local"
    image_generation_timeout_seconds: float = Field(default=30, ge=5, le=60)
    image_generation_poll_seconds: int = Field(default=3, ge=2, le=30)
    image_generation_retention_days: int = Field(default=90, ge=1, le=365)
    image_generation_max_download_bytes: int = Field(
        default=15 * 1024 * 1024, ge=1024 * 1024, le=30 * 1024 * 1024
    )
    image_generation_max_pixels: int = Field(default=25_000_000, ge=1_000_000, le=30_000_000)
    image_generation_limit_10m: int = Field(default=3, ge=1, le=20)
    image_generation_limit_daily: int = Field(default=10, ge=1, le=100)

    # Server-controlled DOCX/PPTX educational document generation. Content is
    # generated once as strict JSON and rendered locally into both formats.
    document_generation_api_key: SecretStr | None = None
    document_generation_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    document_generation_model: str = "qwen3.8-flash"
    document_generation_timeout_seconds: float = Field(default=60, ge=10, le=120)
    document_generation_retention_days: int = Field(default=30, ge=1, le=365)
    document_generation_storage_dir: str = "data/generated_documents"
    document_generation_max_bytes: int = Field(
        default=10 * 1024 * 1024, ge=1024 * 1024, le=30 * 1024 * 1024
    )
    document_generation_limit_10m: int = Field(default=3, ge=1, le=20)
    document_generation_limit_daily: int = Field(default=10, ge=1, le=100)
    document_generation_lease_seconds: int = Field(default=300, ge=60, le=900)
    document_generation_orphan_hours: int = Field(default=24, ge=1, le=168)

    # Consultation document extraction stays local until the user sends a question.
    # 2026-09-21（用户确认的方案 B）把这三项放宽：手机扫描的多页 PDF 经常同时撞体积与页数上限。
    # 代价是解析内存与单次 CPU 时间上升——multipart 与解析子进程都是整份进内存，
    # 而 attachment_context_max_chars 未变，所以模型看到的内容没有变多。
    attachment_max_bytes: int = Field(
        default=30 * 1024 * 1024, ge=64 * 1024, le=30 * 1024 * 1024
    )
    attachment_max_pages: int = Field(default=100, ge=1, le=100)
    attachment_max_chars: int = Field(default=500_000, ge=10_000, le=500_000)
    attachment_chunk_chars: int = Field(default=2_000, ge=500, le=4_000)
    attachment_context_max_chars: int = Field(default=12_000, ge=2_000, le=30_000)
    attachment_parse_timeout_seconds: float = Field(default=60, ge=5, le=60)

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

    @model_validator(mode="after")
    def validate_sms_configuration(self) -> Self:
        self.sms_provider = self.sms_provider.strip().lower()
        environment = self.app_environment.strip().lower()
        if self.sms_provider not in {"fake", "aliyun_pnvs"}:
            raise ValueError("SMS_PROVIDER 只允许 fake 或 aliyun_pnvs")
        if self.sms_provider == "fake" and environment not in {"development", "test"}:
            raise ValueError("非开发测试环境禁止使用模拟短信服务")
        if environment == "production":
            if self.sms_code_secret is None:
                raise ValueError("生产环境必须配置 SMS_CODE_SECRET")
            if (
                self.aliyun_pnvs_access_key_id is None
                or self.aliyun_pnvs_access_key_secret is None
            ):
                raise ValueError("生产环境必须配置阿里云短信认证 RAM AccessKey")
        return self

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

    @field_validator("image_analysis_base_url")
    @classmethod
    def validate_image_analysis_base_url(cls, value: str) -> str:
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
            raise ValueError("IMAGE_ANALYSIS_BASE_URL 必须是阿里云百炼 HTTPS 兼容接口地址")
        return normalized

    @field_validator("image_analysis_model")
    @classmethod
    def validate_image_analysis_model(cls, value: str) -> str:
        if value.strip() != "qwen3.8-flash":
            raise ValueError("当前只允许 qwen3.8-flash 图片识别模型")
        return value.strip()

    @field_validator("image_generation_base_url")
    @classmethod
    def validate_image_generation_base_url(cls, value: str) -> str:
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
            or parsed.path != "/api/v1"
        ):
            raise ValueError("IMAGE_GENERATION_BASE_URL 必须是阿里云百炼原生 HTTPS API 地址")
        return normalized

    @field_validator("image_generation_model")
    @classmethod
    def validate_image_generation_model(cls, value: str) -> str:
        if value.strip() != "wan2.6-t2i":
            raise ValueError("当前只允许 wan2.6-t2i 图片生成模型")
        return value.strip()

    @field_validator("image_generation_provider_code")
    @classmethod
    def validate_image_generation_provider_code(cls, value: str) -> str:
        normalized = value.strip()
        if (
            not 1 <= len(normalized) <= 64
            or any(ord(char) < 33 or ord(char) > 126 for char in normalized)
            or any(char in {'"', "\\"} for char in normalized)
        ):
            raise ValueError("IMAGE_GENERATION_PROVIDER_CODE 必须是 1-64 位安全 ASCII 标识")
        return normalized

    @field_validator("document_generation_base_url")
    @classmethod
    def validate_document_generation_base_url(cls, value: str) -> str:
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
            raise ValueError("DOCUMENT_GENERATION_BASE_URL 必须是阿里云百炼 HTTPS 兼容接口地址")
        return normalized

    @field_validator("document_generation_model")
    @classmethod
    def validate_document_generation_model(cls, value: str) -> str:
        if value.strip() != "qwen3.8-flash":
            raise ValueError("当前只允许 qwen3.8-flash 文档生成模型")
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
