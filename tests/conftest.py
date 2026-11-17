"""测试隔离：绝不读取仓库里的真实 .env。

服务器上 `/root/projects/agentd/.env` 是真凭证（还有 AGENTD_LLM_API_KEY）。
如果测试跑在那个目录下，`Settings()` 会把真 key 读进来 —— 轻则行为随环境漂移，
重则测试真的去调外部 API。所以这里把 `env_file` 指到一个不存在的临时路径，
并清掉进程里所有 `AGENTD_*` 环境变量。
"""

from __future__ import annotations

import os

import pytest

from agentd.config import Settings


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", str(tmp_path / "no-such.env"))
    for key in [k for k in os.environ if k.startswith("AGENTD_")]:
        monkeypatch.delenv(key, raising=False)
