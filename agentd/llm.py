"""LLM 客户端：只走 OpenAI 兼容的 `POST {base_url}/chat/completions`。

不引入官方 SDK —— 需求只有"发一条 messages 拿一条 content"，
多一个依赖就多一份升级/兼容负担；换成通义、本地 vLLM 也只是改 base_url。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Settings

log = logging.getLogger(__name__)

# 值得重试的：限流、服务端错误、连接层抖动。4xx（除 429）是配置问题，重试没意义。
_RETRY_STATUS = {429, 500, 502, 503, 504}


class LlmError(RuntimeError):
    """LLM 调用失败，消息可直接展示给用户。"""


@dataclass
class LlmClient:
    settings: Settings
    transport: httpx.AsyncBaseTransport | None = field(default=None, repr=False)
    retry_delay: float = 1.0
    _http: httpx.AsyncClient | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._http = httpx.AsyncClient(
            base_url=self.settings.llm_base_url.rstrip("/"),
            timeout=httpx.Timeout(self.settings.llm_timeout),
            transport=self.transport,
        )

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def complete(self, messages: list[dict[str, str]]) -> str:
        """返回模型回复正文；失败抛 LlmError。最多尝试两次。"""
        if self._http is None:  # pragma: no cover - 生命周期错误
            raise LlmError("LLM 客户端已关闭")
        payload = {
            "model": self.settings.llm_model,
            "messages": messages,
            "max_tokens": self.settings.llm_max_tokens,
            "temperature": self.settings.llm_temperature,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.settings.api_key}"}

        last_error = "unknown"
        for attempt in range(2):
            try:
                resp = await self._http.post(
                    "/chat/completions", json=payload, headers=headers
                )
            except httpx.TimeoutException:
                last_error = f"超时（{self.settings.llm_timeout:g}s）"
            except httpx.HTTPError as exc:
                last_error = f"网络错误：{type(exc).__name__}"
            else:
                if resp.status_code == 200:
                    return _extract_content(resp.json())
                last_error = f"HTTP {resp.status_code}：{_short(resp.text)}"
                if resp.status_code not in _RETRY_STATUS:
                    raise LlmError(last_error)

            if attempt == 0:
                log.warning("LLM 调用失败，准备重试：%s", last_error)
                await asyncio.sleep(self.retry_delay)

        raise LlmError(last_error)


def _extract_content(payload: dict[str, Any]) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmError(f"响应里没有 choices[0].message.content：{_short(str(payload))}") from exc
    text = (content or "").strip()
    if not text:
        raise LlmError("模型返回了空内容")
    return text


def _short(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[:limit] + "…"
