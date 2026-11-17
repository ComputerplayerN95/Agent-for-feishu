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


class FakeLlm:
    def __init__(self, reply: str = "模型回答") -> None:
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.reply


async def test_llm_reply_is_used_when_configured(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    llm = FakeLlm("这是模型回答")
    service = AgentService(Settings(env="dev"), store, llm)  # type: ignore[arg-type]

    reply = await service.handle(make_message(text="1+1 等于几"))

    assert reply == "这是模型回答"
    assert store.recent()[0]["reply"] == "这是模型回答"
    messages = llm.calls[0]
    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "1+1 等于几"}
    store.close()


async def test_second_turn_carries_history(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    llm = FakeLlm("记住了")
    service = AgentService(Settings(env="dev"), store, llm)  # type: ignore[arg-type]

    await service.handle(make_message(event_id="e1", text="我叫小明"))
    await service.handle(make_message(event_id="e2", text="我叫什么"))

    messages = llm.calls[1]
    assert {"role": "user", "content": "我叫小明"} in messages
    assert {"role": "assistant", "content": "记住了"} in messages
    assert messages[-1] == {"role": "user", "content": "我叫什么"}
    store.close()


async def test_history_is_per_chat(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    llm = FakeLlm()
    service = AgentService(Settings(env="dev"), store, llm)  # type: ignore[arg-type]

    await service.handle(make_message(event_id="e1", chat_id="chat-A", text="A 的话"))
    await service.handle(make_message(event_id="e2", chat_id="chat-B", text="B 的话"))

    messages = llm.calls[1]
    assert all(turn["content"] != "A 的话" for turn in messages)
    store.close()


async def test_llm_failure_becomes_friendly_message(tmp_path: Path) -> None:
    from agentd.llm import LlmError

    class BrokenLlm:
        async def complete(self, messages: list[dict[str, str]]) -> str:
            raise LlmError("HTTP 500：boom")

    store = make_store(tmp_path)
    service = AgentService(Settings(env="dev"), store, BrokenLlm())  # type: ignore[arg-type]

    reply = await service.handle(make_message())

    assert reply is not None
    assert reply.startswith("⚠️ 模型调用失败")
    store.close()
