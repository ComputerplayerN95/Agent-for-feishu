"""把配置、存储、通道、服务串成一个可启动的运行时。"""

from __future__ import annotations

import asyncio
import logging

from .channel.base import Channel
from .config import Settings
from .models import IncomingMessage
from .service import AgentService
from .store import Store

log = logging.getLogger(__name__)


class Runtime:
    def __init__(
        self,
        settings: Settings,
        *,
        store: Store | None = None,
        channel: Channel | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or Store(settings.db_path)
        self.service = AgentService(settings, self.store)
        self.channel: Channel = channel or self._build_channel()
        self.channel.set_handler(self.dispatch)

    def _build_channel(self) -> Channel:
        if self.settings.feishu_configured:
            from .channel.feishu import FeishuChannel

            return FeishuChannel(self.settings)  # type: ignore[return-value]
        from .channel.mock import MockChannel

        log.warning("飞书凭证未配置，降级为 mock 通道")
        return MockChannel()  # type: ignore[return-value]

    async def dispatch(self, msg: IncomingMessage) -> str | None:
        """通道收到消息后唯一入口：处理 + 回复。"""
        reply = await self.service.handle(msg)
        if reply is not None:
            await self.channel.send_text(msg.chat_id, reply)
        return reply

    async def start(self) -> None:
        await asyncio.to_thread(self.store.connect)
        await self.channel.start()
        log.info("runtime started channel=%s db=%s", self.channel.name, self.store._path)

    async def stop(self) -> None:
        await self.channel.stop()
        await asyncio.to_thread(self.store.close)
        log.info("runtime stopped")

    def readiness(self) -> dict[str, object]:
        missing: list[str] = []
        if not self.store.ping():
            missing.append("db")
        if not self.channel.connected:
            missing.append(self.channel.name)
        return {
            "ready": not missing,
            "not_ready": missing,
            "channel": self.channel.name,
            "env": self.settings.env,
        }
