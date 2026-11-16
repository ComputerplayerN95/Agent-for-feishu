"""Agent 回合处理：白名单 → 去重 → 生成回复。

M0 的回复是 echo；M2 把 `reply()` 换成 LLM 调用，其余流程不动。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .config import Settings
from .models import IncomingMessage
from .store import Store

log = logging.getLogger(__name__)


@dataclass
class AgentService:
    settings: Settings
    store: Store

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

        reply = self.reply(text)
        await asyncio.to_thread(self.store.save_message, msg, reply)
        return reply

    def reply(self, text: str) -> str:
        return f"收到：{text}"
