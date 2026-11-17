"""长连接事件探针：排除一切业务代码，只看"飞书到底有没有把事件推过来"。

用法（在服务器上，仓库根目录）：

    systemctl stop agentd agentd-probe agentd-smoke 2>/dev/null
    .venv/bin/python tools/probe_events.py

它会：
  1. 用 DEBUG 级别打印 WebSocket 上收到的**每一帧**（含 ping/pong/data）；
  2. 注册 `im.message.receive_v1`（单聊/群@消息）与 `im.chat.member.bot.added_v1`（机器人进群）两个处理器；
  3. 收到任何事件就整段打印，不做任何过滤。

判定标准：
  * 出现 `BINARY ... [N bytes]` 且随后有 `EVENT ...` → 事件是通的，问题在你的业务代码；
  * 只有 `receive pong`、没有任何 data 帧 → 事件**根本没被推送到这条连接**，
    与 SDK 版本、handler 注册、代码都无关，只能是平台侧配置或发消息的对象不对。
"""

from __future__ import annotations

import logging
import os
import sys

import lark_oapi as lark

logging.basicConfig(
    level=logging.DEBUG,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
)

APP_ID = os.environ.get("AGENTD_FEISHU_APP_ID", "")
APP_SECRET = os.environ.get("AGENTD_FEISHU_APP_SECRET", "")


def on_message(data: object) -> None:
    print("EVENT im.message.receive_v1 >", data, flush=True)


def on_bot_added(data: object) -> None:
    print("EVENT im.chat.member.bot.added_v1 >", data, flush=True)


def main() -> int:
    if not APP_ID or not APP_SECRET:
        print(
            "缺少 AGENTD_FEISHU_APP_ID / AGENTD_FEISHU_APP_SECRET。\n"
            "如果凭证在 .env 里，用： set -a; . ./.env; set +a; .venv/bin/python tools/probe_events.py",
            file=sys.stderr,
        )
        return 2

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .register_p2_im_chat_member_bot_added_v1(on_bot_added)
        .build()
    )
    client = lark.ws.Client(
        APP_ID,
        APP_SECRET,
        event_handler=handler,
        log_level=lark.LogLevel.DEBUG,
    )
    print(f"connecting as {APP_ID} ...", flush=True)
    client.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
