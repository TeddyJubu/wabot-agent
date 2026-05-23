from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wabot_agent.api import _qr_svg, create_app
from wabot_agent.config import Settings
from wabot_agent.memory import MemoryStore
from wabot_agent.runtime_overrides import load_overrides, save_overrides


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp_path / "runtime_overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SEND_POLICY="dry_run",
        OPENROUTER_MODEL="openai/gpt-5.2",
        WABOT_INBOUND_TOKEN="inbound-secret",
        OPENROUTER_API_KEY=None,
        _env_file=None,
    )


def test_settings_accepts_legacy_vignesh_aliases(tmp_path: Path) -> None:
    settings = Settings(
        VIGNESH_OFFLINE_MODE=True,
        VIGNESH_DB_PATH=tmp_path / "legacy.db",
        VIGNESH_SEND_POLICY="dry_run",
        OPENROUTER_API_KEY=None,
    )

    assert settings.offline_mode is True
    assert settings.db_path == tmp_path / "legacy.db"
    assert settings.send_policy == "dry_run"


def test_health_and_ready(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))

    assert client.get("/health").json()["ok"] is True
    ready = client.get("/ready").json()
    assert ready["live_model"] is False
    assert ready["send_policy"] == "dry_run"


def test_pairing_restart_requires_wabot_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("WABOT_AGENT_WABOT_HOME", raising=False)
    monkeypatch.delenv("WABOT_AGENT_WABOT_RESTART_COMMAND", raising=False)
    settings = make_settings(tmp_path).model_copy(
        update={"wabot_home": None, "wabot_restart_command": None}
    )
    client = TestClient(create_app(settings))

    resp = client.post("/api/whatsapp/pairing/restart")

    assert resp.status_code == 503
    assert "WABOT_AGENT_WABOT_HOME" in resp.json()["detail"]


def test_pairing_restart_returns_fresh_qr(tmp_path: Path, monkeypatch) -> None:
    from wabot_agent.wabot import WabotPairingQR

    settings = make_settings(tmp_path).model_copy(
        update={"wabot_home": tmp_path / "wabot"}
    )
    client = TestClient(create_app(settings))

    async def fake_restart(_settings) -> None:
        return None

    async def fake_pairing_qr():
        return WabotPairingQR(
            supported=True,
            reachable=True,
            logged_in=False,
            connected=True,
            qr="fresh-code",
            event="code",
        )

    from wabot_agent import api

    monkeypatch.setattr(api, "restart_wabot_daemon", fake_restart)

    app = client.app
    wabot = app.state.wabot
    wabot.pairing_qr = fake_pairing_qr  # type: ignore[method-assign]

    resp = client.post("/api/whatsapp/pairing/restart")

    assert resp.status_code == 200
    assert resp.json()["qr_available"] is True


def test_pairing_disconnect_requires_wabot_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("WABOT_AGENT_WABOT_HOME", raising=False)
    monkeypatch.delenv("WABOT_AGENT_WABOT_RESTART_COMMAND", raising=False)
    settings = make_settings(tmp_path).model_copy(
        update={"wabot_home": None, "wabot_restart_command": None}
    )
    client = TestClient(create_app(settings))

    resp = client.post("/api/whatsapp/pairing/disconnect")

    assert resp.status_code == 503
    assert "WABOT_AGENT_WABOT_HOME" in resp.json()["detail"]


def test_pairing_disconnect_moves_store_and_returns_fresh_qr(
    tmp_path: Path, monkeypatch
) -> None:
    from wabot_agent.wabot import WabotPairingQR

    wabot_home = tmp_path / "wabot"
    wabot_home.mkdir()
    (wabot_home / "store.db").write_text("linked-session", encoding="utf-8")
    (wabot_home / "store.db-wal").write_text("wal", encoding="utf-8")
    settings = make_settings(tmp_path).model_copy(update={"wabot_home": wabot_home})
    client = TestClient(create_app(settings))

    async def fake_restart(_settings) -> None:
        return None

    async def fake_pairing_qr():
        return WabotPairingQR(
            supported=True,
            reachable=True,
            logged_in=False,
            connected=True,
            qr="fresh-code",
            event="code",
        )

    from wabot_agent import api

    monkeypatch.setattr(api, "restart_wabot_daemon", fake_restart)

    app = client.app
    wabot = app.state.wabot
    wabot.pairing_qr = fake_pairing_qr  # type: ignore[method-assign]

    resp = client.post("/api/whatsapp/pairing/disconnect")

    assert resp.status_code == 200
    body = resp.json()
    assert body["disconnected"] is True
    assert body["qr_available"] is True
    assert not (wabot_home / "store.db").exists()
    assert not (wabot_home / "store.db-wal").exists()
    assert body["store_backups"]
    assert list(wabot_home.glob("store.db.disconnected-*"))


