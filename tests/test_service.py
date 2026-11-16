from __future__ import annotations

from pathlib import Path

from agentd.config import Settings
from agentd.models import IncomingMessage
from agentd.service import AgentService
from agentd.store import Store


def make_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "test.db")
    store.connect()
    return store


def make_message(**overrides: object) -> IncomingMessage:
    data: dict[str, object] = {
        "channel": "mock",
        "event_id": "event-1",
        "message_id": "msg-1",
        "chat_id": "chat-1",
        "chat_type": "p2p",
        "sender_id": "ou_user",
        "text": "你好",
    }
    data.update(overrides)
    return IncomingMessage(**data)  # type: ignore[arg-type]


async def test_echo_reply_and_persist(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    service = AgentService(Settings(env="dev"), store)

    reply = await service.handle(make_message())

    assert reply == "收到：你好"
    rows = store.recent()
    assert len(rows) == 1
    assert rows[0]["text"] == "你好"
    assert rows[0]["reply"] == "收到：你好"
    store.close()


async def test_duplicate_event_is_dropped(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    service = AgentService(Settings(env="dev"), store)

    assert await service.handle(make_message()) is not None
    assert await service.handle(make_message()) is None
    assert len(store.recent()) == 1
    store.close()


async def test_non_whitelisted_sender_is_silently_dropped(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    service = AgentService(Settings(env="prod", allowed_senders=["ou_me"]), store)

    assert await service.handle(make_message(sender_id="ou_stranger")) is None
    assert store.recent() == []
    store.close()


async def test_empty_text_is_ignored(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    service = AgentService(Settings(env="dev"), store)

    assert await service.handle(make_message(text="   ")) is None
    store.close()
