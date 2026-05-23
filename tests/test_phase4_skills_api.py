"""Phase 4 — Skills API tests.

Covers:
- Auth required on all endpoints.
- List on fresh DB.
- POST /skills/scan.
- POST /skills/install/zip — valid zip, path-traversal zip, symlink zip,
  size-exceeded zip, too-many-members zip, duplicate slug.
- POST /skills/install/registry — success.
- DELETE /skills/{slug} — cascades to subagent_skills.
- GET /skills/registry/search — filters by q.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wabot_agent.api import create_app
from wabot_agent.config import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_settings(tmp_path: Path) -> Settings:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    return Settings(
        WABOT_AGENT_OFFLINE_MODE=True,
        WABOT_AGENT_DATA_DIR=tmp_path,
        WABOT_AGENT_DB_PATH=tmp_path / "agent.db",
        WABOT_AGENT_LOG_PATH=tmp_path / "events.jsonl",
        WABOT_AGENT_RUNTIME_OVERRIDES_PATH=tmp_path / "runtime_overrides.json",
        WABOT_AGENT_MCP_CONFIG=None,
        WABOT_AGENT_SKILLS_DIR=skills_dir,
        WABOT_AGENT_SEND_POLICY="dry_run",
        WABOT_INBOUND_TOKEN="test-inbound",
        OPENROUTER_API_KEY=None,
        _env_file=None,
    )


def auth_headers(settings: Settings) -> dict[str, str]:
    return {"X-Operator-Token": settings.operator_token or ""}


@pytest.fixture
def ctx(tmp_path: Path):
    settings = make_settings(tmp_path).model_copy(update={"operator_token": "secret"})
    client = TestClient(create_app(settings), raise_server_exceptions=True)
    return client, settings


# ---------------------------------------------------------------------------
# Helper: build an in-memory zip
# ---------------------------------------------------------------------------


def _make_zip(members: list[tuple[str, bytes]], *, symlink_name: str | None = None) -> bytes:
    """Build a zip in memory.  Pass symlink_name to add a symlink member."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for name, data in members:
            zf.writestr(name, data)
        if symlink_name:
            info = zipfile.ZipInfo(symlink_name)
            # Set symlink bit in external_attr (unix mode 0o120777).
            info.external_attr = 0o120777 << 16
            zf.writestr(info, b"../etc/passwd")
    return buf.getvalue()


def _valid_zip(slug: str = "test-skill") -> bytes:
    skill_md = (
        "---\n"
        f"slug: {slug}\n"
        f"name: Test Skill\n"
        "description: A test skill.\n"
        "version: 1.0.0\n"
        "---\n\n"
        "# Test Skill\n"
    ).encode()
    return _make_zip([
        (f"{slug}/SKILL.md", skill_md),
        (f"{slug}/script.py", b"print('hello')"),
    ])


# ---------------------------------------------------------------------------
# Auth: all endpoints require token
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("get", "/api/skills", {}),
        ("post", "/api/skills/scan", {}),
        ("post", "/api/skills/install/registry", {"json": {"registry_id": "x"}}),
        ("delete", "/api/skills/nonexistent", {}),
        ("get", "/api/skills/registry/search", {}),
    ],
)
def test_skills_auth_required(ctx, method, path, kwargs):
    client, _ = ctx
    resp = getattr(client, method)(path, **kwargs)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# List on fresh DB
# ---------------------------------------------------------------------------


def test_list_skills_empty(ctx):
    client, settings = ctx
    resp = client.get("/api/skills", headers=auth_headers(settings))
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


def test_scan_local_finds_skill(ctx):
    client, settings = ctx
    # Create a skill on disk first.
    skill_dir = Path(settings.skills_dir) / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nslug: my-skill\nname: My Skill\ndescription: Demo.\n---\n\n# My Skill\n",
        encoding="utf-8",
    )
    resp = client.post("/api/skills/scan", headers=auth_headers(settings))
    assert resp.status_code == 200
    data = resp.json()
    assert data["added"] == 1
    assert data["removed"] == 0


# ---------------------------------------------------------------------------
# ZIP install — happy path
# ---------------------------------------------------------------------------


