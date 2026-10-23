import pytest

from app.ai import context_budget
from app.ai.context_budget import estimated_tokens, history_cost, select_recent_history
from app.core.errors import AppError


def _history(count: int, content: str = "短消息") -> list[dict[str, str]]:
    return [
        {"role": "user" if index % 2 == 0 else "assistant", "content": content}
        for index in range(count)
    ]


def test_short_history_can_keep_more_than_thirty_messages():
    history = _history(101)
    selected, omitted, memory_allowed = select_recent_history(
        history,
        system_content="系统规则",
        context_budget_tokens=8_192,
        output_reserve_tokens=1_024,
        has_older_messages=False,
    )
    assert len(selected) == 101
    assert omitted == 0
    assert not memory_allowed


def test_long_history_is_trimmed_before_thirty_messages():
    history = _history(21, "这是一段较长的中文消息。" * 40)
    selected, omitted, memory_allowed = select_recent_history(
        history,
        system_content="系统规则",
        context_budget_tokens=8_192,
        output_reserve_tokens=1_024,
        has_older_messages=False,
    )
    assert 0 < len(selected) < 21
    assert omitted == 21 - len(selected)
    assert selected[-1] is history[-1]
    assert memory_allowed


def test_output_and_memory_reserves_are_counted():
    history = _history(101, "稍长一些的消息")
    selected, omitted, memory_allowed = select_recent_history(
        history,
        system_content="系统规则",
        context_budget_tokens=8_192,
        output_reserve_tokens=1_024,
        has_older_messages=True,
    )
    assert omitted > 0
    assert memory_allowed
    ceiling = int(8_192 * 0.9) - 1_024
    assert history_cost(selected) + estimated_tokens("系统规则") + 32 + 4_800 <= ceiling


def test_current_question_is_not_silently_truncated():
    with pytest.raises(AppError) as error:
        select_recent_history(
            [{"role": "user", "content": "".join(f"第{i}项症状。" for i in range(3_000))}],
            system_content="系统规则",
            context_budget_tokens=8_192,
            output_reserve_tokens=1_024,
            has_older_messages=False,
        )
    assert error.value.code == "AI_CONTEXT_BUDGET_EXCEEDED"


def test_current_question_takes_priority_over_optional_memory():
    selected, omitted, memory_allowed = select_recent_history(
        _history(15, "较长的用户消息。" * 80),
        system_content="系统规则" * 1_000,
        context_budget_tokens=8_192,
        output_reserve_tokens=1_024,
        has_older_messages=True,
    )
    assert selected[-1]["role"] == "user"
    assert omitted > 0
    assert not memory_allowed


def test_pinned_qwen_tokenizer_reduces_chinese_overestimation():
    assert context_budget._qwen_tokenizer() is not None
    text = "我想了解头痛的常见原因和何时就医。"
    assert estimated_tokens(text) == 20
    assert estimated_tokens(text) < len(text.encode("utf-8"))


def test_missing_tokenizer_falls_back_to_byte_estimate(monkeypatch):
    monkeypatch.setattr(context_budget, "_qwen_tokenizer", lambda: None)
    text = "我想了解头痛。"
    assert estimated_tokens(text) == len(text.encode("utf-8"))


def test_qwen_budget_keeps_more_relevant_history_than_byte_fallback(monkeypatch):
    history = _history(81, "我想了解头痛的常见原因和何时就医。" * 12)
    kwargs = {
        "system_content": "系统规则",
        "context_budget_tokens": 32_768,
        "output_reserve_tokens": 2_048,
        "has_older_messages": False,
    }
    qwen_selected, _, _ = select_recent_history(history, **kwargs)
    monkeypatch.setattr(context_budget, "_qwen_tokenizer", lambda: None)
    byte_selected, _, _ = select_recent_history(history, **kwargs)
    assert len(qwen_selected) > len(byte_selected)
    assert qwen_selected[-1] is byte_selected[-1] is history[-1]
