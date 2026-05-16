from __future__ import annotations

import hashlib
import json
import logging
from io import StringIO

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from wabot_agent.auth import AuthIdentity, verify_human_factory
from wabot_agent.config import Settings
from wabot_agent.logging_config import ContextVarsFilter, JsonFormatter
from wabot_agent.middleware import RequestIdMiddleware


@pytest.fixture()
def capture_auth_logs():
    buf = StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextVarsFilter())
    logger = logging.getLogger("wabot_agent.auth")
    saved = list(logger.handlers)
    saved_level = logger.level
    saved_propagate = logger.propagate
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    yield buf
    logger.handlers.clear()
    for h in saved:
        logger.addHandler(h)
    logger.setLevel(saved_level)
    logger.propagate = saved_propagate


def _lines(buf: StringIO) -> list[dict]:
    return [json.loads(line) for line in buf.getvalue().strip().splitlines() if line]


def _client_with_auth(operator_token: str | None = None) -> TestClient:
    settings = Settings(
        operator_token=operator_token,
        cf_access_required=False,
    )
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    dep = verify_human_factory(settings)

    @app.get("/secret")
    async def secret(identity: AuthIdentity = Depends(dep)):  # noqa: B008
        return {"ok": True, "source": identity.source}

    return TestClient(app)


def test_auth_success_logs_auth_login_for_header(capture_auth_logs):
    client = _client_with_auth(operator_token="t0p-s3cret-token")
    resp = client.get("/secret", headers={"X-Operator-Token": "t0p-s3cret-token"})
    assert resp.status_code == 200
    rec = [r for r in _lines(capture_auth_logs) if r["event"] == "auth_login"]
    assert rec, "expected an auth_login record"
    assert rec[0]["source"] == "operator-header"
    assert rec[0]["tenant_id"] == "operator"
    # No raw email/sub in operator-token mode:
    assert rec[0]["email_hash"] is None


def test_auth_failure_logs_auth_denied(capture_auth_logs):
    client = _client_with_auth(operator_token="real-token")
    resp = client.get("/secret", headers={"X-Operator-Token": "wrong-token"})
    assert resp.status_code == 401
    rec = [r for r in _lines(capture_auth_logs) if r["event"] == "auth_denied"]
    assert rec
    assert rec[0]["reason"] == "no_credential_matched"
    assert rec[0]["level"] == "warning"
    # The login record should NOT be emitted on failure.
    assert not [r for r in _lines(capture_auth_logs) if r["event"] == "auth_login"]


def test_auth_open_path_logged(capture_auth_logs):
    """If operator_token is unset, auth_login records source=open (local-dev fall-through)."""
    client = _client_with_auth(operator_token=None)
    resp = client.get("/secret")
    assert resp.status_code == 200
    rec = [r for r in _lines(capture_auth_logs) if r["event"] == "auth_login"]
    assert rec and rec[0]["source"] == "open"
    assert rec[0]["email_hash"] is None


def test_hash_sub_is_deterministic_and_truncated():
    """The hash helper is the one place a sub maps to email_hash."""
    from wabot_agent.auth import _hash_sub

    expected = hashlib.sha256(b"alice@example.com").hexdigest()[:16]
    assert _hash_sub("alice@example.com") == expected
    assert len(_hash_sub("alice@example.com")) == 16
    assert _hash_sub(None) is None
    assert _hash_sub("") is None


def test_auth_denied_logged_when_cf_jwt_missing(capture_auth_logs):
    """CF Access required + no JWT header → auth_denied with reason=missing_jwt."""
    settings = Settings(cf_access_required=True, cf_access_team_domain="x", cf_access_aud="y")
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    dep = verify_human_factory(settings)

    @app.get("/secret")
    async def secret(identity: AuthIdentity = Depends(dep)):  # noqa: B008
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/secret")
    assert resp.status_code == 401
    rec = [r for r in _lines(capture_auth_logs) if r["event"] == "auth_denied"]
    assert rec
    assert rec[0]["source_attempted"] == "cf-access"
    assert rec[0]["reason"] == "missing_jwt"
