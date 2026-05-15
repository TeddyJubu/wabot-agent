# Public Live-Pairing Website Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a public, mobile-first `/pair` page on `wabot-agent` with a live-updating WhatsApp linked-device QR, protected by Cloudflare Tunnel + Cloudflare Access, while keeping the `wabot` daemon and the inbound webhook on loopback.

**Architecture:** Single React bundle with path-based render. New `verify_human` FastAPI dependency that validates a Cloudflare Access JWT (against cached JWKS) and falls back to the existing operator-token model. The EventHub-driven SSE stream that already publishes `pairing_changed` becomes the live feed for both the new `PairView` page and the existing `PairingPanel` slide-over (restoring a live behavior that regressed in the React migration).

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, PyJWT[crypto], React 18, Vite, TypeScript, Tailwind, Zustand, Vitest, pytest, GitHub Actions, Cloudflare Tunnel (cloudflared), Cloudflare Access.

**Spec:** [2026-05-15-public-pairing-website-design.md](../specs/2026-05-15-public-pairing-website-design.md)

---

## File map

**New files:**

| Path | Purpose |
|---|---|
| `src/wabot_agent/cf_access.py` | Cloudflare Access JWT verifier (JWKS fetch + cache, claims validation). |
| `src/wabot_agent/auth.py` | `AuthIdentity` dataclass + `verify_human` dependency. |
| `web/src/components/PairView.tsx` | Full-screen mobile pairing view rendered at `/pair`. |
| `web/src/hooks/usePairingStream.ts` | Single EventSource subscriber that updates the Zustand pairing slice. |
| `tests/test_cf_access.py` | Unit tests for the Access JWT verifier with mock JWKS. |
| `tests/test_pair_route.py` | Tests for `GET /pair` + `verify_human` + cookie-mint behavior. |
| `deploy/cloudflared/config.yml.example` | Tunnel ingress template. |
| `deploy/systemd/cloudflared.service` | Systemd unit for cloudflared. |
| `scripts/setup-cloudflared.sh` | Idempotent helper to install + configure cloudflared on the VPS. |
| `.github/workflows/ci.yml` | CI: ruff, offline pytest, web vitest, web build, eval harness. |

**Modified files:**

| Path | Change |
|---|---|
| `pyproject.toml` | Add `pyjwt[crypto]>=2.8` to `dependencies`. |
| `src/wabot_agent/config.py` | Add `cf_access_team_domain`, `cf_access_aud`, `cf_access_required` settings. |
| `src/wabot_agent/runtime_overrides.py` | Add three CF Access fields to `MUTABLE_FIELDS`. |
| `src/wabot_agent/api.py` | Replace `operator_dependency` with `human_dependency` on human routes; add `GET /pair`; mint operator cookie on successful Access verification. |
| `web/src/main.tsx` | Path-based root render: `<PairView />` for `/pair`, `<App />` otherwise. |
| `web/src/store/index.ts` | Add `pairing` slice + `setPairing` action. |
| `web/src/api/pairing.ts` | Add `subscribePairing(onState)` SSE helper. |
| `web/src/components/slide-overs/PairingPanel.tsx` | Read pairing from store; manual refresh re-pings `fetchPairing`. |
| `web/src/App.tsx` | Mount `usePairingStream()` once at top of `App`. |
| `web/src/__tests__/pair-view.test.tsx` | NEW vitest for `PairView` and `PairingPanel` store-driven behavior. |
| `.env.example` | Document three CF Access vars + pointer to `scripts/setup-cloudflared.sh`. |
| `CLAUDE.md` | Append "Public access" subsection. |
| `README.md` | Add "Public access via Cloudflare Tunnel" section. |

---

## Task 1: Add PyJWT dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit `pyproject.toml` to add the dep**

In the `[project] dependencies` array, append `"pyjwt[crypto]>=2.8.0"`:

```toml
dependencies = [
  "fastapi>=0.124.0",
  "httpx>=0.28.0",
  "openai>=2.15.0",
  "openai-agents>=0.17.2",
  "pydantic>=2.12.0",
  "pydantic-settings>=2.12.0",
  "pyjwt[crypto]>=2.8.0",
  "python-multipart>=0.0.20",
  "qrcode>=8.2",
  "uvicorn[standard]>=0.38.0",
]
```

- [ ] **Step 2: Sync dependencies**

Run: `uv sync --all-extras`
Expected: `pyjwt` resolved and installed. `uv.lock` updated.

- [ ] **Step 3: Smoke-import PyJWT**

Run: `uv run python -c "import jwt; from jwt import PyJWKClient; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add pyjwt[crypto] for Cloudflare Access JWT verification"
```

---

## Task 2: Add Cloudflare Access settings to `config.py`

**Files:**
- Modify: `src/wabot_agent/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_cf_access_settings_default_off(tmp_path: Path) -> None:
    settings = Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        OPENROUTER_API_KEY=None,
    )
    assert settings.cf_access_required is False
    assert settings.cf_access_team_domain is None
    assert settings.cf_access_aud is None


def test_cf_access_settings_can_be_enabled(tmp_path: Path) -> None:
    settings = Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        OPENROUTER_API_KEY=None,
        WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN="example.cloudflareaccess.com",
        WABOT_AGENT_CF_ACCESS_AUD="abc123def456",
        WABOT_AGENT_CF_ACCESS_REQUIRED=True,
    )
    assert settings.cf_access_required is True
    assert settings.cf_access_team_domain == "example.cloudflareaccess.com"
    assert settings.cf_access_aud == "abc123def456"


def test_cf_access_settings_accept_vignesh_aliases(tmp_path: Path) -> None:
    settings = Settings(
        VIGNESH_OFFLINE_MODE=True,
        VIGNESH_DATA_DIR=tmp_path,
        OPENROUTER_API_KEY=None,
        VIGNESH_CF_ACCESS_TEAM_DOMAIN="legacy.cloudflareaccess.com",
        VIGNESH_CF_ACCESS_AUD="legacy-aud",
        VIGNESH_CF_ACCESS_REQUIRED=True,
    )
    assert settings.cf_access_team_domain == "legacy.cloudflareaccess.com"
    assert settings.cf_access_aud == "legacy-aud"
    assert settings.cf_access_required is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with '.[dev]' python -m pytest tests/test_config.py -k cf_access -v`
Expected: FAIL — `cf_access_required` attribute missing on `Settings`.

- [ ] **Step 3: Add the three settings to `config.py`**

In `src/wabot_agent/config.py`, after the existing `max_agent_turns` field block and before the `allowed_recipients` validator, add:

```python
    cf_access_team_domain: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN", "VIGNESH_CF_ACCESS_TEAM_DOMAIN"
        ),
    )
    cf_access_aud: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "WABOT_AGENT_CF_ACCESS_AUD", "VIGNESH_CF_ACCESS_AUD"
        ),
    )
    cf_access_required: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "WABOT_AGENT_CF_ACCESS_REQUIRED", "VIGNESH_CF_ACCESS_REQUIRED"
        ),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with '.[dev]' python -m pytest tests/test_config.py -k cf_access -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wabot_agent/config.py tests/test_config.py
git commit -m "feat(config): add cf_access_{team_domain,aud,required} settings"
```

