from __future__ import annotations

from pathlib import Path

from agentd.channel.mock import MockChannel
from agentd.config import Settings
from agentd.models import IncomingMessage
from agentd.runtime import Runtime


async def test_runtime_routes_message_to_channel(tmp_path: Path) -> None:
    channel = MockChannel()
    runtime = Runtime(Settings(env="dev", db_path=tmp_path / "rt.db"), channel=channel)

    await runtime.start()
    try:
        reply = await channel.receive("ping")

        assert reply == "收到：ping"
        assert channel.sent == [("mock-chat", "收到：ping")]
        assert runtime.readiness()["ready"] is True
    finally:
        await runtime.stop()


async def test_runtime_reports_not_ready_before_start(tmp_path: Path) -> None:
    runtime = Runtime(Settings(env="dev", db_path=tmp_path / "rt2.db"), channel=MockChannel())

    info = runtime.readiness()

    assert info["ready"] is False
    assert "db" in info["not_ready"]
    assert "mock" in info["not_ready"]


async def test_feishu_incoming_mapping() -> None:
    from agentd.channel.feishu import to_incoming

    class SenderId:
        open_id = "ou_sender"

    class Sender:
        sender_id = SenderId()

    class Message:
        message_id = "om_1"
        chat_id = "oc_1"
        chat_type = "p2p"
        message_type = "text"
        content = '{"text":"@_user_1 帮我看看"}'

    class Event:
        message = Message()
        sender = Sender()

    class Header:
        event_id = "evt_1"

    class Data:
        event = Event()
        header = Header()

    msg = to_incoming(Data())

    assert isinstance(msg, IncomingMessage)
    assert msg.event_id == "evt_1"
    assert msg.sender_id == "ou_sender"
    assert msg.text == "帮我看看"
    assert msg.is_p2p is True
