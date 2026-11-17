"""运行时配置：全部来自环境变量，支持 AGENTD_ 前缀与 _FILE 变体。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "dev"
    log_level: str = "INFO"

    http_host: str = "0.0.0.0"
    http_port: int = 8080

    # 飞书自建应用
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_app_secret_file: Path | None = None
    feishu_domain: str = "https://open.feishu.cn"

    # 空白名单 + dev = 放行；空白名单 + prod = 全拒
    # NoDecode: 环境变量按逗号分隔手写，不要 pydantic-settings 先按 JSON 解析
    allowed_senders: Annotated[list[str], NoDecode] = Field(default_factory=list)

    db_path: Path = Path("data/agentd.db")

    @field_validator("allowed_senders", mode="before")
    @classmethod
    def _split_senders(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def app_secret(self) -> str:
        """优先读 Secret 文件（k8s 挂载方式），其次读环境变量。"""
        if self.feishu_app_secret_file is not None:
            return self.feishu_app_secret_file.read_text(encoding="utf-8").strip()
        return self.feishu_app_secret

    @property
    def feishu_configured(self) -> bool:
        return bool(self.feishu_app_id and self.app_secret)

    @property
    def allow_all_senders(self) -> bool:
        return not self.allowed_senders and self.env != "prod"

    def is_allowed(self, sender_id: str) -> bool:
        if sender_id in self.allowed_senders:
            return True
        return self.allow_all_senders


def stray_env_keys(path: Path | str | None = None) -> list[str]:
    """列出 .env 里没带 AGENTD_ 前缀的键。

    踩过的坑：把 `.env` 写成 `Feishu_APP_ID=...`，pydantic-settings 按 `AGENTD_`
    前缀去找，一个都读不到，于是静默降级成 mock 通道 —— 长连接压根没连。
    """
    p = Path(path or Settings.model_config.get("env_file", ".env"))
    if not p.is_file():
        return []
    keys: list[str] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, _value = line.partition("=")
        key = key.strip()
        if key and not key.startswith("AGENTD_"):
            keys.append(key)
    return keys