def test_pairing_endpoint_reports_missing_token(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))

    pairing = client.get("/api/whatsapp/pairing")
    svg = client.get("/api/whatsapp/pairing.svg")

    assert pairing.status_code == 200
    assert pairing.json()["supported"] is True
    assert pairing.json()["qr_available"] is False
    assert svg.status_code == 404


def test_codex_disconnect_removes_auth_file_and_masks_bootstrap_token(
    tmp_path: Path,
) -> None:
    from wabot_agent.codex_auth import load_codex_credentials

    auth_path = tmp_path / "codex" / "auth.json"
    auth_path.parent.mkdir()
    auth_path.write_text(
        '{"auth_mode":"chatgpt","tokens":{"access_token":"file-token"}}',
        encoding="utf-8",
    )
    overrides_path = tmp_path / "runtime_overrides.json"
    save_overrides(
        overrides_path,
        {"codex_access_token": "override-token", "codex_account_id": "acct-1"},
    )
    settings = make_settings(tmp_path).model_copy(
        update={
            "model_provider": "codex",
            "codex_auth_path": auth_path,
            "codex_access_token": "bootstrap-token",
            "codex_account_id": "bootstrap-acct",
            "runtime_overrides_path": overrides_path,
        }
    )
    client = TestClient(create_app(settings))

    resp = client.post("/api/codex/login/disconnect")

    assert resp.status_code == 200
    body = resp.json()
    assert body["logged_in"] is False
    assert body["disconnected"] is True
    assert body["auth_file_removed"] is True
    assert not auth_path.exists()
    overrides = load_overrides(overrides_path)
    assert overrides["codex_access_token"] is None
    assert overrides["codex_account_id"] is None
    assert load_codex_credentials(settings) is None


def test_qr_svg_renderer() -> None:
    svg = _qr_svg("pairing-code")

    assert svg.startswith(b"<?xml")
    assert b"<svg" in svg
    assert b'fill="white"' in svg


def test_operator_endpoints_require_token_when_configured(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "operator-secret"})
    client = TestClient(create_app(settings))

    assert client.get("/ready").status_code == 401
    ok = client.get("/ready", headers={"X-Operator-Token": "operator-secret"})
    assert ok.status_code == 200


def test_dashboard_token_sets_operator_cookie(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "operator-secret"})
    client = TestClient(create_app(settings))

    denied = client.get("/", follow_redirects=False)
    allowed = client.get("/?token=operator-secret")
    ready = client.get("/ready")

    assert denied.status_code == 302
    assert denied.headers["location"] == "/login?next=/"
    assert allowed.status_code == 200
    assert ready.status_code == 200


def test_runs_limit_rejects_negative_values(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))

    assert client.get("/api/runs?limit=-1").status_code == 422


def test_inbound_requires_token(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))
    payload = {"id": "msg-1", "from": "+15550001111", "text": "hello"}

    assert client.post("/whatsapp/inbound", json=payload).status_code == 401


