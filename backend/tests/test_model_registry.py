from app.ai.registry import MODEL_DEFINITIONS
from app.core.config import Settings


def test_model_registry_exposes_one_model_per_provider() -> None:
    assert [(model.id, model.provider) for model in MODEL_DEFINITIONS] == [
        ("deepseek-v4-flash", "deepseek"),
        ("qwen3.8-flash", "qwen"),
        ("kimi-k2.6", "kimi"),
        ("glm-5.2", "zhipuai"),
    ]


def test_blank_provider_base_urls_fall_back_to_official_defaults() -> None:
    settings = Settings(
        _env_file=None,
        postgres_password="test",
        jwt_secret_key="test",
        field_encryption_key="test",
        fingerprint_secret="test",
        qwen_base_url="",
        kimi_base_url="",
        zhipuai_base_url="",
    )

    assert settings.qwen_base_url == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    assert settings.kimi_base_url == "https://api.moonshot.cn/v1"
    assert settings.zhipuai_base_url == "https://open.bigmodel.cn/api/paas/v4"
