"""Tests for the `/pair` route and `verify_human` dependency.

Covers the Cloudflare Access path, the operator-token fallback path, and
the security invariants the architect flagged:

- Operator Bearer token alone MUST NOT bypass CF Access when required.
- Misconfiguration (`cf_access_required=True` but no team_domain) returns 401.
- `/whatsapp/inbound` is untouched by CF Access settings.
- Existing operator-token paths still work when CF Access is disabled.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from wabot_agent.api import create_app
from wabot_agent.cf_access import clear_jwks_cache
from wabot_agent.config import Settings


@pytest.fixture(autouse=True)
def _clear_jwks_cache():
    clear_jwks_cache()
    yield
    clear_jwks_cache()


@pytest.fixture
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def kid() -> str:
    return "test-kid-1"


def _b64uint(n: int) -> str:
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _jwks_for(key: rsa.RSAPrivateKey, kid: str) -> dict:
    pub = key.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": kid,
                "use": "sig",
                "alg": "RS256",
                "n": _b64uint(pub.n),
                "e": _b64uint(pub.e),
            }
        ]
    }


def _mint(
    key: rsa.RSAPrivateKey,
    kid: str,
    *,
    aud: str = "test-aud",
    iss: str = "https://example.cloudflareaccess.com",
    email: str = "op@example.com",
) -> str:
    now = int(time.time())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(
        {
            "aud": aud,
            "iss": iss,
            "email": email,
            "sub": "sub-1",
            "iat": now,
            "exp": now + 300,
        },
        pem,
        algorithm="RS256",
        headers={"kid": kid},
    )


def _make_settings(tmp_path: Path, **overrides) -> Settings:
    base = dict(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SEND_POLICY="dry_run",
        WABOT_INBOUND_TOKEN="inbound-secret",
        OPENROUTER_API_KEY=None,
    )
    base.update(overrides)
    return Settings(**base)


def _patch_jwks(monkeypatch, jwks: dict) -> None:
    from wabot_agent import cf_access

    def fake_fetcher(team_domain: str) -> dict:
        return jwks

    monkeypatch.setattr(cf_access, "_default_fetcher", fake_fetcher)


# --- Static SPA shell ------------------------------------------------------


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "static" / "index.html").exists(),
    reason="static/index.html missing; run scripts/build-web.sh first",
)
def test_pair_serves_spa_shell_in_local_dev(tmp_path: Path) -> None:
    """When neither CF Access nor operator_token is configured, /pair serves
    the SPA shell to anyone (matching today's `/` behavior in local dev)."""
    client = TestClient(create_app(_make_settings(tmp_path)))
    r = client.get("/pair")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


# --- Cloudflare Access required mode --------------------------------------


def test_pair_requires_access_when_required(
    tmp_path: Path, monkeypatch, rsa_key, kid
) -> None:
    _patch_jwks(monkeypatch, _jwks_for(rsa_key, kid))
    settings = _make_settings(
        tmp_path,
        WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN="example.cloudflareaccess.com",
        WABOT_AGENT_CF_ACCESS_AUD="test-aud",
        WABOT_AGENT_CF_ACCESS_REQUIRED=True,
    )
    client = TestClient(create_app(settings))

    assert client.get("/pair").status_code == 401


def test_pair_accepts_valid_access_jwt(
    tmp_path: Path, monkeypatch, rsa_key, kid
) -> None:
    _patch_jwks(monkeypatch, _jwks_for(rsa_key, kid))
    settings = _make_settings(
        tmp_path,
        WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN="example.cloudflareaccess.com",
        WABOT_AGENT_CF_ACCESS_AUD="test-aud",
        WABOT_AGENT_CF_ACCESS_REQUIRED=True,
    )
    client = TestClient(create_app(settings))
    token = _mint(rsa_key, kid)

    r = client.get("/pair", headers={"Cf-Access-Jwt-Assertion": token})
    # Either 200 (if static shell present) or 404 (if not built yet).
    # Either way, NOT 401 — auth succeeded.
    assert r.status_code in (200, 404)


def test_pair_mints_operator_cookie_on_access_when_token_configured(
    tmp_path: Path, monkeypatch, rsa_key, kid
) -> None:
    _patch_jwks(monkeypatch, _jwks_for(rsa_key, kid))
    settings = _make_settings(
        tmp_path,
        WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN="example.cloudflareaccess.com",
        WABOT_AGENT_CF_ACCESS_AUD="test-aud",
        WABOT_AGENT_CF_ACCESS_REQUIRED=True,
        WABOT_AGENT_OPERATOR_TOKEN="op-secret",
    )
    client = TestClient(create_app(settings))
    token = _mint(rsa_key, kid)

    r = client.get("/pair", headers={"Cf-Access-Jwt-Assertion": token})
    # We don't care about 200 vs 404 (static shell may not be built yet).
    assert r.status_code in (200, 404)
    set_cookie = r.headers.get("set-cookie", "")
    assert "wabot_agent_operator_token=op-secret" in set_cookie
    assert "HttpOnly".lower() in set_cookie.lower()
    assert "samesite=strict" in set_cookie.lower()


def test_operator_bearer_alone_rejected_when_cf_required(
    tmp_path: Path, monkeypatch, rsa_key, kid
) -> None:
    """Operator Bearer MUST NOT bypass CF Access when required."""
    _patch_jwks(monkeypatch, _jwks_for(rsa_key, kid))
    settings = _make_settings(
        tmp_path,
        WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN="example.cloudflareaccess.com",
        WABOT_AGENT_CF_ACCESS_AUD="test-aud",
        WABOT_AGENT_CF_ACCESS_REQUIRED=True,
        WABOT_AGENT_OPERATOR_TOKEN="op-secret",
    )
    client = TestClient(create_app(settings))
    r = client.get("/pair", headers={"Authorization": "Bearer op-secret"})
    assert r.status_code == 401


def test_cf_required_but_no_team_domain_returns_401(tmp_path: Path) -> None:
    """Misconfiguration produces a clean 401, not a 500."""
    settings = _make_settings(
        tmp_path,
        WABOT_AGENT_CF_ACCESS_REQUIRED=True,
        WABOT_AGENT_CF_ACCESS_AUD="test-aud",
        # team_domain intentionally omitted
    )
    client = TestClient(create_app(settings))
    r = client.get(
        "/pair", headers={"Cf-Access-Jwt-Assertion": "anything"}
    )
    assert r.status_code == 401


def test_api_routes_reject_when_access_required_and_missing(
    tmp_path: Path,
) -> None:
    settings = _make_settings(
        tmp_path,
        WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN="example.cloudflareaccess.com",
        WABOT_AGENT_CF_ACCESS_AUD="test-aud",
        WABOT_AGENT_CF_ACCESS_REQUIRED=True,
    )
    client = TestClient(create_app(settings))
    assert client.get("/api/whatsapp/pairing").status_code == 401
    assert client.get("/api/runs").status_code == 401
    assert client.get("/api/settings").status_code == 401


# --- Inbound webhook untouched --------------------------------------------


def test_inbound_unaffected_by_cf_access(
    tmp_path: Path, monkeypatch, rsa_key, kid
) -> None:
    _patch_jwks(monkeypatch, _jwks_for(rsa_key, kid))
    settings = _make_settings(
        tmp_path,
        WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN="example.cloudflareaccess.com",
        WABOT_AGENT_CF_ACCESS_AUD="test-aud",
        WABOT_AGENT_CF_ACCESS_REQUIRED=True,
    )
    client = TestClient(create_app(settings))
    payload = {"id": "msg-cf-1", "from": "+15550001111", "text": "hello"}

    # Without inbound token: 401, even with CF Access in play.
    denied = client.post("/whatsapp/inbound", json=payload)
    assert denied.status_code == 401

    # With inbound token alone (no CF Access JWT): accepted. CF Access does
    # NOT protect this endpoint — wabot calls it on loopback.
    ok = client.post(
        "/whatsapp/inbound",
        json=payload,
        headers={"Authorization": "Bearer inbound-secret"},
    )
    assert ok.status_code == 200
    assert ok.json()["accepted"] is True


# --- /health remains public -----------------------------------------------


def test_health_remains_public_with_cf_access(tmp_path: Path) -> None:
    settings = _make_settings(
        tmp_path,
        WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN="example.cloudflareaccess.com",
        WABOT_AGENT_CF_ACCESS_AUD="test-aud",
        WABOT_AGENT_CF_ACCESS_REQUIRED=True,
    )
    client = TestClient(create_app(settings))
    assert client.get("/health").json()["ok"] is True


# --- Legacy operator-token mode unchanged ---------------------------------


def test_existing_operator_token_path_still_works(tmp_path: Path) -> None:
    """When cf_access_required=False, operator token semantics unchanged."""
    settings = _make_settings(tmp_path, WABOT_AGENT_OPERATOR_TOKEN="op-secret")
    client = TestClient(create_app(settings))
    assert client.get("/api/runs").status_code == 401
    ok = client.get("/api/runs", headers={"X-Operator-Token": "op-secret"})
    assert ok.status_code == 200


def test_cf_access_fields_not_runtime_mutable(tmp_path: Path) -> None:
    """An operator session MUST NOT be able to disable CF Access via the API.

    Even though the SettingsPatch model currently doesn't expose cf_access_*
    fields, the MUTABLE_FIELDS allowlist is the security-critical guard —
    confirm those three fields aren't in it.
    """
    from wabot_agent.runtime_overrides import MUTABLE_FIELDS

    assert "cf_access_required" not in MUTABLE_FIELDS
    assert "cf_access_team_domain" not in MUTABLE_FIELDS
    assert "cf_access_aud" not in MUTABLE_FIELDS


def test_minted_cookie_is_secure_when_cf_access_required(
    tmp_path: Path, monkeypatch, rsa_key, kid
) -> None:
    """Defence-in-depth: the operator cookie must carry Secure=True when CF
    Access is enforcing HTTPS at the edge, so it's refused if the FastAPI
    port is ever inadvertently exposed over plain HTTP."""
    _patch_jwks(monkeypatch, _jwks_for(rsa_key, kid))
    settings = _make_settings(
        tmp_path,
        WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN="example.cloudflareaccess.com",
        WABOT_AGENT_CF_ACCESS_AUD="test-aud",
        WABOT_AGENT_CF_ACCESS_REQUIRED=True,
        WABOT_AGENT_OPERATOR_TOKEN="op-secret",
    )
    client = TestClient(create_app(settings))
    token = _mint(rsa_key, kid)

    r = client.get("/pair", headers={"Cf-Access-Jwt-Assertion": token})
    set_cookie = r.headers.get("set-cookie", "")
    assert "secure" in set_cookie.lower()


def test_minted_cookie_is_not_secure_in_legacy_mode(tmp_path: Path) -> None:
    """In legacy operator-token mode the cookie is minted over loopback HTTP
    in local dev, so Secure must stay False to avoid breaking the bootstrap."""
    settings = _make_settings(
        tmp_path,
        WABOT_AGENT_OPERATOR_TOKEN="op-secret",
    )
    client = TestClient(create_app(settings))

    # ?token=… bootstrap path triggers the cookie mint.
    r = client.get("/?token=op-secret")
    set_cookie = r.headers.get("set-cookie", "")
    assert "wabot_agent_operator_token=op-secret" in set_cookie
    # Secure is absent (or False).
    assert "secure" not in set_cookie.lower()