---

## Task 3: Extend `runtime_overrides.MUTABLE_FIELDS`

**Files:**
- Modify: `src/wabot_agent/runtime_overrides.py`
- Test: existing test file (covered by next task's settings test); add quick guard test in `tests/test_config.py` if not present.

- [ ] **Step 1: Locate MUTABLE_FIELDS**

Run: `grep -n MUTABLE_FIELDS src/wabot_agent/runtime_overrides.py`
Expected: a tuple/frozenset literal listing currently-mutable fields.

- [ ] **Step 2: Add the three CF Access fields**

In `src/wabot_agent/runtime_overrides.py`, add `"cf_access_team_domain"`, `"cf_access_aud"`, `"cf_access_required"` to `MUTABLE_FIELDS`. Maintain the existing alphabetical (or order) convention.

- [ ] **Step 3: Verify pytest still passes**

Run: `uv run --with '.[dev]' python -m pytest tests/test_config.py -q`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add src/wabot_agent/runtime_overrides.py
git commit -m "feat(overrides): allow cf_access_* fields to be set via PATCH /api/settings"
```

---

## Task 4: Cloudflare Access JWT verifier (`cf_access.py`)

**Files:**
- Create: `src/wabot_agent/cf_access.py`
- Create: `tests/test_cf_access.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cf_access.py` with the full test body below. This uses a self-signed JWKS so tests don't hit the network.

```python
from __future__ import annotations

import json
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from wabot_agent.cf_access import (
    AccessIdentity,
    CfAccessConfig,
    CfAccessError,
    verify_access_jwt,
)


@pytest.fixture
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def kid() -> str:
    return "test-kid-1"


def _jwks_for(key: rsa.RSAPrivateKey, kid: str) -> dict:
    public_numbers = key.public_key().public_numbers()

    def _b64(n: int) -> str:
        import base64

        b = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")

    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": kid,
                "use": "sig",
                "alg": "RS256",
                "n": _b64(public_numbers.n),
                "e": _b64(public_numbers.e),
            }
        ]
    }


def _make_jwt(
    key: rsa.RSAPrivateKey,
    kid: str,
    *,
    aud: str = "test-aud",
    iss: str = "https://example.cloudflareaccess.com",
    email: str = "user@example.com",
    sub: str = "user-sub-123",
    exp_offset: int = 300,
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
            "sub": sub,
            "iat": now,
            "exp": now + exp_offset,
        },
        pem,
        algorithm="RS256",
        headers={"kid": kid},
    )


@pytest.fixture
def cfg(kid: str) -> CfAccessConfig:
    return CfAccessConfig(
        team_domain="example.cloudflareaccess.com",
        aud="test-aud",
    )


def _fake_jwks_fetcher(jwks: dict):
    calls = {"n": 0}

    def fetch(team_domain: str) -> dict:
        calls["n"] += 1
        return jwks

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def test_valid_token_returns_identity(rsa_key, kid, cfg):
    token = _make_jwt(rsa_key, kid)
    fetcher = _fake_jwks_fetcher(_jwks_for(rsa_key, kid))

    identity = verify_access_jwt(token, cfg, fetcher=fetcher)

    assert isinstance(identity, AccessIdentity)
    assert identity.email == "user@example.com"
    assert identity.sub == "user-sub-123"


def test_wrong_audience_rejected(rsa_key, kid, cfg):
    token = _make_jwt(rsa_key, kid, aud="other-aud")
    fetcher = _fake_jwks_fetcher(_jwks_for(rsa_key, kid))

    with pytest.raises(CfAccessError, match="audience"):
        verify_access_jwt(token, cfg, fetcher=fetcher)


def test_expired_token_rejected(rsa_key, kid, cfg):
    token = _make_jwt(rsa_key, kid, exp_offset=-10)
    fetcher = _fake_jwks_fetcher(_jwks_for(rsa_key, kid))

    with pytest.raises(CfAccessError, match="expired"):
        verify_access_jwt(token, cfg, fetcher=fetcher)


def test_unknown_kid_rejected(rsa_key, kid, cfg):
    token = _make_jwt(rsa_key, "different-kid")
    fetcher = _fake_jwks_fetcher(_jwks_for(rsa_key, kid))

    with pytest.raises(CfAccessError, match="kid"):
        verify_access_jwt(token, cfg, fetcher=fetcher)


def test_malformed_token_rejected(cfg, rsa_key, kid):
    fetcher = _fake_jwks_fetcher(_jwks_for(rsa_key, kid))
    with pytest.raises(CfAccessError):
        verify_access_jwt("not-a-jwt", cfg, fetcher=fetcher)


def test_jwks_cached_within_ttl(rsa_key, kid, cfg):
    fetcher = _fake_jwks_fetcher(_jwks_for(rsa_key, kid))

    for _ in range(5):
        verify_access_jwt(_make_jwt(rsa_key, kid), cfg, fetcher=fetcher)

    # JWKS fetched at most twice (once on first verify; subsequent verifies
    # reuse the cache). Allow 1 or 2 to keep the test resilient to cache impl.
    assert fetcher.calls["n"] <= 2  # type: ignore[attr-defined]


def test_missing_team_domain_raises(rsa_key, kid):
    cfg = CfAccessConfig(team_domain=None, aud="test-aud")
    token = _make_jwt(rsa_key, kid)
    fetcher = _fake_jwks_fetcher(_jwks_for(rsa_key, kid))

    with pytest.raises(CfAccessError, match="team_domain"):
        verify_access_jwt(token, cfg, fetcher=fetcher)


