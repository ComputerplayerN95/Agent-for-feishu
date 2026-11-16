"""命令行入口：agentd {serve,migrate,version}。"""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__
from .config import Settings


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        stream=sys.stdout,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentd", description="飞书 Agent 守护进程")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="启动长连接与健康检查端点")
    sub.add_parser("migrate", help="初始化 SQLite 表结构后退出（幂等）")
    sub.add_parser("version", help="打印版本并退出")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "version":
        print(f"agentd {__version__}")
        return 0

    settings = Settings()
    _configure_logging(settings.log_level)

    if args.command == "migrate":
        from .store import Store

        store = Store(settings.db_path)
        store.connect()
        store.close()
        print(f"migrate: ok ({settings.db_path})")
        return 0

    import uvicorn

    from .app import create_app
    from .runtime import Runtime

    runtime = Runtime(settings)
    uvicorn.run(
        create_app(runtime),
        host=settings.http_host,
        port=settings.http_port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
