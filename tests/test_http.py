from __future__ import annotations

from pathlib import Path

from agentd.app import create_app
from agentd.channel.mock import MockChannel
from agentd.config import Settings
from agentd.runtime import Runtime
from fastapi.testclient import TestClient


def test_healthz_and_readyz(tmp_path: Path) -> None:
    runtime = Runtime(Settings(env="dev", db_path=tmp_path / "http.db"), channel=MockChannel())

    with TestClient(create_app(runtime)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}

        response = client.get("/readyz")

        assert response.status_code == 200
        assert response.json()["ready"] is True
        assert response.json()["channel"] == "mock"


def test_readyz_returns_503_when_channel_drops(tmp_path: Path) -> None:
    channel = MockChannel()
    runtime = Runtime(Settings(env="dev", db_path=tmp_path / "http2.db"), channel=channel)

    with TestClient(create_app(runtime)) as client:
        channel._connected = False

        response = client.get("/readyz")

        assert response.status_code == 503
        assert "mock" in response.json()["not_ready"]