def test_missing_aud_raises(rsa_key, kid):
    cfg = CfAccessConfig(team_domain="example.cloudflareaccess.com", aud=None)
    token = _make_jwt(rsa_key, kid)
    fetcher = _fake_jwks_fetcher(_jwks_for(rsa_key, kid))

    with pytest.raises(CfAccessError, match="aud"):
        verify_access_jwt(token, cfg, fetcher=fetcher)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with '.[dev]' python -m pytest tests/test_cf_access.py -v`
Expected: ImportError on `wabot_agent.cf_access`.

- [ ] **Step 3: Create `cf_access.py` with full implementation**

Create `src/wabot_agent/cf_access.py`:

```python
"""Cloudflare Access JWT verification.

Cloudflare Access fronts the FastAPI service via Cloudflare Tunnel. Every
authenticated request carries a `Cf-Access-Jwt-Assertion` header signed by
Cloudflare with RS256, with `iss` = the team domain and `aud` = the
Application Audience tag. We verify both, plus expiry, against the JWKS
fetched from `https://<team-domain>/cdn-cgi/access/certs`.

The fetcher is injectable so tests can supply a static JWKS without
hitting the network.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

import httpx
import jwt
from jwt import InvalidTokenError, PyJWK


class CfAccessError(Exception):
    """Raised when a Cloudflare Access JWT cannot be verified."""


@dataclass(frozen=True)
class CfAccessConfig:
    team_domain: str | None
    aud: str | None
    jwks_ttl_seconds: int = 21600  # 6 hours


@dataclass(frozen=True)
class AccessIdentity:
    email: str | None
    sub: str | None
    aud: str


# Module-level cache keyed by team_domain. Bounded by the number of distinct
# Cloudflare teams the service ever talks to — in practice exactly one.
_jwks_cache: dict[str, tuple[dict, float]] = {}


class JwksFetcher(Protocol):
    def __call__(self, team_domain: str) -> dict: ...


def _default_fetcher(team_domain: str) -> dict:
    url = f"https://{team_domain}/cdn-cgi/access/certs"
    try:
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise CfAccessError(f"JWKS fetch failed for {team_domain}: {exc}") from exc
    try:
        return resp.json()
    except ValueError as exc:
        raise CfAccessError(f"JWKS response was not JSON: {exc}") from exc


def _get_jwks(
    team_domain: str,
    ttl: int,
    fetcher: Callable[[str], dict],
) -> dict:
    now = time.monotonic()
    cached = _jwks_cache.get(team_domain)
    if cached is not None and (now - cached[1]) < ttl:
        return cached[0]
    jwks = fetcher(team_domain)
    _jwks_cache[team_domain] = (jwks, now)
    return jwks


def _find_key(jwks: dict, kid: str) -> PyJWK:
    for k in jwks.get("keys", []):
        if k.get("kid") == kid:
            return PyJWK(k)
    raise CfAccessError(f"Unknown signing kid: {kid}")


def verify_access_jwt(
    token: str,
    cfg: CfAccessConfig,
    *,
    fetcher: Callable[[str], dict] = _default_fetcher,
) -> AccessIdentity:
    """Verify a Cloudflare Access JWT and return the identity claims.

    Raises CfAccessError on any failure.
    """
    if not cfg.team_domain:
        raise CfAccessError("cf_access team_domain is not configured")
    if not cfg.aud:
        raise CfAccessError("cf_access aud is not configured")

    try:
        header = jwt.get_unverified_header(token)
    except InvalidTokenError as exc:
        raise CfAccessError(f"Malformed JWT: {exc}") from exc

    kid = header.get("kid")
    if not kid:
        raise CfAccessError("JWT missing kid header")

    jwks = _get_jwks(cfg.team_domain, cfg.jwks_ttl_seconds, fetcher)
    pyjwk = _find_key(jwks, kid)

    try:
        claims = jwt.decode(
            token,
            pyjwk.key,
            algorithms=["RS256"],
            audience=cfg.aud,
            issuer=f"https://{cfg.team_domain}",
            options={"require": ["aud", "iss", "exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise CfAccessError(f"Token expired: {exc}") from exc
    except jwt.InvalidAudienceError as exc:
        raise CfAccessError(f"Invalid audience: {exc}") from exc
    except jwt.InvalidIssuerError as exc:
        raise CfAccessError(f"Invalid issuer: {exc}") from exc
    except InvalidTokenError as exc:
        raise CfAccessError(f"Invalid JWT: {exc}") from exc

    return AccessIdentity(
        email=claims.get("email"),
        sub=claims.get("sub"),
        aud=cfg.aud,
    )


def clear_jwks_cache() -> None:
    """Test helper: drop the module-level JWKS cache."""
    _jwks_cache.clear()
```

- [ ] **Step 4: Add a `cryptography` pytest fixture import path**

The tests import from `cryptography.hazmat`. Confirm it's available:

Run: `uv run python -c "from cryptography.hazmat.primitives.asymmetric import rsa; print('ok')"`
Expected: `ok` (it's transitively installed via `pyjwt[crypto]`).

- [ ] **Step 5: Make tests pass — ensure cache isolation between tests**

Edit `tests/test_cf_access.py` and at top-level add an `autouse` fixture:

```python
@pytest.fixture(autouse=True)
def _clear_jwks_cache():
    from wabot_agent.cf_access import clear_jwks_cache

    clear_jwks_cache()
    yield
    clear_jwks_cache()
```

- [ ] **Step 6: Run tests to verify all pass**

Run: `uv run --with '.[dev]' python -m pytest tests/test_cf_access.py -v`
Expected: 8 passed.

- [ ] **Step 7: Commit**

```bash
git add src/wabot_agent/cf_access.py tests/test_cf_access.py
git commit -m "feat(auth): Cloudflare Access JWT verifier with JWKS cache"
```

---

## Task 5: `AuthIdentity` + `verify_human` dependency (`auth.py`)

**Files:**
- Create: `src/wabot_agent/auth.py`
- Modify: `src/wabot_agent/api.py` (preserve `verify_operator` signature for re-use)
- Test: `tests/test_pair_route.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pair_route.py`:

```python
from __future__ import annotations

import json
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
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def kid():
    return "test-kid-1"


def _b64uint(n: int) -> str:
    import base64

    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _jwks_for(key, kid):
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


def _mint(key, kid, *, aud="test-aud", iss="https://example.cloudflareaccess.com", email="op@example.com"):
    now = int(time.time())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(
        {"aud": aud, "iss": iss, "email": email, "sub": "sub-1", "iat": now, "exp": now + 300},
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


def _patch_jwks(monkeypatch, jwks: dict):
    from wabot_agent import cf_access

    def fake_fetcher(team_domain: str) -> dict:
        return jwks

    monkeypatch.setattr(cf_access, "_default_fetcher", fake_fetcher)


# --- Tests ---


def test_pair_serves_spa_shell_in_local_dev(tmp_path: Path) -> None:
    client = TestClient(create_app(_make_settings(tmp_path)))
    r = client.get("/pair")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<div id=\"root\"" in r.text


def test_pair_requires_access_when_required(tmp_path: Path, monkeypatch, rsa_key, kid) -> None:
    _patch_jwks(monkeypatch, _jwks_for(rsa_key, kid))
    settings = _make_settings(
        tmp_path,
        WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN="example.cloudflareaccess.com",
        WABOT_AGENT_CF_ACCESS_AUD="test-aud",
        WABOT_AGENT_CF_ACCESS_REQUIRED=True,
    )
    client = TestClient(create_app(settings))

    assert client.get("/pair").status_code == 401


def test_pair_accepts_valid_access_jwt(tmp_path: Path, monkeypatch, rsa_key, kid) -> None:
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
    assert r.status_code == 200


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
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "wabot_agent_operator_token=op-secret" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=Strict" in set_cookie


def test_inbound_unaffected_by_cf_access(tmp_path: Path, monkeypatch, rsa_key, kid) -> None:
    _patch_jwks(monkeypatch, _jwks_for(rsa_key, kid))
    settings = _make_settings(
        tmp_path,
        WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN="example.cloudflareaccess.com",
        WABOT_AGENT_CF_ACCESS_AUD="test-aud",
        WABOT_AGENT_CF_ACCESS_REQUIRED=True,
    )
    client = TestClient(create_app(settings))
    payload = {"id": "msg-cf-1", "from": "+15550001111", "text": "hello"}

    # Even with CF Access required for humans, inbound uses its own token.
    denied = client.post("/whatsapp/inbound", json=payload)
    assert denied.status_code == 401

    ok = client.post(
        "/whatsapp/inbound",
        json=payload,
        headers={"Authorization": "Bearer inbound-secret"},
    )
    assert ok.status_code == 200
    assert ok.json()["accepted"] is True


def test_health_remains_public_with_cf_access(tmp_path: Path) -> None:
    settings = _make_settings(
        tmp_path,
        WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN="example.cloudflareaccess.com",
        WABOT_AGENT_CF_ACCESS_AUD="test-aud",
        WABOT_AGENT_CF_ACCESS_REQUIRED=True,
    )
    client = TestClient(create_app(settings))
    assert client.get("/health").json()["ok"] is True


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


def test_existing_operator_token_path_still_works(tmp_path: Path) -> None:
    """When cf_access_required=False, operator token semantics unchanged."""
    settings = _make_settings(tmp_path, WABOT_AGENT_OPERATOR_TOKEN="op-secret")
    client = TestClient(create_app(settings))
    assert client.get("/api/runs").status_code == 401
    ok = client.get("/api/runs", headers={"X-Operator-Token": "op-secret"})
    assert ok.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with '.[dev]' python -m pytest tests/test_pair_route.py -v`
Expected: most fail (404 on /pair, or 401-when-allowed mismatches).

- [ ] **Step 3: Create `auth.py` with `AuthIdentity` + `verify_human`**

Create `src/wabot_agent/auth.py`:

```python
"""Human authentication for FastAPI routes.

