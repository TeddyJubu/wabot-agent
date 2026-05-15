"""Unit tests for the Cloudflare Access JWT verifier.

Uses a self-signed RSA keypair + a stub JWKS fetcher so no network or real
Cloudflare account is required.
"""

from __future__ import annotations

import base64
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from wabot_agent.cf_access import (
    AccessIdentity,
    CfAccessConfig,
    CfAccessError,
    clear_jwks_cache,
    verify_access_jwt,
)


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
    public_numbers = key.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": kid,
                "use": "sig",
                "alg": "RS256",
                "n": _b64uint(public_numbers.n),
                "e": _b64uint(public_numbers.e),
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
def cfg() -> CfAccessConfig:
    return CfAccessConfig(
        team_domain="example.cloudflareaccess.com",
        aud="test-aud",
    )


def _fake_fetcher(jwks: dict):
    calls = {"n": 0}

    def fetch(team_domain: str) -> dict:
        calls["n"] += 1
        return jwks

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def test_valid_token_returns_identity(rsa_key, kid, cfg):
    token = _make_jwt(rsa_key, kid)
    fetcher = _fake_fetcher(_jwks_for(rsa_key, kid))

    identity = verify_access_jwt(token, cfg, fetcher=fetcher)

    assert isinstance(identity, AccessIdentity)
    assert identity.email == "user@example.com"
    assert identity.sub == "user-sub-123"


def test_wrong_audience_rejected(rsa_key, kid, cfg):
    token = _make_jwt(rsa_key, kid, aud="other-aud")
    fetcher = _fake_fetcher(_jwks_for(rsa_key, kid))

    with pytest.raises(CfAccessError, match="audience"):
        verify_access_jwt(token, cfg, fetcher=fetcher)


def test_expired_token_rejected(rsa_key, kid, cfg):
    token = _make_jwt(rsa_key, kid, exp_offset=-10)
    fetcher = _fake_fetcher(_jwks_for(rsa_key, kid))

    with pytest.raises(CfAccessError, match="expired"):
        verify_access_jwt(token, cfg, fetcher=fetcher)


def test_unknown_kid_rejected(rsa_key, kid, cfg):
    token = _make_jwt(rsa_key, "different-kid")
    fetcher = _fake_fetcher(_jwks_for(rsa_key, kid))

    with pytest.raises(CfAccessError, match="kid"):
        verify_access_jwt(token, cfg, fetcher=fetcher)


def test_malformed_token_rejected(cfg, rsa_key, kid):
    fetcher = _fake_fetcher(_jwks_for(rsa_key, kid))
    with pytest.raises(CfAccessError):
        verify_access_jwt("not-a-jwt", cfg, fetcher=fetcher)


def test_jwks_cached_within_ttl(rsa_key, kid, cfg):
    fetcher = _fake_fetcher(_jwks_for(rsa_key, kid))

    for _ in range(5):
        verify_access_jwt(_make_jwt(rsa_key, kid), cfg, fetcher=fetcher)

    # Cache hits keep network calls minimal — allow 1 or 2 to leave room for
    # cache implementation variants.
    assert fetcher.calls["n"] <= 2  # type: ignore[attr-defined]


def test_missing_team_domain_raises(rsa_key, kid):
    cfg = CfAccessConfig(team_domain=None, aud="test-aud")
    token = _make_jwt(rsa_key, kid)
    fetcher = _fake_fetcher(_jwks_for(rsa_key, kid))

    with pytest.raises(CfAccessError, match="team_domain"):
        verify_access_jwt(token, cfg, fetcher=fetcher)


def test_missing_aud_raises(rsa_key, kid):
    cfg = CfAccessConfig(team_domain="example.cloudflareaccess.com", aud=None)
    token = _make_jwt(rsa_key, kid)
    fetcher = _fake_fetcher(_jwks_for(rsa_key, kid))

    with pytest.raises(CfAccessError, match="aud"):
        verify_access_jwt(token, cfg, fetcher=fetcher)


def test_wrong_issuer_rejected(rsa_key, kid, cfg):
    """Defence-in-depth against confused-deputy: same key, different team."""
    token = _make_jwt(rsa_key, kid, iss="https://attacker.cloudflareaccess.com")
    fetcher = _fake_fetcher(_jwks_for(rsa_key, kid))

    with pytest.raises(CfAccessError, match="(?i)issuer|iss"):
        verify_access_jwt(token, cfg, fetcher=fetcher)


def test_none_algorithm_rejected(rsa_key, kid, cfg):
    """A token forged with alg=none must be rejected (RS256 pinning)."""
    unsigned = jwt.encode(
        {
            "aud": "test-aud",
            "iss": "https://example.cloudflareaccess.com",
            "email": "u@e",
            "sub": "u",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        },
        "",
        algorithm="none",
        headers={"kid": kid},
    )
    fetcher = _fake_fetcher(_jwks_for(rsa_key, kid))

    with pytest.raises(CfAccessError):
        verify_access_jwt(unsigned, cfg, fetcher=fetcher)
