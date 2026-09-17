import json

from pydantic import ValidationError

from app.core.errors import AppError
from app.schemas.consultations import FollowUpCard

FOLLOW_UP_PREFIX = "[[FOLLOW_UP_CARD]]"
FOLLOW_UP_PREFIXES = (FOLLOW_UP_PREFIX, r"[[FOLLOW\_UP\_CARD]]")


def is_follow_up_prefix_fragment(content: str) -> bool:
    return any(prefix.startswith(content) for prefix in FOLLOW_UP_PREFIXES)


def split_follow_up_content(content: str) -> tuple[str, str] | None:
    matches = [
        (position, prefix)
        for prefix in FOLLOW_UP_PREFIXES
        if (position := content.find(prefix)) >= 0
    ]
    if not matches:
        return None
    position, prefix = min(matches, key=lambda match: match[0])
    return content[:position], content[position + len(prefix) :]


def parse_follow_up(content: str, *, strict: bool = False) -> FollowUpCard | None:
    stripped = content.strip()
    split = split_follow_up_content(stripped)
    if split is None:
        return None
    _, raw = split
    raw = raw.strip().replace(r"\_", "_")
    if raw.startswith("```json"):
        raw = raw[7:].strip()
    elif raw.startswith("```"):
        raw = raw[3:].strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    try:
        return FollowUpCard.model_validate_json(raw)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        if strict:
            raise AppError(
                502,
                "AI_INVALID_STRUCTURED_RESPONSE",
                "模型返回的追问信息格式无效，请重试或切换其他模型",
            ) from exc
        return None


def serialize_follow_up(card: FollowUpCard) -> str:
    payload = card.model_dump(by_alias=True, mode="json")
    return f"{FOLLOW_UP_PREFIX}\n{json.dumps(payload, ensure_ascii=False)}"


def follow_up_fallback(card: FollowUpCard) -> str:
    questions = "\n".join(f"- {question.label}" for question in card.questions)
    return f"{card.intro}\n{questions}"
