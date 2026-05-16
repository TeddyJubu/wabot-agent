from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from wabot_agent.api import create_app
from wabot_agent.config import Settings


def _make_settings(tmp_path: Path, **overrides) -> Settings:
    base = dict(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_MEDIA_DIR=tmp_path / "media",
        WABOT_AGENT_OPERATOR_TOKEN="operator-secret",
        WABOT_AGENT_DASHBOARD_PASSWORD="easy-pin",
    )
    base.update(overrides)
    return Settings(**base)


def test_unauthenticated_dashboard_redirects_to_login(tmp_path: Path) -> None:
    client = TestClient(create_app(_make_settings(tmp_path)))
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login?next=/"


def test_login_page_renders_without_auth(tmp_path: Path) -> None:
    client = TestClient(create_app(_make_settings(tmp_path)))
    r = client.get("/login")
    assert r.status_code == 200
    assert "wabot dashboard" in r.text
    assert 'name="password"' in r.text


def test_login_with_dashboard_password_sets_cookie(tmp_path: Path) -> None:
    client = TestClient(create_app(_make_settings(tmp_path)))
    r = client.post(
        "/api/auth/login",
        data={"password": "easy-pin", "next": "/"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert "wabot_agent_operator_token=operator-secret" in r.headers.get("set-cookie", "")


def test_login_wrong_password_returns_401(tmp_path: Path) -> None:
    client = TestClient(create_app(_make_settings(tmp_path)))
    r = client.post("/api/auth/login", data={"password": "nope", "next": "/"})
    assert r.status_code == 401
    assert "Wrong password" in r.text


def test_authenticated_dashboard_after_login(tmp_path: Path) -> None:
    client = TestClient(create_app(_make_settings(tmp_path)))
    client.post("/api/auth/login", data={"password": "easy-pin", "next": "/"})
    r = client.get("/")
    assert r.status_code in {200, 404}  # 404 when static/ not built in tests