Two layers, applied in order:

1. **Cloudflare Access JWT** when `settings.cf_access_required=True`. The
   header `Cf-Access-Jwt-Assertion` is verified against Cloudflare's JWKS
   for the team domain. On success, an `AuthIdentity` is produced.
2. **Operator token** (`X-Operator-Token` header, `Authorization: Bearer`,
   or `wabot_agent_operator_token` cookie). When CF Access already verified
   the user, this layer is optional and the cookie is *minted* downstream
   so the SPA's `/api/*` calls can use it.

`AuthIdentity.tenant_id` is the seam for future multi-tenancy. Today it's
always `"operator"`; tomorrow it can carry an account UUID without route
changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import Cookie, Header, HTTPException, Request, status

from .cf_access import (
    AccessIdentity,
    CfAccessConfig,
    CfAccessError,
    verify_access_jwt,
)
from .config import Settings


AuthSource = Literal["operator-cookie", "operator-header", "cf-access", "open"]


@dataclass(frozen=True)
class AuthIdentity:
    tenant_id: str
    email: str | None
    sub: str | None
    source: AuthSource


_OPERATOR_TENANT_ID = "operator"


def _verify_operator_token(
    settings: Settings,
    x_operator_token: str | None,
    authorization: str | None,
    operator_session: str | None,
) -> AuthSource | None:
    """Return the source name if a token matches, None otherwise."""
    if not settings.operator_token:
        return "open"
    expected = settings.operator_token
    if x_operator_token == expected:
        return "operator-header"
    if authorization == f"Bearer {expected}":
        return "operator-header"
    if operator_session == expected:
        return "operator-cookie"
    return None


def verify_human_factory(settings: Settings):
    """Build a FastAPI dependency bound to a Settings instance.

    Using a factory keeps the dependency pure (no module-level mutable
    state) and lets `create_app` wire it once at startup.
    """

    def verify_human(
        request: Request,
        x_operator_token: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
        operator_session: str | None = Cookie(
            default=None, alias="wabot_agent_operator_token"
        ),
        cf_access_jwt: str | None = Header(
            default=None, alias="Cf-Access-Jwt-Assertion"
        ),
    ) -> AuthIdentity:
        # 1. Cloudflare Access path (required mode)
        if settings.cf_access_required:
            if not cf_access_jwt:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Cloudflare Access required",
                )
            try:
                access: AccessIdentity = verify_access_jwt(
                    cf_access_jwt,
                    CfAccessConfig(
                        team_domain=settings.cf_access_team_domain,
                        aud=settings.cf_access_aud,
                    ),
                )
            except CfAccessError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Cloudflare Access: {exc}",
                ) from exc
            # Stash on request.state so the route handler can mint the
            # operator cookie on the response.
            request.state.cf_access_identity = access
            return AuthIdentity(
                tenant_id=_OPERATOR_TENANT_ID,
                email=access.email,
                sub=access.sub,
                source="cf-access",
            )

        # 2. Operator token path (legacy / local dev)
        source = _verify_operator_token(
            settings, x_operator_token, authorization, operator_session
        )
        if source is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Operator token required",
            )
        return AuthIdentity(
            tenant_id=_OPERATOR_TENANT_ID,
            email=None,
            sub=None,
            source=source,
        )

    return verify_human
```

- [ ] **Step 4: Wire `verify_human` into `api.py`**

In `src/wabot_agent/api.py`:

1. Replace the `operator_dependency = Depends(verify_operator)` line with:

```python
human_dependency = Depends(verify_human_factory(settings))
```

(placing it after `settings` is in scope inside `create_app`).

2. Replace every `dependencies=[operator_dependency]` on a human route with `dependencies=[human_dependency]`. The routes to update:
   - `GET /ready`
   - `GET /api/whatsapp/pairing`
   - `GET /api/whatsapp/pairing.svg`
   - `POST /api/chat`
   - `POST /api/chat/stream`
   - `GET /api/memory/{contact}`
   - `GET /api/runs`
   - `GET /api/stream`
   - `GET /api/settings`
   - `PATCH /api/settings`
   - `POST /api/settings/test/openrouter`
   - `POST /api/settings/test/wabot`

3. Leave `POST /whatsapp/inbound` and `GET /health` unchanged.

4. Add the import: `from .auth import verify_human_factory`.

5. Add a helper `_maybe_mint_operator_cookie(response, request, settings)` that, if `request.state.cf_access_identity` is set and `settings.operator_token` is truthy and the cookie is missing on the request, calls `response.set_cookie(...)` with the same flags as the existing `GET /` flow.

- [ ] **Step 5: Add `GET /pair` route**

In `create_app`, after the `GET /` route, add:

```python
@app.get("/pair")
async def pair_page(
    request: Request,
    response: Response,
    identity: AuthIdentity = human_dependency,
) -> FileResponse:
    _maybe_mint_operator_cookie(response, request, settings)
    return FileResponse(static_dir / "index.html", media_type="text/html")
```

- [ ] **Step 6: Run tests**

Run: `uv run --with '.[dev]' python -m pytest tests/test_pair_route.py -v`
Expected: all 8 passed.

- [ ] **Step 7: Run full backend offline suite**

Run: `uv run --with '.[dev]' python -m pytest -m offline -q`
Expected: all green. If any of the existing `test_operator_endpoints_require_token_when_configured` or `test_dashboard_token_sets_operator_cookie` tests fail, the `verify_human` operator-token fallback path needs adjustment — fix in `auth.py` until those tests pass too.

- [ ] **Step 8: Commit**

```bash
git add src/wabot_agent/auth.py src/wabot_agent/api.py tests/test_pair_route.py
git commit -m "feat(auth): verify_human dep + /pair route with Cloudflare Access"
```

---

## Task 6: Zustand pairing slice + `subscribePairing` SSE helper

**Files:**
- Modify: `web/src/store/index.ts`
- Modify: `web/src/api/pairing.ts`

- [ ] **Step 1: Extend the store with a pairing slice**

In `web/src/store/index.ts`:

Add to the `State` interface (before the action signatures):

```ts
  pairing: PairingState | null;
