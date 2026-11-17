from __future__ import annotations

from pathlib import Path

from agentd.config import Settings, stray_env_keys


def test_allowed_senders_parsed_from_comma_string(monkeypatch) -> None:
    monkeypatch.setenv("AGENTD_ALLOWED_SENDERS", "ou_1, ou_2 ,")
    settings = Settings()
    assert settings.allowed_senders == ["ou_1", "ou_2"]


def test_secret_prefers_file(tmp_path: Path) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_text("file-secret\n", encoding="utf-8")
    settings = Settings(
        feishu_app_id="cli_x",
        feishu_app_secret="env-secret",
        feishu_app_secret_file=secret_file,
    )
    assert settings.app_secret == "file-secret"
    assert settings.feishu_configured is True


def test_dev_without_whitelist_is_open() -> None:
    settings = Settings(env="dev")
    assert settings.allow_all_senders is True
    assert settings.is_allowed("ou_anyone") is True


def test_prod_without_whitelist_is_closed() -> None:
    settings = Settings(env="prod")
    assert settings.allow_all_senders is False
    assert settings.is_allowed("ou_anyone") is False


def test_whitelist_wins_in_prod() -> None:
    settings = Settings(env="prod", allowed_senders=["ou_me"])
    assert settings.is_allowed("ou_me") is True
    assert settings.is_allowed("ou_other") is False


def test_stray_env_keys_flags_missing_prefix(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# comment\n\nAGENTD_FEISHU_APP_ID=cli_ok\nFeishu_APP_SECRET=oops\nDEEPSEEK_API=0\n",
        encoding="utf-8",
    )
    assert stray_env_keys(env) == ["Feishu_APP_SECRET", "DEEPSEEK_API"]


def test_stray_env_keys_missing_file() -> None:
    assert stray_env_keys("/nonexistent/.env") == []
