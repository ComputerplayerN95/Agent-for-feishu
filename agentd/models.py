"""跨通道的领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class IncomingMessage:
    """一条已归一化的入站消息，通道差异在这一层被抹平。"""

    channel: str
    event_id: str
    message_id: str
    chat_id: str
    chat_type: str
    sender_id: str
    text: str
    raw: Any = field(default=None, repr=False)

    @property
    def is_p2p(self) -> bool:
        return self.chat_type == "p2p"
