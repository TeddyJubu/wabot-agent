from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from wabot_agent.api import _qr_svg, create_app
from wabot_agent.config import Settings


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SEND_POLICY="dry_run",
        WABOT_INBOUND_TOKEN="inbound-secret",
        OPENROUTER_API_KEY=None,
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


def test_pairing_endpoint_reports_missing_token(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))

    pairing = client.get("/api/whatsapp/pairing")
    svg = client.get("/api/whatsapp/pairing.svg")

    assert pairing.status_code == 200
    assert pairing.json()["supported"] is True
    assert pairing.json()["qr_available"] is False
    assert svg.status_code == 404


def test_qr_svg_renderer() -> None:
    svg = _qr_svg("pairing-code")

    assert svg.startswith(b"<?xml")
    assert b"<svg" in svg
    assert b"path" in svg


def test_operator_endpoints_require_token_when_configured(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "operator-secret"})
    client = TestClient(create_app(settings))

    assert client.get("/ready").status_code == 401
    ok = client.get("/ready", headers={"X-Operator-Token": "operator-secret"})
    assert ok.status_code == 200


def test_dashboard_token_sets_operator_cookie(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "operator-secret"})
    client = TestClient(create_app(settings))

    denied = client.get("/")
    allowed = client.get("/?token=operator-secret")
    ready = client.get("/ready")

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert ready.status_code == 200


def test_runs_limit_rejects_negative_values(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))

    assert client.get("/api/runs?limit=-1").status_code == 422


def test_inbound_requires_token(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))
    payload = {"id": "msg-1", "from": "+15550001111", "text": "hello"}

    assert client.post("/whatsapp/inbound", json=payload).status_code == 401


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
