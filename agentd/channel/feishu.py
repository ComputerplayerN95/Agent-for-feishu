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
        self._thread: threading.Thread | None = None
        self._connected = False
        self._http = httpx.AsyncClient(
            base_url=settings.feishu_domain, timeout=httpx.Timeout(10.0)
        )
        self._token: str | None = None
        self._token_deadline = 0.0

    @property
    def connected(self) -> bool:
        return self._connected

    def set_handler(self, handler: MessageHandler) -> None:
        self._handler = handler

    # --- lifecycle -------------------------------------------------
    async def start(self) -> None:
        if not self._settings.feishu_configured:
            raise RuntimeError("AGENTD_FEISHU_APP_ID / AGENTD_FEISHU_APP_SECRET 未配置")
        try:
            import lark_oapi as lark
        except ImportError as exc:  # pragma: no cover - 依赖缺失时给出人话
            raise RuntimeError("缺少 lark-oapi 依赖，请先 uv sync") from exc

        self._loop = asyncio.get_running_loop()
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
        self._thread = threading.Thread(target=self._run, name="feishu-ws", daemon=True)
        self._thread.start()
        log.info("feishu long connection starting")

    def _run(self) -> None:
        # start() 是阻塞的，跑在独立线程里；这只线程活着就认为链路在尝试维持
        self._connected = True
        try:
            self._ws.start()
        except Exception:
            log.exception("feishu long connection crashed")
        finally:
            self._connected = False
            log.info("feishu long connection stopped")

    async def stop(self) -> None:
        if self._ws is not None:
            try:
                self._ws.stop()
            except Exception:
                log.warning("failed to stop feishu ws client", exc_info=True)
        if self._thread is not None and self._thread.is_alive():
            await asyncio.to_thread(self._thread.join, 5)
        await self._http.aclose()

    # --- inbound ---------------------------------------------------
    def _on_event(self, data: Any) -> None:
        try:
            msg = to_incoming(data)
        except Exception:
            log.exception("failed to normalize feishu event")
            return
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
        token = await self._access_token()
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
