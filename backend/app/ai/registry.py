from dataclasses import dataclass, field

from pydantic import SecretStr

from app.core.config import Settings, get_settings
from app.core.errors import AppError


@dataclass(frozen=True, slots=True)
class ModelConfig:
    id: str
    name: str
    provider: str
    provider_name: str
    description: str
    base_url: str
    api_key: SecretStr
    extra_payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelDefinition:
    id: str
    name: str
    provider: str
    provider_name: str
    description: str
    api_key_setting: str
    base_url_setting: str
    extra_payload: dict[str, object] = field(default_factory=dict)


MODEL_DEFINITIONS = (
    ModelDefinition(
        id="deepseek-v4-flash",
        name="DeepSeek V4 Flash",
        provider="deepseek",
        provider_name="DeepSeek",
        description="已验证可用的低成本通用模型，作为稳定兜底",
        api_key_setting="deepseek_api_key",
        base_url_setting="deepseek_base_url",
        extra_payload={"thinking": {"type": "disabled"}},
    ),
    ModelDefinition(
        id="qwen3.8-flash",
        name="通义千问 Qwen3.8 Flash",
        provider="qwen",
        provider_name="阿里云百炼",
        description="新款快速低成本模型，适合日常科普与结构化追问",
        api_key_setting="qwen_api_key",
        base_url_setting="qwen_base_url",
        extra_payload={"enable_thinking": False},
    ),
    ModelDefinition(
        id="kimi-k2.6",
        name="Kimi K2.6",
        provider="kimi",
        provider_name="Kimi",
        description="新款长上下文模型，关闭深度思考以提升响应速度",
        api_key_setting="kimi_api_key",
        base_url_setting="kimi_base_url",
        extra_payload={"thinking": {"type": "disabled"}, "temperature": 0.6},
    ),
    ModelDefinition(
        id="glm-5.2",
        name="智谱 GLM-5.2",
        provider="zhipuai",
        provider_name="智谱 AI",
        description="最新旗舰文本模型，适合需要更完整说明的科普问题",
        api_key_setting="zhipuai_api_key",
        base_url_setting="zhipuai_base_url",
        extra_payload={"thinking": {"type": "disabled"}},
    ),
)


def available_models(settings: Settings | None = None) -> list[ModelConfig]:
    current = settings or get_settings()
    models: list[ModelConfig] = []
    for definition in MODEL_DEFINITIONS:
        api_key = getattr(current, definition.api_key_setting)
        if not api_key or not api_key.get_secret_value().strip():
            continue
        models.append(
            ModelConfig(
                id=definition.id,
                name=definition.name,
                provider=definition.provider,
                provider_name=definition.provider_name,
                description=definition.description,
                base_url=getattr(current, definition.base_url_setting),
                api_key=api_key,
                extra_payload=definition.extra_payload,
            )
        )
    return models


def get_model(model_id: str, settings: Settings | None = None) -> ModelConfig:
    model = next((item for item in available_models(settings) if item.id == model_id), None)
    if model is None:
        raise AppError(422, "MODEL_NOT_AVAILABLE", "所选模型不存在或尚未配置")
    return model
