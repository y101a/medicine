"""Local Qwen tokenizer proxy for consultation prompt budgeting only.

The open Qwen tokenizer is not an exact tokenizer for every hosted model. A
2x multiplier and the existing prompt safety margin keep this an estimate.
"""

import gzip
import hashlib
from functools import lru_cache
from pathlib import Path

from tokenizers import Tokenizer

from app.core.errors import AppError

PROMPT_SAFETY_RATIO = 0.9
MESSAGE_OVERHEAD = 32
MEMORY_RESERVE_TOKENS = 4_800
PLANNER_RESERVE_TOKENS = 512
QWEN_TOKEN_MULTIPLIER = 2
QWEN_TOKENIZER_SHA256 = "0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3"


@lru_cache(maxsize=1)
def _qwen_tokenizer() -> Tokenizer | None:
    path = Path(__file__).with_name("tokenizer_data") / "qwen3_8_27b_tokenizer.json.gz"
    try:
        raw = gzip.decompress(path.read_bytes())
        if hashlib.sha256(raw).hexdigest() != QWEN_TOKENIZER_SHA256:
            return None
        return Tokenizer.from_str(raw.decode("utf-8"))
    except (OSError, ValueError):
        return None


def estimated_tokens(text: str) -> int:
    tokenizer = _qwen_tokenizer()
    if tokenizer is None:
        # A missing or damaged local asset must not make consultations fail.
        return len(text.encode("utf-8"))
    return len(tokenizer.encode(text, add_special_tokens=False).ids) * QWEN_TOKEN_MULTIPLIER


def history_cost(history: list[dict[str, str]]) -> int:
    return sum(estimated_tokens(item["content"]) + MESSAGE_OVERHEAD for item in history)


def select_recent_history(
    history: list[dict[str, str]],
    *,
    system_content: str,
    context_budget_tokens: int,
    output_reserve_tokens: int,
    has_older_messages: bool,
    planner_enabled: bool = False,
) -> tuple[list[dict[str, str]], int, bool]:
    """Keep the newest full messages that fit; return the number omitted.

    The last user message is never truncated. When it cannot fit with the fixed
    prompt, fail before calling the provider instead of silently losing facts.
    """
    if not history or history[-1]["role"] != "user":
        raise ValueError("history must end with a user message")
    ceiling = int(context_budget_tokens * PROMPT_SAFETY_RATIO) - output_reserve_tokens
    fixed = estimated_tokens(system_content) + MESSAGE_OVERHEAD
    if planner_enabled:
        fixed += PLANNER_RESERVE_TOKENS
    full_cost = fixed + history_cost(history)
    if full_cost <= ceiling and not has_older_messages:
        return history, 0, False

    # A continuity note can be added once older messages exist. Reserve its
    # maximum rendered size before selecting history, including on retries.
    latest_cost = estimated_tokens(history[-1]["content"]) + MESSAGE_OVERHEAD
    memory_allowed = latest_cost + MEMORY_RESERVE_TOKENS <= ceiling - fixed
    available = ceiling - fixed - (MEMORY_RESERVE_TOKENS if memory_allowed else 0)
    selected: list[dict[str, str]] = []
    used = 0
    for item in reversed(history):
        cost = estimated_tokens(item["content"]) + MESSAGE_OVERHEAD
        if used + cost > available:
            break
        selected.append(item)
        used += cost
    if not selected:
        raise AppError(
            413,
            "AI_CONTEXT_BUDGET_EXCEEDED",
            "当前问题和参考资料过长，请缩短问题或减少附件后重试",
        )
    selected.reverse()
    return selected, len(history) - len(selected), memory_allowed
