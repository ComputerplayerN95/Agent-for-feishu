"""通道适配层的公共契约。

加一个通道 = 实现这个 Protocol，其余代码不动。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from ..models import IncomingMessage

MessageHandler = Callable[[IncomingMessage], Awaitable[str | None]]


@runtime_checkable
class Channel(Protocol):
    name: str

    @property
    def connected(self) -> bool: ...

    def set_handler(self, handler: MessageHandler) -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def send_text(self, chat_id: str, text: str) -> None: ...