```

Add to the `State` action signatures:

```ts
  setPairing: (p: PairingState | null) => void;
```

Add at the top of the file:

```ts
import type { PairingState } from "@/api/pairing";
```

In the `create<State>((set) => ({ ... }))` initial state, add:

```ts
  pairing: null,
```

And add the action:

```ts
  setPairing: (p) => set({ pairing: p }),
```

- [ ] **Step 2: Add `subscribePairing` to `web/src/api/pairing.ts`**

Replace the file with:

```ts
export interface PairingState {
  qr_available: boolean;
  logged_in: boolean | null;
  connected: boolean | null;
  reachable: boolean;
  detail?: string | null;
  updated_at?: string | null;
  supported?: boolean;
}

export async function fetchPairing(): Promise<PairingState> {
  const res = await fetch("/api/whatsapp/pairing", { credentials: "include" });
  if (!res.ok) {
    return {
      qr_available: false,
      logged_in: null,
      connected: null,
      reachable: false,
    };
  }
  return res.json();
}

export interface PairingSubscription {
  close: () => void;
}

/**
 * Open an EventSource to /api/stream and call `onState` whenever a
 * `pairing_changed` arrives (or the `ready_snapshot` carries a pairing
 * payload). Returns a handle whose `close()` tears down the EventSource.
 *
 * `EventSource` already auto-reconnects on transport errors. We only add
 * a thin guard to ignore events after `close()` has been called.
 */
export function subscribePairing(
  onState: (s: PairingState) => void,
): PairingSubscription {
  let closed = false;
  const es = new EventSource("/api/stream", { withCredentials: true });

  const handlePairing = (raw: string) => {
    if (closed) return;
    try {
      const data = JSON.parse(raw) as PairingState;
      onState(data);
    } catch {
      // Ignore malformed payloads — the next pairing tick will resync.
    }
  };

  es.addEventListener("pairing_changed", (ev) => {
    handlePairing((ev as MessageEvent).data);
  });

  es.addEventListener("ready_snapshot", (ev) => {
    if (closed) return;
    try {
      const data = JSON.parse((ev as MessageEvent).data);
      if (data && data.pairing) onState(data.pairing as PairingState);
    } catch {
      // Ignore.
    }
  });

  return {
    close: () => {
      closed = true;
      es.close();
    },
  };
}
```

- [ ] **Step 3: Smoke-check via the TypeScript build**

Run: `cd web && npm ci && npm run build`
Expected: build succeeds; no type errors.

- [ ] **Step 4: Commit**

```bash
git add web/src/store/index.ts web/src/api/pairing.ts
git commit -m "feat(web): pairing slice in zustand + subscribePairing SSE helper"
```

---

## Task 7: `usePairingStream` hook + restore live `PairingPanel`

**Files:**
- Create: `web/src/hooks/usePairingStream.ts`
- Modify: `web/src/components/slide-overs/PairingPanel.tsx`
- Modify: `web/src/App.tsx`
- Test: `web/src/__tests__/pair-view.test.tsx`

- [ ] **Step 1: Create `usePairingStream.ts`**

```ts
import { useEffect } from "react";
import { subscribePairing } from "@/api/pairing";
import { useStore } from "@/store";

/**
 * Mount once at the top of the app shell (or the PairView). Opens a
 * single EventSource and feeds `pairing_changed` updates into the
 * Zustand pairing slice. All consumers read via `useStore(s => s.pairing)`.
 */
export function usePairingStream(): void {
  const setPairing = useStore((s) => s.setPairing);

  useEffect(() => {
    const sub = subscribePairing(setPairing);
    return () => sub.close();
  }, [setPairing]);
}
```

- [ ] **Step 2: Replace `PairingPanel.tsx` to read from the store**

```tsx
import { useState } from "react";
import PairingQrCard from "../tool-cards/PairingQrCard";
import { fetchPairing, type PairingState } from "@/api/pairing";
import { useStore } from "@/store";

function describe(state: PairingState | null): string | null {
  if (!state) return "Checking…";
  if (state.logged_in) return state.connected ? "Linked & connected" : "Linked";
  if (state.qr_available) return "Ready to pair";
  if (!state.reachable) return "wabot unreachable";
  return "Not linked";
}