def test_install_zip_valid(ctx):
    client, settings = ctx
    zip_bytes = _valid_zip("my-skill")
    resp = client.post(
        "/api/skills/install/zip",
        headers=auth_headers(settings),
        files={"file": ("my-skill.skill", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["slug"] == "my-skill"
    assert data["source"] == "zip"
    # Confirm it shows up in the list.
    list_resp = client.get("/api/skills", headers=auth_headers(settings))
    slugs = [s["slug"] for s in list_resp.json()]
    assert "my-skill" in slugs


# ---------------------------------------------------------------------------
# ZIP install — path traversal rejected
# ---------------------------------------------------------------------------


def test_install_zip_path_traversal_rejected(ctx):
    client, settings = ctx
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        skill_md = b"---\nslug: evil-skill\nname: Evil\ndescription: x\n---\n"
        zf.writestr("evil-skill/SKILL.md", skill_md)
        zf.writestr("../etc/passwd", b"root:x:0:0:root:/root:/bin/bash")
    zip_bytes = buf.getvalue()
    resp = client.post(
        "/api/skills/install/zip",
        headers=auth_headers(settings),
        files={"file": ("evil.skill", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 400
    assert ".." in resp.json()["detail"]
    # Nothing installed.
    list_resp = client.get("/api/skills", headers=auth_headers(settings))
    assert list_resp.json() == []


# ---------------------------------------------------------------------------
# ZIP install — symlink rejected
# ---------------------------------------------------------------------------


def test_install_zip_symlink_rejected(ctx):
    client, settings = ctx
    skill_md = b"---\nslug: sym-skill\nname: Sym\ndescription: x\n---\n"
    zip_bytes = _make_zip(
        [("sym-skill/SKILL.md", skill_md)],
        symlink_name="sym-skill/evil_link",
    )
    resp = client.post(
        "/api/skills/install/zip",
        headers=auth_headers(settings),
        files={"file": ("sym.skill", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 400
    assert "symlink" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# ZIP install — total size > 50 MB rejected (mock)
# ---------------------------------------------------------------------------


def test_install_zip_size_exceeded_rejected(ctx):
    client, settings = ctx
    # We monkeypatch the size check inside install_from_zip via a real zip
    # whose sum reports > 50 MB.
    import wabot_agent.skills_service as ss

    original = ss._MAX_TOTAL_UNCOMPRESSED
    ss._MAX_TOTAL_UNCOMPRESSED = 10  # tiny threshold for the test
    try:
        zip_bytes = _valid_zip("size-skill")
        resp = client.post(
            "/api/skills/install/zip",
            headers=auth_headers(settings),
            files={"file": ("size.skill", zip_bytes, "application/zip")},
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "50 MB" in detail or "uncompressed" in detail or "10" in detail
    finally:
        ss._MAX_TOTAL_UNCOMPRESSED = original


# ---------------------------------------------------------------------------
# ZIP install — > 500 members rejected
# ---------------------------------------------------------------------------


def test_install_zip_too_many_members_rejected(ctx):
    client, settings = ctx
    import wabot_agent.skills_service as ss

    original = ss._MAX_MEMBER_COUNT
    ss._MAX_MEMBER_COUNT = 2  # tiny threshold
    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "many-skill/SKILL.md",
                b"---\nslug: many-skill\nname: Many\ndescription: x\n---\n",
            )
            for i in range(5):
                zf.writestr(f"many-skill/file_{i}.txt", b"data")
        resp = client.post(
            "/api/skills/install/zip",
            headers=auth_headers(settings),
            files={"file": ("many.skill", buf.getvalue(), "application/zip")},
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "member" in detail.lower() or "500" in detail or "2" in detail
    finally:
        ss._MAX_MEMBER_COUNT = original


# ---------------------------------------------------------------------------
# ZIP install — duplicate slug rejected
# ---------------------------------------------------------------------------


def test_install_zip_duplicate_slug_rejected(ctx):
    client, settings = ctx
    zip_bytes = _valid_zip("dup-skill")
    headers = auth_headers(settings)
    r1 = client.post(
        "/api/skills/install/zip",
        headers=headers,
        files={"file": ("dup.skill", zip_bytes, "application/zip")},
    )
    assert r1.status_code == 201

    r2 = client.post(
        "/api/skills/install/zip",
        headers=headers,
        files={"file": ("dup.skill", _valid_zip("dup-skill"), "application/zip")},
    )
    assert r2.status_code == 400
    assert "already exists" in r2.json()["detail"]


# ---------------------------------------------------------------------------
# Registry install
# ---------------------------------------------------------------------------


def test_install_from_registry(ctx):
    client, settings = ctx
    headers = auth_headers(settings)
    # Use a known id from data/skills_registry.json.
    resp = client.post(
        "/api/skills/install/registry",
        headers=headers,
        json={"registry_id": "sk_web_research"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["slug"] == "web-research"
    assert data["source"] == "registry"


def test_install_from_registry_unknown_id(ctx):
    client, settings = ctx
    resp = client.post(
        "/api/skills/install/registry",
        headers=auth_headers(settings),
        json={"registry_id": "sk_does_not_exist"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE cascades to subagent_skills
# ---------------------------------------------------------------------------


def test_delete_skill_cascades(ctx):
    client, settings = ctx
    headers = auth_headers(settings)

    # Install a skill.
    r = client.post(
        "/api/skills/install/registry",
        headers=headers,
        json={"registry_id": "sk_scheduler"},
    )
    assert r.status_code == 201
    skill_id = r.json()["id"]

    # Get an agent to assign the skill to.
    agents_resp = client.get("/api/agents", headers=headers)
    agent_slug = agents_resp.json()[0]["slug"]

    # Assign skill to agent.
    client.put(
        f"/api/agents/{agent_slug}/skills",
        headers=headers,
        json={"skill_ids": [skill_id]},
    )

    # Delete the skill.
    del_resp = client.delete("/api/skills/scheduler", headers=headers)
    assert del_resp.status_code == 204

    # Confirm skill is gone.
    list_resp = client.get("/api/skills", headers=headers)
    slugs = [s["slug"] for s in list_resp.json()]
    assert "scheduler" not in slugs

    # Confirm agent no longer references the skill.
    agent_resp = client.get(f"/api/agents/{agent_slug}", headers=headers)
    assert skill_id not in agent_resp.json()["skill_ids"]


def test_delete_skill_not_found(ctx):
    client, settings = ctx
    resp = client.delete("/api/skills/nonexistent", headers=auth_headers(settings))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Registry search — filters by q
# ---------------------------------------------------------------------------


def test_registry_search_no_query(ctx):
    client, settings = ctx
    resp = client.get("/api/skills/registry/search", headers=auth_headers(settings))
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) >= 4  # at least 4 entries seeded


def test_registry_search_with_query(ctx):
    client, settings = ctx
    resp = client.get(
        "/api/skills/registry/search",
        headers=auth_headers(settings),
        params={"q": "web"},
    )
    assert resp.status_code == 200
    entries = resp.json()
    assert all(
        "web" in (e["name"] + e["description"] + " ".join(e["tags"])).lower()
        for e in entries
    )
    assert any(e["slug"] == "web-research" for e in entries)


def test_registry_search_no_match(ctx):
    client, settings = ctx
    resp = client.get(
        "/api/skills/registry/search",
        headers=auth_headers(settings),
        params={"q": "zzznomatch999"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# BLOCKER 1 — Path.relative_to sibling-prefix traversal guard
# ---------------------------------------------------------------------------


def test_install_zip_rejects_sibling_dir_traversal(ctx, tmp_path):
    """A zip member whose resolved path starts with target_dir's string but
    is actually outside it (e.g. /skills/ab vs /skills/abcdef) must be
    rejected by the relative_to guard."""
    client, settings = ctx
    headers = auth_headers(settings)

    # Build a zip whose SKILL.md identifies slug "abcdef" but contains a
    # member that traverses to a sibling directory ("../sibling/payload.txt").
    # When target_dir is skills_dir/abcdef, resolving ../sibling/payload.txt
    # gives skills_dir/sibling/payload.txt, which is NOT under abcdef —
    # relative_to should raise and we should get a 400.
    import io as _io
    import zipfile as _zipfile

    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as zf:
        skill_md = (
            b"---\n"
            b"slug: abcdef\n"
            b"name: Abcdef Skill\n"
            b"description: Traversal test.\n"
            b"version: 1.0.0\n"
            b"---\n"
        )
        zf.writestr("abcdef/SKILL.md", skill_md)
        # Member that traverses out to a sibling dir.
        zf.writestr("abcdef/../sibling/payload.txt", b"evil payload")

    resp = client.post(
        "/api/skills/install/zip",
        headers=headers,
        files={"file": ("abcdef.skill", buf.getvalue(), "application/zip")},
    )
    assert resp.status_code == 400

    # Confirm nothing was written outside the skills dir.
    sibling_dir = Path(settings.skills_dir) / "sibling"
    assert not sibling_dir.exists(), "sibling dir must not have been created"
