"""FastAPI 外壳：只暴露探针端点，不承载任何业务入站流量。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status

from . import __version__
from .config import Settings
from .runtime import Runtime

log = logging.getLogger(__name__)


def create_app(runtime: Runtime | None = None) -> FastAPI:
    rt = runtime or Runtime(Settings())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await rt.start()
        try:
            yield
        finally:
            # uvicorn 收到 SIGTERM 后走到这里，10 秒内收尾
            await rt.stop()

    # 不挂 /docs：这套东西没有对外 API，少一个暴露面
    app = FastAPI(
        title="agentd",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.runtime = rt

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """进程活着就 200，不看依赖。"""
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(response: Response) -> dict[str, object]:
        """长连接与数据库都可用才 200。"""
        info = rt.readiness()
        if not info["ready"]:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return info

    return app
