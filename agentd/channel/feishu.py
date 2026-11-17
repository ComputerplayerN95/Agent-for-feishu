"""飞书通道：长连接收事件 + OpenAPI 发消息。

长连接是**出站** WebSocket，不需要公网 IP、域名或 Ingress；
HTTP 那 8080 端口只留给 kubelet 探针。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from typing import Any

import httpx

from ..config import Settings
from ..models import IncomingMessage
from ..textutil import split_text
from .base import MessageHandler

log = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"@_user_\d+")


def _extract_text(message: Any) -> str:
    msg_type = getattr(message, "message_type", None) or getattr(message, "msg_type", "") or ""
    raw = getattr(message, "content", "") or ""
    try:
        content = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return raw if isinstance(raw, str) else ""

    if not isinstance(content, dict):
        return ""
    if msg_type == "text":
        text = content.get("text", "")
    elif msg_type == "post":
        parts: list[str] = []
        for line in content.get("content", []) or []:
            for node in line:
                if isinstance(node, dict) and node.get("tag") == "text":
                    parts.append(node.get("text", ""))
        text = "".join(parts)
    else:
        return f"[{msg_type or 'unknown'}]"
    return _MENTION_RE.sub("", text).strip()


def to_incoming(data: Any) -> IncomingMessage:
    """把 SDK 事件对象转成通道无关的 IncomingMessage。"""
    event = data.event
    message = event.message
    sender = event.sender
    header = getattr(data, "header", None)
    sender_id = getattr(getattr(sender, "sender_id", None), "open_id", "") or ""
    return IncomingMessage(
        channel="feishu",
        event_id=getattr(header, "event_id", "") if header is not None else "",
        message_id=getattr(message, "message_id", ""),
        chat_id=getattr(message, "chat_id", ""),
        chat_type=getattr(message, "chat_type", ""),
        sender_id=sender_id,
        text=_extract_text(message),
        raw=data,
    )


class FeishuChannel:
    name = "feishu"

    def __init__(self, settings: Settings, handler: MessageHandler | None = None) -> None:
        self._settings = settings
        self._handler = handler
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws: Any = None
        self._sdk_loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._start_error: BaseException | None = None
        self._http = httpx.AsyncClient(
            base_url=settings.feishu_domain, timeout=httpx.Timeout(10.0)
        )
        self._token: str | None = None
        self._token_deadline = 0.0

    @property
    def connected(self) -> bool:
        # SDK 在握手成功后才会把 _conn 赋成 websocket 对象
        return self._ws is not None and getattr(self._ws, "_conn", None) is not None

    def set_handler(self, handler: MessageHandler) -> None:
        self._handler = handler

    # --- lifecycle -------------------------------------------------
    async def start(self) -> None:
        if not self._settings.feishu_configured:
            raise RuntimeError("AGENTD_FEISHU_APP_ID / AGENTD_FEISHU_APP_SECRET 未配置")

        self._loop = asyncio.get_running_loop()
        self._thread = threading.Thread(target=self._run, name="feishu-ws", daemon=True)
        self._thread.start()

        ready = await asyncio.to_thread(self._started.wait, 15)
        if self._start_error is not None:
            raise RuntimeError(f"飞书长连接启动失败: {self._start_error}") from self._start_error
        if not ready:  # pragma: no cover - 正常不会走到
            log.warning("feishu long connection still starting after 15s")
        log.info("feishu long connection starting")

    def _run(self) -> None:
        """在工作线程里建 lark 客户端并阻塞跑长连接。

        有个坑必须在这里 import：`lark_oapi/ws/client.py` 在**模块导入时**执行
        `loop = asyncio.get_event_loop()`，把 loop 抓成模块级全局，之后
        `Client.start()` 只用这个 loop 跑 run_until_complete。若在 uvicorn 的事件
        循环里 import，抓到的就是那个正在运行的 loop，跨线程调用立刻报
        "This event loop is already running"。在没有 running loop 的线程里首次
        import，SDK 才会走 except 分支新建并持有自己的 loop。
        """
        try:
            import lark_oapi as lark

            self._sdk_loop = asyncio.get_event_loop()
            dispatcher = (
                lark.EventDispatcherHandler.builder("", "")
                .register_p2_im_message_receive_v1(self._on_event)
                .build()
            )
            self._ws = lark.ws.Client(
                self._settings.feishu_app_id,
                self._settings.app_secret,
                event_handler=dispatcher,
                log_level=lark.LogLevel.INFO,
            )
        except BaseException as exc:  # pragma: no cover - 依赖缺失/凭证错误
            self._start_error = exc
            log.exception("failed to create feishu ws client")
            self._started.set()
            return
        self._started.set()

        try:
            self._ws.start()  # 阻塞；内部自带重连
        except Exception:
            log.exception("feishu long connection crashed")
        finally:
            log.info("feishu long connection stopped")

    async def stop(self) -> None:
        await asyncio.to_thread(self._close_ws)
        if self._thread is not None and self._thread.is_alive():
            await asyncio.to_thread(self._thread.join, 5)
        await self._http.aclose()

    def _close_ws(self) -> None:
        """SDK 这个版本没有 public stop()，只能关连接再停它自己的 loop。"""
        ws, loop = self._ws, self._sdk_loop
        if ws is None or loop is None:
            return
        try:
            disconnect = getattr(ws, "_disconnect", None)
            if disconnect is not None and loop.is_running():
                asyncio.run_coroutine_threadsafe(disconnect(), loop).result(timeout=3)
        except Exception:  # pragma: no cover - 关停尽力而为
            log.debug("failed to close feishu ws connection", exc_info=True)
        if loop.is_running():
            loop.call_soon_threadsafe(loop.stop)

    # --- inbound ---------------------------------------------------
    def _on_event(self, data: Any) -> None:
        try:
            msg = to_incoming(data)
        except Exception:
            log.exception("failed to normalize feishu event")
            return
        log.info(
            "feishu event received event_id=%s chat_type=%s chat_id=%s sender=%s text=%r",
            msg.event_id,
            msg.chat_type,
            msg.chat_id,
            msg.sender_id,
            msg.text[:60],
        )
        if self._loop is None or self._handler is None:
            log.error("feishu event arrived before runtime is ready")
            return
        # 回调跑在 SDK 线程里，把协程丢回主事件循环
        future = asyncio.run_coroutine_threadsafe(self._handler(msg), self._loop)
        future.add_done_callback(self._on_done)

    @staticmethod
    def _on_done(future: Any) -> None:
        exc = future.exception()
        if exc is not None:
            log.error("message handler failed: %s", exc, exc_info=exc)
            return
        if future.result() is None:
            log.info("event dropped (not allowed / duplicate / empty)")
        else:
            log.info("event handled, reply sent")

    # --- outbound --------------------------------------------------
    async def _access_token(self) -> str:
        if self._token is not None and time.monotonic() < self._token_deadline:
            return self._token
        resp = await self._http.post(
            "/open-apis/auth/v3/tenant_access_token/internal",
            json={
                "app_id": self._settings.feishu_app_id,
                "app_secret": self._settings.app_secret,
            },
        )
        payload = resp.json() if resp.content else {}
        if resp.status_code >= 400 or payload.get("code") != 0:
            raise RuntimeError(
                f"tenant_access_token failed: status={resp.status_code} body={payload}"
            )
        self._token = payload["tenant_access_token"]
        expire = int(payload.get("expire", 7200))
        self._token_deadline = time.monotonic() + max(expire - 60, 60)
        return self._token

    async def send_text(self, chat_id: str, text: str) -> None:
        # 单条文本消息有长度上限，长回复拆成多条按顺序发，失败即中断
        chunks = split_text(text)
        token = await self._access_token()
        for index, chunk in enumerate(chunks, start=1):
            await self._send_one(token, chat_id, chunk)
        if len(chunks) > 1:
            log.info("长回复已拆分发送 chat=%s chunks=%d", chat_id, len(chunks))

    async def _send_one(self, token: str, chat_id: str, text: str) -> None:
        resp = await self._http.post(
            "/open-apis/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )
        payload = resp.json() if resp.content else {}
        if resp.status_code >= 400 or payload.get("code") not in (0, None):
            raise RuntimeError(
                f"send message failed: status={resp.status_code} body={payload}"
            )
