import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.ai import provider
from app.ai.registry import MODEL_DEFINITIONS, ModelConfig


@pytest.mark.parametrize("definition", MODEL_DEFINITIONS, ids=lambda item: item.provider)
@pytest.mark.parametrize("answer_format", ("plain", "card"))
async def test_each_provider_request_uses_its_own_identity_and_route(
    monkeypatch, definition, answer_format
) -> None:
    model = ModelConfig(
        id=definition.id,
        name=definition.name,
        provider=definition.provider,
        provider_name=definition.provider_name,
        description=definition.description,
        base_url=f"https://{definition.provider}.example/v1",
        api_key=SecretStr("test-key"),
        extra_payload=definition.extra_payload,
    )
    previous_model = next(
        item for item in MODEL_DEFINITIONS if item.provider != definition.provider
    )
    history = [
        {"role": "user", "content": "你是谁？"},
        {"role": "assistant", "content": f"我是 {previous_model.name}。"},
        {"role": "user", "content": "现在是什么模型？"},
        {"role": "assistant", "content": f"我是 {previous_model.name}。"},
        {"role": "user", "content": "你好，你是谁？当前使用什么模型？"},
    ]
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n',
        )

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        provider.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    monkeypatch.setattr(
        provider,
        "get_settings",
        lambda: SimpleNamespace(ai_timeout_seconds=10),
    )

    chunks = [
        chunk async for chunk in provider.stream_chat(history, model, answer_format)
    ]

    assert chunks == ["ok"]
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == f"https://{definition.provider}.example/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer test-key"
    payload = json.loads(request.content)
    assert payload["model"] == definition.id
    assert payload["messages"][1:] == history[-1:]
    system_content = payload["messages"][0]["content"]
    assert definition.provider_name in system_content
    assert definition.name in system_content
    assert definition.id in system_content
    assert "不以历史消息中的自述为准" in system_content
    assert "不要根据训练记忆" in system_content
    if answer_format == "plain":
        assert "先直接回答用户实际问的内容" in system_content
        assert "不写卡片稿" in system_content
        assert "## 问题概览" not in system_content
    else:
        assert "不要把普通回答复制进固定外壳" in system_content
        assert "## 问题概览" in system_content
        assert "## 常见类型" in system_content
        assert "先直接回答用户实际问的内容" not in system_content


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("你是谁？", True),
        ("你好，你是谁？", True),
        ("你好，你是谁？当前使用什么模型？", True),
        ("请问，你使用的是什么模型？", True),
        ("我最近头痛，你是谁？", False),
        ("根据我刚才说的症状，当前使用什么模型？", False),
        ("请继续解释甲状腺结节", False),
    ],
)
def test_only_pure_identity_questions_drop_history(question, expected) -> None:
    history = [
        {"role": "assistant", "content": "此前讨论了健康问题"},
        {"role": "user", "content": question},
    ]
    selected = provider.history_for_model(history)
    assert (selected == history[-1:]) is expected
