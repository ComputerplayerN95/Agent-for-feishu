from __future__ import annotations

import json

import httpx
import pytest

from agentd.config import Settings
from agentd.llm import LlmClient, LlmError


def make_client(handler, **settings_kwargs) -> LlmClient:
    settings = Settings(
        llm_api_key="test-key",
        llm_base_url="https://llm.test/v1",
        llm_timeout=5,
        **settings_kwargs,
    )
    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_delay=0)


def completion(content: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": content}}]}
    )


async def test_complete_returns_content() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return completion("你好，我在。")

    client = make_client(handler)
    text = await client.complete([{"role": "user", "content": "在吗"}])
    await client.aclose()

    assert text == "你好，我在。"
    assert seen[0].url == "https://llm.test/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer test-key"
    body = json.loads(seen[0].content)
    assert body["model"] == "deepseek-chat"
    assert body["stream"] is False


async def test_retry_on_500_then_success() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="boom")
        return completion("第二次成功")

    client = make_client(handler)
    assert await client.complete([{"role": "user", "content": "hi"}]) == "第二次成功"
    await client.aclose()
    assert calls["n"] == 2


async def test_401_is_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, text="invalid api key")

    client = make_client(handler)
    with pytest.raises(LlmError, match="HTTP 401"):
        await client.complete([{"role": "user", "content": "hi"}])
    await client.aclose()
    assert calls["n"] == 1


async def test_timeout_raises_friendly_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("too slow", request=request)

    client = make_client(handler)
    with pytest.raises(LlmError, match="超时"):
        await client.complete([{"role": "user", "content": "hi"}])
    await client.aclose()


async def test_empty_content_is_error() -> None:
    client = make_client(lambda request: completion("   "))
    with pytest.raises(LlmError, match="空内容"):
        await client.complete([{"role": "user", "content": "hi"}])
    await client.aclose()