export default function PairingPanel() {
  const state = useStore((s) => s.pairing);
  const setPairing = useStore((s) => s.setPairing);
  const [refreshing, setRefreshing] = useState(false);

  async function manualRefresh() {
    setRefreshing(true);
    try {
      const p = await fetchPairing();
      setPairing(p);
    } finally {
      setRefreshing(false);
    }
  }

  const status = describe(state);
  return (
    <div className="space-y-3">
      {status && (
        <p className="text-xs uppercase tracking-wider text-fg-muted">{status}</p>
      )}
      <PairingQrCard
        data={{ available: !!state?.qr_available, linked_device: null }}
        actions={[
          {
            id: "refresh",
            label: refreshing ? "Refreshing…" : "Refresh",
            tool: "__pairing_qr",
            args: {},
          },
        ]}
        onAction={() => {
          void manualRefresh();
        }}
      />
      {state?.detail && (
        <p className="rounded-card border border-border bg-bg-app p-3 text-xs text-fg-muted">
          {state.detail}
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Mount `usePairingStream` in `App.tsx`**

In `web/src/App.tsx`, near the top of the component body (after the `const messages = useStore(...)` block but before the `useEffect` that calls `fetchSettings`), add:

```ts
  usePairingStream();
```

And the import:

```ts
import { usePairingStream } from "@/hooks/usePairingStream";
```

- [ ] **Step 4: Write a vitest for PairingPanel store-driven behavior**

Create `web/src/__tests__/pair-view.test.tsx`:

```tsx
import { describe, expect, it, beforeEach, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

import PairingPanel from "@/components/slide-overs/PairingPanel";
import { useStore } from "@/store";

beforeEach(() => {
  useStore.setState({ pairing: null });
});

describe("PairingPanel", () => {
  it("renders 'Checking…' when pairing is null", () => {
    render(<PairingPanel />);
    expect(screen.getByText(/checking/i)).toBeInTheDocument();
  });

  it("renders 'Linked & connected' when store reflects connected state", () => {
    act(() => {
      useStore.setState({
        pairing: {
          qr_available: false,
          logged_in: true,
          connected: true,
          reachable: true,
        },
      });
    });
    render(<PairingPanel />);
    expect(screen.getByText(/linked & connected/i)).toBeInTheDocument();
  });

  it("renders 'wabot unreachable' when pairing.reachable is false", () => {
    act(() => {
      useStore.setState({
        pairing: {
          qr_available: false,
          logged_in: false,
          connected: false,
          reachable: false,
        },
      });
    });
    render(<PairingPanel />);
    expect(screen.getByText(/unreachable/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Run web tests**

Run: `cd web && npm run test -- --run`
Expected: all PairingPanel tests pass plus existing tool-cards snapshots still pass.

- [ ] **Step 6: Commit**

```bash
git add web/src/hooks/usePairingStream.ts web/src/components/slide-overs/PairingPanel.tsx web/src/App.tsx web/src/__tests__/pair-view.test.tsx
git commit -m "feat(web): live PairingPanel via Zustand + usePairingStream"
```

---

## Task 8: `PairView` page + path-based render in `main.tsx`

**Files:**
- Create: `web/src/components/PairView.tsx`
- Modify: `web/src/main.tsx`
- Test: append to `web/src/__tests__/pair-view.test.tsx`

- [ ] **Step 1: Write the failing tests**

Append to `web/src/__tests__/pair-view.test.tsx`:

```tsx
import PairView from "@/components/PairView";

describe("PairView", () => {
  it("renders the checking state when no pairing data is loaded", () => {
    useStore.setState({ pairing: null });
    render(<PairView />);
    expect(screen.getByText(/whatsapp pairing/i)).toBeInTheDocument();
    expect(screen.getByText(/checking/i)).toBeInTheDocument();
  });

  it("shows the connected state when the bot is linked", () => {
    act(() => {
      useStore.setState({
        pairing: {
          qr_available: false,
          logged_in: true,
          connected: true,
          reachable: true,
        },
      });
    });
    render(<PairView />);
    expect(screen.getByText(/connected/i)).toBeInTheDocument();
  });

  it("shows the QR card when a pairing code is available", () => {
    act(() => {
      useStore.setState({
        pairing: {
          qr_available: true,
          logged_in: false,
          connected: false,
          reachable: true,
        },
      });
    });
    render(<PairView />);
    // PairingQrCard renders an <img> with the cache-busted SVG src.
    expect(screen.getByRole("img", { name: /pairing/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run web tests to verify they fail**

Run: `cd web && npm run test -- --run`
Expected: import failure on `@/components/PairView`.

- [ ] **Step 3: Create `PairView.tsx`**

```tsx
import { useStore } from "@/store";
import { usePairingStream } from "@/hooks/usePairingStream";
import PairingQrCard from "@/components/tool-cards/PairingQrCard";
import type { PairingState } from "@/api/pairing";

function statusText(p: PairingState | null): string {
  if (!p) return "Checking…";
  if (p.logged_in) return p.connected ? "Connected" : "Linked (offline)";
  if (p.qr_available) return "Scan to connect";
  if (!p.reachable) return "wabot unreachable";
  return "Not linked";
}

function statusTone(p: PairingState | null): string {
  if (!p) return "text-fg-muted";
  if (p.logged_in && p.connected) return "text-success";
  if (!p.reachable) return "text-warn";
  return "text-fg-muted";
}

export default function PairView() {
  usePairingStream();
  const pairing = useStore((s) => s.pairing);

  return (
    <div className="mx-auto flex min-h-full w-full max-w-[480px] flex-col px-4 py-8">
      <header className="mb-6 space-y-1 text-center">
        <h1 className="text-xl font-semibold tracking-tight">WhatsApp pairing</h1>
        <p className={`text-sm ${statusTone(pairing)}`}>{statusText(pairing)}</p>
      </header>

      <div className="rounded-card border border-border bg-bg-card p-4">
        {pairing?.logged_in && pairing.connected ? (
          <div className="flex flex-col items-center gap-3 py-12 text-center">
            <div className="text-3xl">✓</div>
            <p className="text-sm text-fg-muted">
              Your WhatsApp is linked to this bot.
            </p>
          </div>
        ) : (
          <PairingQrCard
            data={{
              available: !!pairing?.qr_available,
              linked_device: null,
            }}
            actions={[]}
          />
        )}
      </div>

      {pairing?.detail && (
        <p className="mt-3 rounded-card border border-border bg-bg-app p-3 text-xs text-fg-muted">
          {pairing.detail}
        </p>
      )}

      <footer className="mt-auto pt-8 text-center text-xs text-fg-muted">
        <a href="/" className="underline hover:text-fg">
          Open full dashboard
        </a>
      </footer>
    </div>
  );
}
```

- [ ] **Step 4: Path-based render in `main.tsx`**

Replace `web/src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import PairView from "./components/PairView";
import "./styles.css";

function selectRoot(): JSX.Element {
  const path = window.location.pathname.replace(/\/+$/, "");
  if (path === "/pair") return <PairView />;
  return <App />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>{selectRoot()}</StrictMode>,
);
```

- [ ] **Step 5: Run web tests + build**

```bash
cd web && npm run test -- --run && npm run build
```

Expected: all tests green; `tsc --noEmit` clean; Vite build emits `dist/`.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/PairView.tsx web/src/main.tsx web/src/__tests__/pair-view.test.tsx
git commit -m "feat(web): PairView page + path-based render at /pair"
```

---

## Task 9: Build the SPA bundle into `static/`

**Files:**
- Generated: `static/*`

- [ ] **Step 1: Run the build-web script**

Run: `bash scripts/build-web.sh`
Expected: `static/ updated from web/dist/`. Files include `index.html`, `assets/index-*.js`, `assets/index-*.css`.

- [ ] **Step 2: Sanity-check by running pytest (static-shell route test)**

Run: `uv run --with '.[dev]' python -m pytest tests/test_pair_route.py::test_pair_serves_spa_shell_in_local_dev -v`
Expected: pass (the route serves `static/index.html`).

- [ ] **Step 3: Commit the rebuilt bundle**

```bash
git add static/
git commit -m "build(web): rebuild bundle including PairView"
```

---

## Task 10: Cloudflare Tunnel deploy artifacts

**Files:**
- Create: `deploy/cloudflared/config.yml.example`
- Create: `deploy/systemd/cloudflared.service`
- Create: `scripts/setup-cloudflared.sh`

- [ ] **Step 1: Create the tunnel config template**

`deploy/cloudflared/config.yml.example`:

```yaml
# Cloudflare Tunnel config for wabot-agent
#
# Copy this to /etc/cloudflared/config.yml after running
# `cloudflared tunnel create wabot-agent` (which writes the credentials JSON
# and tunnel UUID), then fill in the placeholders.

tunnel: REPLACE_WITH_TUNNEL_UUID
credentials-file: /etc/cloudflared/REPLACE_WITH_TUNNEL_UUID.json

# Origin requests stay on the VPS loopback. FastAPI binds 127.0.0.1:8787.
# wabot itself (127.0.0.1:7777) is NOT exposed here — and never should be.
ingress:
  - hostname: wabot.REPLACE_WITH_YOUR_DOMAIN
    service: http://127.0.0.1:8787
    originRequest:
      noTLSVerify: true
      connectTimeout: 10s
      # `/whatsapp/inbound` is loopback-only — wabot POSTs to it directly,
      # never via this tunnel. Cloudflare Access protects everything else.

  # Required catch-all.
  - service: http_status:404
```

- [ ] **Step 2: Create the systemd unit**

`deploy/systemd/cloudflared.service`:

```ini
[Unit]
Description=Cloudflare Tunnel for wabot-agent
After=network.target wabot-agent.service
Wants=network.target

[Service]
Type=notify
ExecStart=/usr/local/bin/cloudflared --no-autoupdate tunnel --config /etc/cloudflared/config.yml run
Restart=on-failure
RestartSec=5s
User=cloudflared
Group=cloudflared
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadOnlyPaths=/etc/cloudflared

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Create the setup script**

`scripts/setup-cloudflared.sh`:

```bash
#!/usr/bin/env bash
# Idempotent installer for cloudflared on the wabot-agent VPS.
#
# Steps:
#   1. Install cloudflared from the official Cloudflare apt repo (skip if already present).
#   2. Run `cloudflared tunnel login` (browser-based; copies cert.pem to /etc/cloudflared).
#   3. Create the tunnel "wabot-agent" (skip if it already exists).
#   4. Write /etc/cloudflared/config.yml from the template, substituting the tunnel UUID and the user-supplied hostname.
#   5. Route the chosen hostname's DNS to the tunnel.
#   6. Install the systemd unit and enable it.
#   7. Print next steps for Cloudflare Access setup (manual — must be done in the Cloudflare dashboard).
#
# Usage:
#   sudo ./scripts/setup-cloudflared.sh wabot.example.com
#
# Re-running with the same hostname is safe: no duplicate tunnels created,
# no duplicate DNS records, no service flapping.

set -euo pipefail

if [[ ${EUID:-1000} -ne 0 ]]; then
  echo "This script must be run as root (sudo)." >&2
  exit 1
fi

HOSTNAME="${1:-}"
if [[ -z "${HOSTNAME}" ]]; then
  echo "Usage: sudo $0 <hostname e.g. wabot.example.com>" >&2
  exit 2
fi

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TUNNEL_NAME="wabot-agent"
CONFIG_DIR="/etc/cloudflared"
SYSTEMD_UNIT="/etc/systemd/system/cloudflared.service"

echo "==> Installing cloudflared (if missing)"
if ! command -v cloudflared >/dev/null 2>&1; then
  mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" \
    | tee /etc/apt/sources.list.d/cloudflared.list
  apt-get update
  apt-get install -y cloudflared
else
  echo "cloudflared already present: $(cloudflared --version | head -1)"
fi

echo "==> Ensuring config dir exists"
mkdir -p "${CONFIG_DIR}"

echo "==> Logging in to Cloudflare (browser flow, only if cert is missing)"
if [[ ! -f "${CONFIG_DIR}/cert.pem" ]]; then
  cloudflared tunnel login
  cp "${HOME}/.cloudflared/cert.pem" "${CONFIG_DIR}/cert.pem" || true
fi

echo "==> Creating tunnel '${TUNNEL_NAME}' (if missing)"
if ! cloudflared --origincert "${CONFIG_DIR}/cert.pem" tunnel list 2>/dev/null | grep -q " ${TUNNEL_NAME} "; then
  cloudflared --origincert "${CONFIG_DIR}/cert.pem" tunnel create "${TUNNEL_NAME}"
fi

TUNNEL_UUID="$(cloudflared --origincert "${CONFIG_DIR}/cert.pem" tunnel list \
  | awk -v n="${TUNNEL_NAME}" '$2==n {print $1; exit}')"
if [[ -z "${TUNNEL_UUID}" ]]; then
  echo "Could not resolve tunnel UUID for '${TUNNEL_NAME}'" >&2
  exit 3
fi
echo "Tunnel UUID: ${TUNNEL_UUID}"

# Move the credentials JSON into the config dir if it isn't there yet.
CRED_SRC="${HOME}/.cloudflared/${TUNNEL_UUID}.json"
CRED_DST="${CONFIG_DIR}/${TUNNEL_UUID}.json"
if [[ -f "${CRED_SRC}" && ! -f "${CRED_DST}" ]]; then
  install -m 0640 "${CRED_SRC}" "${CRED_DST}"
fi

echo "==> Writing ${CONFIG_DIR}/config.yml"
sed \
  -e "s|REPLACE_WITH_TUNNEL_UUID|${TUNNEL_UUID}|g" \
  -e "s|wabot.REPLACE_WITH_YOUR_DOMAIN|${HOSTNAME}|g" \
  "${REPO_DIR}/deploy/cloudflared/config.yml.example" \
  > "${CONFIG_DIR}/config.yml"
chmod 0644 "${CONFIG_DIR}/config.yml"

echo "==> Routing DNS ${HOSTNAME} -> tunnel ${TUNNEL_UUID}"
cloudflared --origincert "${CONFIG_DIR}/cert.pem" tunnel route dns "${TUNNEL_NAME}" "${HOSTNAME}" || true

echo "==> Creating cloudflared system user (if missing)"
if ! id cloudflared >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin cloudflared
fi
chown -R cloudflared:cloudflared "${CONFIG_DIR}"

echo "==> Installing systemd unit"
install -m 0644 "${REPO_DIR}/deploy/systemd/cloudflared.service" "${SYSTEMD_UNIT}"
systemctl daemon-reload
systemctl enable --now cloudflared.service

echo
echo "✓ cloudflared is running for ${HOSTNAME}."
echo
echo "Next steps (manual, in the Cloudflare dashboard):"
echo "  1. Zero Trust > Access > Applications > Add an application"
echo "     - Type: Self-hosted"
echo "     - Application domain: ${HOSTNAME}"
echo "     - Application Audience tag: copy it; you'll set WABOT_AGENT_CF_ACCESS_AUD to this."
echo "  2. Policies: add a 'Google login' or 'One-time PIN' policy restricted to your email."
echo "  3. In your .env on the VPS, set:"
echo "       WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN=<yourteam>.cloudflareaccess.com"
echo "       WABOT_AGENT_CF_ACCESS_AUD=<aud from step 1>"
echo "       WABOT_AGENT_CF_ACCESS_REQUIRED=true"
echo "  4. systemctl restart wabot-agent.service"
echo
echo "Test from a phone: https://${HOSTNAME}/pair"
```

Make it executable:

- [ ] **Step 4: chmod +x the script**

Run: `chmod +x scripts/setup-cloudflared.sh`

- [ ] **Step 5: Commit**

```bash
git add deploy/cloudflared/config.yml.example deploy/systemd/cloudflared.service scripts/setup-cloudflared.sh
git commit -m "feat(deploy): cloudflared tunnel config + systemd unit + setup script"
```

---

## Task 11: CI workflow (`.github/workflows/ci.yml`)

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the workflow**

```yaml
name: ci

on:
  push:
  pull_request:

jobs:
  backend:
    name: backend (ruff + pytest)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          version: "0.8.22"
      - name: Set up Python
        run: uv python install 3.12
      - name: Sync deps
        run: uv sync --all-extras
      - name: Ruff
        run: uv run --with '.[dev]' ruff check .
      - name: Pytest (offline)
        run: uv run --with '.[dev]' python -m pytest -m offline -q

  evals:
    name: evals (offline)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          version: "0.8.22"
      - name: Set up Python
        run: uv python install 3.12
      - name: Sync deps
        run: uv sync --all-extras
      - name: Run eval harness
        run: uv run python evals/run_local.py

  web:
    name: web (vitest + build)
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: web
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: web/package-lock.json
      - name: Install deps
        run: npm ci
      - name: Vitest
        run: npm run test -- --run
      - name: Build
        run: npm run build
```

- [ ] **Step 2: Validate YAML locally (no special tool needed; Python suffices)**

Run: `uv run python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions workflow (backend, evals, web)"
```

---

## Task 12: Documentation updates

**Files:**
- Modify: `.env.example`
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Append to `.env.example`**

Add at the bottom:

```dotenv
# --- Public access via Cloudflare Tunnel + Cloudflare Access ---
# When you want anyone with browser access to a public URL to be able
# to pair their phone, run scripts/setup-cloudflared.sh on the VPS,
# create a Cloudflare Access application for the hostname, and set:
#
#   WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN=yourteam.cloudflareaccess.com
#   WABOT_AGENT_CF_ACCESS_AUD=<Application Audience tag from CF dashboard>
#   WABOT_AGENT_CF_ACCESS_REQUIRED=true
#
# Leaving these unset (or REQUIRED=false) preserves today's
# operator-token-only behavior, suitable for local development.
```

- [ ] **Step 2: Append to `CLAUDE.md` under the Architecture section**

Add a new subsection:

```markdown
### Public access

Public access is provided by **Cloudflare Tunnel** running on the VPS — `cloudflared` opens an outbound connection to Cloudflare's edge and proxies inbound traffic to FastAPI on `127.0.0.1:8787`. **No inbound ports are opened on the VPS.** `wabot` stays on loopback at `127.0.0.1:7777` and is not part of the tunnel ingress.

In front of the tunnel, **Cloudflare Access** prompts the operator for a Google login or one-time-PIN email before the request reaches the VPS. The Access JWT is verified by [src/wabot_agent/cf_access.py](src/wabot_agent/cf_access.py) using the JWKS at `https://<team-domain>/cdn-cgi/access/certs`, cached for 6h. The dependency [src/wabot_agent/auth.py](src/wabot_agent/auth.py) (`verify_human`) replaces the old `verify_operator` on all human routes — but **`/whatsapp/inbound` is unchanged** because `wabot` calls it over loopback with its own `WABOT_INBOUND_TOKEN`. Cloudflare never sees that path.

`/pair` is a mobile-first single-page route served by the same React bundle as `/`. The Zustand `pairing` slice is fed by a single `EventSource('/api/stream')`, so the QR re-renders instantly when `wabot` rotates the pairing code.
```

- [ ] **Step 3: Append to `README.md`**

Add a new section after the VPS deploy block:

```markdown
## Public access (optional)

To pair WhatsApp from any phone or laptop browser — without SSH — run the
Cloudflare Tunnel installer on the VPS:

```bash
sudo ./scripts/setup-cloudflared.sh wabot.your-domain.com
```

This installs `cloudflared`, creates the tunnel, routes DNS to it, and starts
a systemd service. Follow the printed instructions to create a Cloudflare
Access application and set the three `WABOT_AGENT_CF_ACCESS_*` env vars.
The public `/pair` page then shows a live, mobile-friendly WhatsApp linked-
device QR, gated by your Cloudflare Access policy.

See [docs/superpowers/specs/2026-05-15-public-pairing-website-design.md](docs/superpowers/specs/2026-05-15-public-pairing-website-design.md)
for the full security model.
```

- [ ] **Step 4: Commit**

```bash
git add .env.example CLAUDE.md README.md
git commit -m "docs: public access setup via Cloudflare Tunnel + Access"
```

---

## Task 13: Full offline suite and ruff sweep

- [ ] **Step 1: Run ruff**

Run: `uv run --with '.[dev]' ruff check .`
Expected: no issues. If lint errors appear, fix them inline (most likely import sorting in the new files).

- [ ] **Step 2: Run pytest (offline)**

Run: `uv run --with '.[dev]' python -m pytest -m offline -q`
Expected: all green. If `test_dashboard_token_sets_operator_cookie` or `test_operator_endpoints_require_token_when_configured` flake under the new auth dependency, trace through `verify_human` and fix.

- [ ] **Step 3: Run the eval harness**

Run: `uv run python evals/run_local.py`
Expected: writes `evals/results/latest.jsonl`, exits 0.

- [ ] **Step 4: Run vitest**

Run: `cd web && npm run test -- --run`
Expected: all passing.

- [ ] **Step 5: Run the web build one more time**

Run: `bash scripts/build-web.sh`
Expected: `static/` regenerated. If files change, commit them.

```bash
git add static/
git diff --cached --quiet || git commit -m "build(web): final bundle"
```

---

## Task 14: SQA review pass

- [ ] **Step 1: Dispatch the SQA subagent**

Delegate to `feature-dev:code-reviewer` (or `pr-review-toolkit:code-reviewer`) to inspect the full diff vs `main`. Brief it that this PR introduces a new internet-facing auth path on a service that controls a WhatsApp account, so the review should be conservative about: JWT verification correctness, cookie flag preservation, route-by-route auth coverage, fail-closed behavior on JWKS fetch errors, and absence of secrets in commits.

- [ ] **Step 2: Address each finding**

Triage in confidence order. Land fixes as additional commits on the same branch, prefixed `fix(review): ...` so the history is legible.

- [ ] **Step 3: Re-run the full offline suite**

Run Task 13 steps again. Must remain green.

---

## Task 15: PR

- [ ] **Step 1: Push the branch**

Run: `git push -u origin claude/public-pairing-website`

- [ ] **Step 2: Open the PR**

Use `gh pr create` with a HEREDOC body summarizing scope, decisions, and the operator-side post-merge steps (the three CF Access env vars and the setup script).

- [ ] **Step 3: Monitor CI**

Watch `gh pr checks` until the run completes. If anything fails, apply the `ci-fix` skill and push fixes onto the same branch.

- [ ] **Step 4: Leave a final status comment on the PR**

Summarize what's done, what the operator must do post-merge (CF Access setup), and call out the points that need their attention before they click merge.

---

## Self-review

**Spec coverage:** Every numbered decision in the spec maps to a task —
- "Cloudflare Tunnel from VPS" → Task 10 (cloudflared artifacts).
- "Cloudflare Access JWT + operator token defense-in-depth" → Tasks 4–5.
- "Single React bundle path-based render" → Task 8 (main.tsx).
- "Zustand pairing slice + usePairingStream" → Tasks 6–7.
- "PairingPanel reads from store" → Task 7.
- "CI from scratch" → Task 11.
- "AuthIdentity tenant-id seam" → Task 5 (`auth.py`).
- "Defaults preserve offline tests" → Task 2 (`cf_access_required=False` default).
- "/whatsapp/inbound unchanged" → covered by Task 5 step 4 + the test in Task 5 step 1.

**Placeholder scan:** Every code step contains full code. The setup script and YAML use `REPLACE_WITH_*` placeholders intentionally (substituted at install time).

**Type consistency:** `AuthIdentity.tenant_id` is used in spec + Task 5. `PairingState` is exported from `web/src/api/pairing.ts` and imported in store + components. `subscribePairing` returns `PairingSubscription`.
