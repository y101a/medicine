"""Extract only user-stated health facts from one message.

Design boundary: the model is used as a *restating extractor*, never as a source of
conclusions. Facts that look like an inference or a diagnosis the user did not state
are rejected before they can be stored, and identity data is never persisted.
"""

import json
import re
import unicodedata

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.provider import chat_completions_url
from app.ai.registry import ModelConfig
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.privacy import redact_direct_identifiers
from app.models.health_record import CATEGORY_LABELS, HealthRecordCategory

EXTRACTION_TIMEOUT_SECONDS = 20
MAX_USER_TEXT_CHARS = 1200
MAX_EXISTING_FACTS = 20
MAX_FACTS = 5
MAX_FACT_CHARS = 200

# Hedging words that turn a restatement into an unverified conclusion.
INFERENCE_MARKERS = (
    "疑似",
    "可能",
    "不排除",
    "考虑为",
    "考虑是",
    "倾向于",
    "提示",
    "建议",
    "风险较高",
)
IDENTITY_PATTERN = re.compile(
    r"(?<!\d)1[3-9]\d{9}(?!\d)|(?<!\d)\d{17}[0-9Xx](?!\w)|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)


class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: HealthRecordCategory
    content: str = Field(min_length=2, max_length=MAX_FACT_CHARS)


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[ExtractedFact] = Field(default_factory=list, max_length=MAX_FACTS)


def build_extraction_prompt(
    user_text: str,
    existing_facts: list[str] | None = None,
) -> str:
    category_lines = "\n".join(
        f"- {category.value}：{label}" for category, label in CATEGORY_LABELS.items()
    )
    safe_user_text = redact_direct_identifiers(user_text)[0]
    existing = "（暂无）"
    if existing_facts:
        existing = "\n".join(
            f"- {redact_direct_identifiers(item)[0]}"
            for item in existing_facts[:MAX_EXISTING_FACTS]
        )
    return f"""你是健康记录抽取器。只把“用户自己明确说出的”健康事实抽成结构化条目。

规则：
1. 只保留用户明确陈述的事实，不得写入任何推断、猜测、疑似诊断或医学结论。
   例如用户说“最近总口渴”，只能记录“最近经常口渴”，绝不能记录“可能患有糖尿病”。
2. 不得写入身份信息（姓名、电话、身份证、邮箱、详细住址、单位名称）。
3. 不得写入建议、医嘱、用药剂量、检查结论或风险判断。
4. 每条 content 用简短中立的中文陈述，不超过 40 字，不得包含“疑似、可能、建议”等词。
5. 与“已有记录”重复或语义相同的条目不要再次输出。
6. 用户本轮没有陈述任何健康事实时，返回空数组。

category 只能取以下键之一：
{category_lines}

只输出 JSON，不要 Markdown 代码块，不要任何解释文字：
{{"facts":[{{"category":"symptom","content":"最近一周夜间失眠"}}]}}

已有记录（用于去重）：
{existing}

用户本轮消息：
{safe_user_text[:MAX_USER_TEXT_CHARS]}"""


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def is_safe_fact(content: str) -> bool:
    """Reject anything that is not a plain restatement of the user's own words."""

    normalized = unicodedata.normalize("NFKC", content).strip()
    if not 2 <= len(normalized) <= MAX_FACT_CHARS:
        return False
    if any(marker in normalized for marker in INFERENCE_MARKERS):
        return False
    return IDENTITY_PATTERN.search(normalized) is None


def parse_extraction(raw: str) -> list[ExtractedFact]:
    """Parse the model reply, dropping anything that is not a user-stated fact."""

    text = _strip_code_fence(raw)
    payload: object | None = None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                payload = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                payload = None
    if payload is None:
        raise AppError(502, "HEALTH_EXTRACT_INVALID", "健康记录提取结果不是有效 JSON")
    try:
        result = ExtractionResult.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        raise AppError(502, "HEALTH_EXTRACT_INVALID", "健康记录提取结果格式无效") from exc
    return [fact for fact in result.facts if is_safe_fact(fact.content)]


async def _request_extraction(prompt: str, model: ModelConfig) -> str:
    settings = get_settings()
    timeout = httpx.Timeout(
        min(settings.ai_timeout_seconds, EXTRACTION_TIMEOUT_SECONDS), connect=10
    )
    payload = {
        "model": model.id,
        "stream": False,
        "temperature": 0,
        "max_tokens": 600,
        "messages": [{"role": "system", "content": prompt}],
        **model.extra_payload,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                chat_completions_url(model.base_url),
                headers={
                    "Authorization": f"Bearer {model.api_key.get_secret_value()}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except (httpx.TimeoutException, TimeoutError) as exc:
        raise AppError(504, "AI_PROVIDER_TIMEOUT", "健康记录提取超时") from exc
    except httpx.HTTPError as exc:
        raise AppError(502, "AI_PROVIDER_UNAVAILABLE", "健康记录提取无法连接模型服务") from exc

    if response.status_code >= 400:
        raise AppError(502, "AI_PROVIDER_ERROR", "健康记录提取调用失败")
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AppError(502, "AI_PROVIDER_RESPONSE_INVALID", "健康记录提取返回格式无效") from exc
    if not isinstance(content, str) or not content.strip():
        raise AppError(502, "AI_PROVIDER_RESPONSE_INVALID", "健康记录提取返回空内容")
    return content


async def extract_health_facts(
    user_text: str,
    model: ModelConfig,
    *,
    existing_facts: list[str] | None = None,
) -> list[ExtractedFact]:
    """Return only safe, user-stated facts. Raises AppError on provider failure."""

    if not user_text.strip():
        return []
    prompt = build_extraction_prompt(user_text, existing_facts)
    raw = await _request_extraction(prompt, model)
    return parse_extraction(raw)
