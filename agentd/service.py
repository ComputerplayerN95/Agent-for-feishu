"""Agent 回合处理：白名单 → 去重 → 生成回复。

M0 的回复是 echo；M2 起若配置了 LLM 就走模型，否则仍回 echo（便于离线开发）。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from .config import Settings
from .llm import LlmClient, LlmError
from .models import IncomingMessage
from .store import Store

log = logging.getLogger(__name__)


@dataclass
class AgentService:
    settings: Settings
    store: Store
    llm: LlmClient | None = None
    # 同一会话串行，避免多轮上下文在并发请求里互相穿插
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict, repr=False)

    async def handle(self, msg: IncomingMessage) -> str | None:
        """返回要发回给用户的内容；返回 None 表示这条消息不该回复。"""
        if not self.settings.is_allowed(msg.sender_id):
            # 静默丢弃，不回 DENY，避免被当成探活或触发重推
            log.warning("drop message from non-whitelisted sender: %s", msg.sender_id)
            return None

        first_time = await asyncio.to_thread(self.store.mark_event, msg.event_id)
        if not first_time:
            log.info("duplicate event dropped: %s", msg.event_id)
            return None

        text = msg.text.strip()
        if not text:
            return None

        reply = await self.reply(text, msg.chat_id)
        await asyncio.to_thread(self.store.save_message, msg, reply)
        return reply

    async def reply(self, text: str, chat_id: str) -> str:
        if self.llm is None:
            return f"收到：{text}"

        lock = self._locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            messages = await self._build_messages(chat_id, text)
            try:
                return await self.llm.complete(messages)
            except LlmError as exc:
                log.error("LLM 调用失败 chat=%s: %s", chat_id, exc)
                return f"⚠️ 模型调用失败：{exc}"

    async def _build_messages(self, chat_id: str, text: str) -> list[dict[str, str]]:
        turns = self.settings.llm_history_turns
        history = await asyncio.to_thread(self.store.history, chat_id, turns)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.settings.llm_system_prompt}
        ]
        for row in history:
            messages.append({"role": "user", "content": row["text"]})
            messages.append({"role": "assistant", "content": row["reply"]})
        messages.append({"role": "user", "content": text})
        return messages