def test_requires_inbound_token_production_env(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(
        update={"env": "production", "wabot_inbound_token": None}
    )
    with pytest.raises(RuntimeError, match="WABOT_INBOUND_TOKEN"):
        create_app(settings)


def test_inbound_open_on_local_loopback_without_token(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(
        update={"wabot_inbound_token": None, "env": "local", "host": "127.0.0.1"}
    )
    client = TestClient(create_app(settings))
    payload = {"id": "msg-open-1", "from": "+15550001111", "text": "hello"}

    assert client.post("/whatsapp/inbound", json=payload).status_code == 200


def test_receipt_webhook_requires_token(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))
    payload = {
        "chat": "15550001111@s.whatsapp.net",
        "message_ids": ["abc"],
        "receipt_type": "read",
    }
    assert client.post("/whatsapp/receipt", json=payload).status_code == 401


def test_receipt_webhook_accepted(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))
    payload = {
        "chat": "15550001111@s.whatsapp.net",
        "message_ids": ["abc"],
        "receipt_type": "read",
        "timestamp": "2026-05-16T12:00:00Z",
    }
    headers = {"Authorization": "Bearer inbound-secret"}
    resp = client.post("/whatsapp/receipt", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True


def test_history_batch_stores_without_agent_run(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))
    payload = {
        "type": "history_batch",
        "sync_type": "RECENT",
        "messages": [
            {
                "id": "hist-1",
                "from": "+15550001111",
                "chat": "+15550001111",
                "text": "old message",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        ],
    }
    headers = {"Authorization": "Bearer inbound-secret"}
    resp = client.post("/whatsapp/history", json=payload, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    assert body["stored"] == 1
    # History rows must not be claimed for auto-reply.
    settings = make_settings(tmp_path)
    memory = MemoryStore(settings.db_path)
    assert memory.is_processed("hist-1") is False
    last = memory.last_inbound()
    assert last is not None
    assert last["id"] == "hist-1"


def test_history_sync_summary_accepted(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))
    payload = {
        "type": "history_sync",
        "sync_type": "INITIAL_BOOTSTRAP",
        "conversation_count": 3,
        "message_count": 120,
        "chunk_order": 1,
        "progress": 40,
    }
    headers = {"Authorization": "Bearer inbound-secret"}
    resp = client.post("/whatsapp/history-sync", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True


def test_presence_webhook_accepted(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))
    payload = {
        "chat": "15550001111@s.whatsapp.net",
        "sender": "15550002222@s.whatsapp.net",
        "state": "composing",
    }
    headers = {"Authorization": "Bearer inbound-secret"}
    resp = client.post("/whatsapp/presence", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True


def test_inbound_is_idempotent(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))
    payload = {"id": "msg-1", "from": "+15550001111", "text": "hello"}
    headers = {"Authorization": "Bearer inbound-secret"}

    first = client.post("/whatsapp/inbound", json=payload, headers=headers)
    second = client.post("/whatsapp/inbound", json=payload, headers=headers)

    assert first.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True


def test_settings_get_masks_secrets(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(
        update={"openrouter_api_key": "sk-or-v1-abcdefghij1234567890"}
    )
    client = TestClient(create_app(settings))

    view = client.get("/api/settings").json()
    api_key = view["openrouter"]["api_key"]
    assert api_key["set"] is True
    assert api_key["preview"].startswith("sk-o")
    assert api_key["preview"].endswith("7890")
    # The raw key must never appear in the response.
    assert "abcdefghij1234567890" not in client.get("/api/settings").text


def test_settings_patch_updates_send_policy_and_persists(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(
        update={"runtime_overrides_path": tmp_path / "overrides.json"}
    )
    client = TestClient(create_app(settings))

    resp = client.patch(
        "/api/settings",
        json={"send_policy": "allowlist", "allowed_recipients": ["+15550001111"]},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["send_policy"] == "allowlist"
    assert body["allowed_recipients"] == ["+15550001111"]

    # File on disk reflects the change.
    import json

    written = json.loads((tmp_path / "overrides.json").read_text())
    assert written["send_policy"] == "allowlist"
    assert written["allowed_recipients"] == ["+15550001111"]


def test_settings_patch_allow_all_requires_confirmation(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(
        update={"runtime_overrides_path": tmp_path / "overrides.json"}
    )
    client = TestClient(create_app(settings))

    blocked = client.patch("/api/settings", json={"send_policy": "allow_all"})
    assert blocked.status_code == 400

    allowed = client.patch(
        "/api/settings",
        json={"send_policy": "allow_all", "confirm_allow_all": True},
    )
    assert allowed.status_code == 200
    assert allowed.json()["send_policy"] == "allow_all"


def test_runtime_overrides_apply_on_startup(tmp_path: Path) -> None:
    import json

    overrides_path = tmp_path / "overrides.json"
    overrides_path.write_text(
        json.dumps({"openrouter_model": "anthropic/claude-haiku", "send_policy": "allowlist"})
    )

    settings = make_settings(tmp_path).model_copy(
        update={"runtime_overrides_path": overrides_path}
    )
    client = TestClient(create_app(settings))

    view = client.get("/api/settings").json()
    assert view["openrouter"]["model"] == "anthropic/claude-haiku"
    assert view["send_policy"] == "allowlist"


def test_openrouter_test_endpoint_uses_openrouter_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured["request"] = kwargs
            return type(
                "Completion",
                (),
                {
                    "choices": [
                        type(
                            "Choice",
                            (),
                            {"message": type("Message", (), {"content": "ok"})()},
                        )()
                    ]
                },
            )()

    class FakeAsyncOpenAI:
        def __init__(self, *, api_key: str, base_url: str, default_headers: dict[str, str]):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            captured["default_headers"] = default_headers
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("openai.AsyncOpenAI", FakeAsyncOpenAI)
    settings = make_settings(tmp_path).model_copy(
        update={
            "model_provider": "codex",
            "openrouter_api_key": None,
            "runtime_overrides_path": tmp_path / "overrides.json",
        }
    )
    client = TestClient(create_app(settings))

    resp = client.post(
        "/api/settings/test/openrouter",
        json={
            "api_key": "sk-or-test",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "openai/gpt-4.1-mini",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert captured["api_key"] == "sk-or-test"
    assert captured["base_url"] == "https://openrouter.ai/api/v1"
    assert captured["request"]["model"] == "openai/gpt-4.1-mini"  # type: ignore[index]
    headers = captured["default_headers"]
    assert isinstance(headers, dict)
    assert headers["HTTP-Referer"] == settings.openrouter_site_url
    assert headers["X-OpenRouter-Title"] == settings.openrouter_app_title
    assert settings.model_provider == "codex"
    assert settings.openrouter_api_key is None
    assert not (tmp_path / "overrides.json").exists()


def test_openai_test_endpoint_uses_openai_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured["request"] = kwargs
            return type(
                "Completion",
                (),
                {
                    "choices": [
                        type(
                            "Choice",
                            (),
                            {"message": type("Message", (), {"content": "ok"})()},
                        )()
                    ]
                },
            )()

    class FakeAsyncOpenAI:
        def __init__(self, *, api_key: str, base_url: str):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("openai.AsyncOpenAI", FakeAsyncOpenAI)
    settings = make_settings(tmp_path).model_copy(
        update={
            "model_provider": "openrouter",
            "openai_api_key": None,
            "runtime_overrides_path": tmp_path / "overrides.json",
        }
    )
    client = TestClient(create_app(settings))

    resp = client.post(
        "/api/settings/test/openai",
        json={
            "api_key": "sk-openai-test",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4.1-mini",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert captured["api_key"] == "sk-openai-test"
    assert captured["base_url"] == "https://api.openai.com/v1"
    assert captured["request"]["model"] == "gpt-4.1-mini"  # type: ignore[index]
    assert settings.model_provider == "openrouter"
    assert settings.openai_api_key is None
    assert not (tmp_path / "overrides.json").exists()


def test_settings_patch_can_switch_dashboard_to_openai(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(
        update={
            "model_provider": "openrouter",
            "runtime_overrides_path": tmp_path / "overrides.json",
        }
    )
    client = TestClient(create_app(settings))

    resp = client.patch(
        "/api/settings",
        json={
            "model_provider": "openai",
            "openai_api_key": "sk-openai-new",
            "openai_model": "gpt-4.1-mini",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["llm"]["provider"] == "openai"
    assert body["openai"]["api_key"]["set"] is True
    assert settings.model_provider == "openai"


def test_settings_patch_can_switch_dashboard_to_openrouter(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(
        update={
            "model_provider": "codex",
            "runtime_overrides_path": tmp_path / "overrides.json",
        }
    )
    client = TestClient(create_app(settings))

    resp = client.patch(
        "/api/settings",
        json={
            "model_provider": "openrouter",
            "openrouter_api_key": "sk-or-new",
            "openrouter_model": "openai/gpt-4.1-mini",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["llm"]["provider"] == "openrouter"
    assert body["openrouter"]["api_key"]["set"] is True
    assert settings.model_provider == "openrouter"


def test_settings_patch_rejects_non_loopback_wabot_endpoint(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(
        update={"runtime_overrides_path": tmp_path / "overrides.json"}
    )
    client = TestClient(create_app(settings))
    original_endpoint = settings.wabot_endpoint

    bad = client.patch("/api/settings", json={"wabot_endpoint": "http://evil.example.com:7777"})

    assert bad.status_code == 400
    assert "loopback" in bad.json()["detail"]
    # Live settings unchanged.
    assert settings.wabot_endpoint == original_endpoint
    assert not (tmp_path / "overrides.json").exists()


def test_settings_patch_rejects_plain_http_remote_openrouter(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(
        update={"runtime_overrides_path": tmp_path / "overrides.json"}
    )
    client = TestClient(create_app(settings))

    resp = client.patch(
        "/api/settings",
        json={
            "openrouter_base_url": "http://attacker.example.com/v1",
            "openrouter_api_key": "sk-test",
        },
    )

    assert resp.status_code == 400
    assert "https" in resp.json()["detail"].lower()


def test_settings_patch_rejects_plain_http_remote_openai(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(
        update={"runtime_overrides_path": tmp_path / "overrides.json"}
    )
    client = TestClient(create_app(settings))

    resp = client.patch(
        "/api/settings",
        json={
            "openai_base_url": "http://attacker.example.com/v1",
            "openai_api_key": "sk-test",
        },
    )

    assert resp.status_code == 400
    assert "https" in resp.json()["detail"].lower()


def test_settings_patch_base_url_change_requires_new_key(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(
        update={
            "runtime_overrides_path": tmp_path / "overrides.json",
            "openrouter_api_key": "sk-old-key",
        }
    )
    client = TestClient(create_app(settings))

    blocked = client.patch(
        "/api/settings",
        json={"openrouter_base_url": "https://elsewhere.example.com/v1"},
    )
    assert blocked.status_code == 400
    assert "openrouter_api_key" in blocked.json()["detail"]
    # Live and on-disk state unchanged.
    assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert settings.openrouter_api_key == "sk-old-key"

    allowed = client.patch(
        "/api/settings",
        json={
            "openrouter_base_url": "https://elsewhere.example.com/v1",
            "openrouter_api_key": "sk-new-key",
        },
    )
    assert allowed.status_code == 200
    assert allowed.json()["openrouter"]["base_url"] == "https://elsewhere.example.com/v1"


def test_settings_patch_atomicity_invalid_field_leaves_state_clean(tmp_path: Path) -> None:
    """A patch that fails validation must not mutate live settings or write to disk."""
    overrides_path = tmp_path / "overrides.json"
    settings = make_settings(tmp_path).model_copy(
        update={"runtime_overrides_path": overrides_path}
    )
    client = TestClient(create_app(settings))
    original_policy = settings.send_policy

    bad = client.patch(
        "/api/settings",
        # send_policy is a Literal — "garbage" should fail validation on the snapshot
        # before anything is written to disk or applied to live settings.
        json={"send_policy": "garbage"},
    )

    assert bad.status_code == 400
    assert settings.send_policy == original_policy
    assert not overrides_path.exists()


def test_chat_stream_emits_ndjson_final_event(tmp_path: Path) -> None:
    """Offline-mode streaming chat must complete with a final event and
    an NDJSON content type. We exercise the fallback (Runner.run -> single
    delta + final) since OfflineModel doesn't implement stream_response."""
    import json as _json

    client = TestClient(create_app(make_settings(tmp_path)))

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "hello", "session_id": "test-stream"},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/x-ndjson")
        events: list[dict] = []
        buffer = ""
        for chunk in resp.iter_text():
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if line:
                    events.append(_json.loads(line))

    assert events, "expected at least one event"
    # The fallback path emits a synthetic delta with the entire echo response,
    # then a final event with the run summary.
    types = [e["type"] for e in events]
    assert types[-1] == "final"
    final = events[-1]
    assert final["live_model"] is False
    assert "Offline mode is active" in final["output"]
    assert final["session_id"] == "test-stream"
    assert final["run_id"]
    # And a delta carrying the same text.
    deltas = [e for e in events if e["type"] == "delta"]
    assert deltas, "expected at least one delta event"
    assert any("Offline mode is active" in d["text"] for d in deltas)


def test_chat_stream_requires_operator_token_when_configured(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "operator-secret"})
    client = TestClient(create_app(settings))

    denied = client.post("/api/chat/stream", json={"message": "hi"})
    assert denied.status_code == 401


def test_startup_ignores_invalid_overrides_atomically(tmp_path: Path) -> None:
    """A stale overrides file with one bad field must not partially mutate Settings."""
    import json

    overrides_path = tmp_path / "overrides.json"
    overrides_path.write_text(
        json.dumps({"openrouter_model": "anthropic/claude-haiku", "send_policy": "garbage"})
    )

    settings = make_settings(tmp_path).model_copy(
        update={"runtime_overrides_path": overrides_path}
    )
    # Should boot cleanly, ignoring the file entirely (not half-applying it).
    client = TestClient(create_app(settings))
    view = client.get("/api/settings").json()

    assert view["send_policy"] == "dry_run"  # original env value preserved
    assert view["openrouter"]["model"] == "openai/gpt-5.2"  # not partially applied
