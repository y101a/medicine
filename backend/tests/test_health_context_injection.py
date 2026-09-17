"""Verify the health context really reaches the model prompt.

健康记录只能作为受限背景注入：注入时必须同时带上「不得推断病因」与「不得降低红旗
警惕」的条款，未提供时不得出现任何相关文本。
"""

import pytest
from pydantic import SecretStr

from app.ai import provider
from app.ai.health_context import render_health_context
from app.ai.registry import ModelConfig

HEALTH_BLOCK = render_health_context('[{"category":"近期症状","content":"夜间失眠"}]')


def model_config() -> ModelConfig:
    return ModelConfig(
        id="test-model",
        name="测试模型",
        provider="test",
        provider_name="测试服务商",
        description="",
        base_url="http://127.0.0.1:1/v1",
        api_key=SecretStr("test-key"),
    )


class FakeStreamResponse:
    status_code = 200

    async def aread(self) -> bytes:
        return b""

    async def aiter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"好的"}}]}'
        yield "data: [DONE]"


class FakeStreamContext:
    async def __aenter__(self) -> FakeStreamResponse:
        return FakeStreamResponse()

    async def __aexit__(self, *args: object) -> bool:
        return False


class FakeAsyncClient:
    captured: dict = {}

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    def stream(self, method: str, url: str, **kwargs: object) -> FakeStreamContext:
        FakeAsyncClient.captured["payload"] = kwargs["json"]
        return FakeStreamContext()


@pytest.fixture
def captured(monkeypatch):
    FakeAsyncClient.captured = {}
    monkeypatch.setattr(provider.httpx, "AsyncClient", FakeAsyncClient)
    return FakeAsyncClient.captured


async def collect(health_context: str | None) -> list[str]:
    return [
        chunk
        async for chunk in provider.stream_chat(
            [{"role": "user", "content": "我最近睡不好"}],
            model_config(),
            "plain",
            "本轮检索证据 JSON：[]",
            health_context,
        )
    ]


async def test_health_context_is_injected_with_safety_rules(captured):
    chunks = await collect(HEALTH_BLOCK)

    assert chunks == ["好的"]
    system = captured["payload"]["messages"][0]["content"]
    assert "夜间失眠" in system
    assert "用户自述健康记录" in system
    assert "不得据记录推断病因" in system
    assert "不得因为记录中存在某项情况而降低对红旗症状的警惕" in system
    # 注入健康记录不能挤掉检索证据。
    assert "本轮检索证据" in system


async def test_without_health_context_nothing_is_injected(captured):
    await collect(None)

    system = captured["payload"]["messages"][0]["content"]
    assert "用户自述健康记录" not in system
    assert "不得据记录推断病因" not in system
    assert "本轮检索证据" in system