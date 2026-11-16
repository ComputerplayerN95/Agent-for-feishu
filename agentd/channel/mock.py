"""Mock 通道：本地开发与测试用，不发任何网络请求。"""

from __future__ import annotations

import itertools
import time

from ..models import IncomingMessage
from .base import MessageHandler


class MockChannel:
    name = "mock"

    def __init__(self, handler: MessageHandler | None = None) -> None:
        self._handler = handler
        self._connected = False
        self.sent: list[tuple[str, str]] = []
        self._seq = itertools.count(1)

    @property
    def connected(self) -> bool:
        return self._connected

    def set_handler(self, handler: MessageHandler) -> None:
        self._handler = handler

    async def start(self) -> None:
        self._connected = True

    async def stop(self) -> None:
        self._connected = False

    async def send_text(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))

    async def receive(
        self,
        text: str,
        *,
        sender_id: str = "mock-user",
        chat_id: str = "mock-chat",
        event_id: str | None = None,
        chat_type: str = "p2p",
    ) -> str | None:
        """模拟一条入站消息，走完整个 dispatch 流程。"""
        if self._handler is None:
            raise RuntimeError("no handler registered")
        msg = IncomingMessage(
            channel=self.name,
            event_id=event_id or f"mock-event-{next(self._seq)}",
            message_id=f"mock-msg-{int(time.time() * 1000)}",
            chat_id=chat_id,
            chat_type=chat_type,
            sender_id=sender_id,
            text=text,
        )
        return await self._handler(msg)
