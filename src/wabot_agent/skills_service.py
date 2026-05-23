"""skills_service — CRUD + install logic for the skills table.

Phase 4 service layer.  All functions take a MemoryStore as their first
argument, mirroring agents_service.py.

Security-critical notes (install_from_zip):
  - Every zip member is validated before any bytes hit disk.
  - Path traversal, symlinks, and size bombs are all rejected up front.
  - Extraction target must not already exist (no silent overwrites).
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import stat
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import Settings
    from .memory import MemoryStore

logger = logging.getLogger(__name__)

# Slug pattern for skills (allows hyphens, unlike the agent slug pattern).
_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")

# Zip safety limits
_MAX_TOTAL_UNCOMPRESSED = 50 * 1024 * 1024   # 50 MB
_MAX_SINGLE_FILE = 10 * 1024 * 1024           # 10 MB
_MAX_MEMBER_COUNT = 500


def _row_to_dict(row: Any) -> dict:
    try:
        return dict(row)
    except (TypeError, ValueError):
        raise


def _registry_path() -> Path:
    """Return the path to data/skills_registry.json shipped with the package."""
    # Walk up from this file: src/wabot_agent/ -> src/ -> project_root/
    return Path(__file__).resolve().parents[2] / "data" / "skills_registry.json"


# ---------------------------------------------------------------------------
# list_skills
# ---------------------------------------------------------------------------


def list_skills(store: MemoryStore) -> list[dict]:
    """Return all skills with installed/enabled flags."""
    with store.connect() as conn:
        rows = conn.execute(
            "select * from skills order by installed_at desc"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# scan_local
# ---------------------------------------------------------------------------


def scan_local(store: MemoryStore, settings: Settings) -> dict:
    """Re-scan settings.skills_dir, upsert skill rows with source='local'.

    Returns {added: int, removed: int}.
    """
    skills_dir: Path = Path(settings.skills_dir)
    added = 0
    removed = 0

    with store.connect() as conn:
        # Build the set of slugs currently on disk.
        disk_slugs: set[str] = set()
        if skills_dir.exists():
            for skill_md in skills_dir.glob("*/SKILL.md"):
                slug = skill_md.parent.name
                if not _SLUG_RE.match(slug):
                    logger.debug("scan_local: ignoring invalid slug %r", slug)
                    continue
                disk_slugs.add(slug)

                # Parse the SKILL.md for frontmatter fields.
                text = skill_md.read_text(encoding="utf-8")
                display_name = slug
                description = ""
                version = None
                in_frontmatter = False
                for i, line in enumerate(text.splitlines()):
                    if i == 0 and line.strip() == "---":
                        in_frontmatter = True
                        continue
                    if in_frontmatter and line.strip() == "---":
                        break
                    if in_frontmatter:
                        if line.startswith("name:"):
                            display_name = line.split(":", 1)[1].strip().strip('"')
                        elif line.startswith("description:"):
                            description = line.split(":", 1)[1].strip().strip('"')
                        elif line.startswith("version:"):
                            version = line.split(":", 1)[1].strip().strip('"')

                install_path = str(skill_md.parent.resolve())
                existing = conn.execute(
                    "select id from skills where slug = ?", (slug,)
                ).fetchone()
                if existing is None:
                    conn.execute(
                        """
                        insert into skills
                            (slug, display_name, description, source,
                             install_path, version, is_enabled)
                        values (?, ?, ?, 'local', ?, ?, 1)
                        """,
                        (slug, display_name, description, install_path, version),
                    )
                    added += 1
                else:
                    conn.execute(
                        """
                        update skills set
                            display_name = ?,
                            description  = ?,
                            install_path = ?,
                            version      = ?,
                            is_enabled   = 1
                        where slug = ?
                        """,
                        (display_name, description, install_path, version, slug),
                    )

        # Mark skills that no longer exist on disk as disabled.
        all_local = conn.execute(
            "select id, slug from skills where source = 'local'"
        ).fetchall()
        for row in all_local:
            if row["slug"] not in disk_slugs:
                conn.execute(
                    "update skills set is_enabled = 0 where id = ?", (row["id"],)
                )
                removed += 1

        conn.commit()

    return {"added": added, "removed": removed}


# ---------------------------------------------------------------------------
# install_from_zip
# ---------------------------------------------------------------------------


def install_from_zip(
    store: MemoryStore,
    settings: Settings,
    file_path: Path,
) -> dict:
    """Extract a .skill zip into settings.skills_dir and register in DB.

    SECURITY:
      - Rejects absolute paths, '..' components, symlinks.
      - Enforces 50 MB total / 10 MB per file / 500 member limits.
      - Refuses to overwrite an existing skill directory.
    """
    skills_dir = Path(settings.skills_dir)
    skills_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(file_path, "r") as zf:
        members = zf.infolist()

        # --- member count check ---
        if len(members) > _MAX_MEMBER_COUNT:
            raise ValueError(
                f"zip contains {len(members)} members; maximum is {_MAX_MEMBER_COUNT}"
            )

        # --- total size check (sum of uncompressed sizes) ---
        total_size = sum(m.file_size for m in members)
        if total_size > _MAX_TOTAL_UNCOMPRESSED:
            raise ValueError(
                f"zip total uncompressed size {total_size} bytes exceeds 50 MB limit"
            )

        # --- per-member validation ---
        for member in members:
            name = member.filename

            # Absolute path or path traversal
            if name.startswith("/") or name.startswith("\\"):
                raise ValueError(f"zip member has absolute path: {name!r}")
            parts = Path(name).parts
            if ".." in parts:
                raise ValueError(f"zip member contains '..': {name!r}")

            # Symlink check: unix mode is in the high 16 bits of external_attr.
            unix_mode = (member.external_attr >> 16) & 0xFFFF
            if unix_mode and stat.S_ISLNK(unix_mode):
                raise ValueError(f"zip member is a symlink: {name!r}")

            # Single-file size
            if member.file_size > _MAX_SINGLE_FILE:
                raise ValueError(
                    f"zip member {name!r} is {member.file_size} bytes; exceeds 10 MB limit"
                )

        # --- locate SKILL.md ---
        skill_md_names = [
            m.filename for m in members if m.filename.endswith("SKILL.md")
        ]
        if not skill_md_names:
            raise ValueError("zip does not contain a SKILL.md file")

        # Pick the shallowest SKILL.md (handles both flat and nested zips).
        skill_md_names.sort(key=lambda p: p.count("/"))
        skill_md_name = skill_md_names[0]
        skill_md_data = zf.read(skill_md_name).decode("utf-8")

        # --- derive slug from frontmatter or directory structure ---
        slug: str | None = None
        display_name = ""
        description = ""
        version = None
        origin_url = None

        in_fm = False
        for i, line in enumerate(skill_md_data.splitlines()):
            if i == 0 and line.strip() == "---":
                in_fm = True
                continue
            if in_fm and line.strip() == "---":
                break
            if in_fm:
                if line.startswith("slug:"):
                    slug = line.split(":", 1)[1].strip().strip('"')
                elif line.startswith("name:"):
                    display_name = line.split(":", 1)[1].strip().strip('"')
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip().strip('"')
                elif line.startswith("version:"):
                    version = line.split(":", 1)[1].strip().strip('"')
                elif line.startswith("source_url:"):
                    origin_url = line.split(":", 1)[1].strip().strip('"')

        # Fall back: infer slug from the parent directory of SKILL.md in the zip.
        if not slug:
            parts = skill_md_name.rsplit("/", 1)
            slug = parts[0].split("/")[-1] if "/" in skill_md_name else Path(file_path).stem

        # Strip file-extension artifacts (e.g. "my-skill.skill" → "my-skill").
        if slug.endswith(".skill"):
            slug = slug[: -len(".skill")]

        if not slug or not _SLUG_RE.match(slug):
            raise ValueError(
                f"derived slug {slug!r} is invalid; "
                "must match ^[a-z][a-z0-9-]{{1,63}}$"
            )

        if not display_name:
            display_name = slug

        # --- refuse to overwrite ---
        target_dir = skills_dir / slug
        if target_dir.exists():
            raise ValueError(
                f"skill directory {target_dir} already exists; "
                "delete the existing skill before re-installing"
            )

        # --- extract ---
        # We extract only files whose resolved path stays inside target_dir.
        target_dir.mkdir(parents=True)
        try:
            prefix = skill_md_name.rsplit("/", 1)[0] + "/" if "/" in skill_md_name else ""
            for member in members:
                if member.is_dir():
                    continue
                rel = member.filename
                if prefix and rel.startswith(prefix):
                    rel = rel[len(prefix):]
                dest = (target_dir / rel).resolve()
                # Final guard: resolved path must be inside target_dir.
                # Use Path.relative_to instead of startswith to avoid
                # prefix-collision bypass (e.g. /skills/ab vs /skills/abcdef).
                target_resolved = target_dir.resolve()
                try:
                    dest.relative_to(target_resolved)
                except ValueError as exc:
                    raise ValueError(
                        "zip member resolves outside skill directory: " + member.filename
                    ) from exc
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(member.filename))
        except Exception:
            # Clean up the partial extraction on failure.
            shutil.rmtree(target_dir, ignore_errors=True)
            raise

    install_path = str(target_dir.resolve())

    with store.connect() as conn:
        conn.execute(
            """
            insert into skills
                (slug, display_name, description, source,
                 install_path, origin_url, version, is_enabled)
            values (?, ?, ?, 'zip', ?, ?, ?, 1)
            """,
            (slug, display_name, description, install_path, origin_url, version),
        )
        conn.commit()
        row = conn.execute(
            "select * from skills where slug = ?", (slug,)
        ).fetchone()
        return _row_to_dict(row)


# ---------------------------------------------------------------------------
# install_from_registry
# ---------------------------------------------------------------------------


def install_from_registry(
    store: MemoryStore,
    settings: Settings,
    registry_id: str,
) -> dict:
    """Install a skill from the curated registry by id.

    v1: installs a synthetic SKILL.md placeholder; no network download.
    TODO(v1.1): if entry has a 'fetch_url' field, download and extract the
    real bundle (see Task 4.2 spec comment).
    """
    entries = registry_search("")
    entry = next((e for e in entries if e["id"] == registry_id), None)
    if entry is None:
        raise ValueError(f"registry entry {registry_id!r} not found")

    slug = entry["slug"]
    skills_dir = Path(settings.skills_dir)
    skills_dir.mkdir(parents=True, exist_ok=True)
    target_dir = skills_dir / slug

    if target_dir.exists():
        raise ValueError(
            f"skill directory {target_dir} already exists; "
            "delete the existing skill before re-installing"
        )

    target_dir.mkdir(parents=True)
    skill_md = (
        "---\n"
        f"slug: {slug}\n"
        f"name: {entry['name']}\n"
        f"description: {entry['description']}\n"
        f"version: {entry['version']}\n"
        f"source_url: {entry['source_url']}\n"
        "---\n\n"
        f"# {entry['name']}\n\n"
        f"{entry['description']}\n\n"
        "_This skill was installed from the curated registry (v1 placeholder)._\n"
    )
    (target_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    with store.connect() as conn:
        conn.execute(
            """
            insert or ignore into skills
                (slug, display_name, description, source,
                 install_path, origin_url, version, is_enabled)
            values (?, ?, ?, 'registry', ?, ?, ?, 1)
            """,
            (
                slug,
                entry["name"],
                entry["description"],
                str(target_dir.resolve()),
                entry["source_url"],
                entry["version"],
            ),
        )
        conn.commit()
        row = conn.execute(
            "select * from skills where slug = ?", (slug,)
        ).fetchone()
        return _row_to_dict(row)


# ---------------------------------------------------------------------------
# delete_skill
# ---------------------------------------------------------------------------


def delete_skill(
    store: MemoryStore,
    settings: Settings,
    slug: str,
) -> bool:
    """Remove a skill: cascades join rows, marks disabled, deletes directory.

    Returns False if the slug is not found.
    """
    with store.connect() as conn:
        row = conn.execute(
            "select id, install_path from skills where slug = ?", (slug,)
        ).fetchone()
        if row is None:
            return False

        skill_id = row["id"]
        install_path = row["install_path"]

        # Cascade: remove from subagent_skills.
        conn.execute(
            "delete from subagent_skills where skill_id = ?", (skill_id,)
        )
        # Remove the DB row entirely.
        conn.execute("delete from skills where id = ?", (skill_id,))
        conn.commit()

    # Remove the directory from disk (best-effort; don't fail if already gone).
    if install_path:
        skill_dir = Path(install_path)
        if skill_dir.exists() and skill_dir.is_dir():
            try:
                shutil.rmtree(skill_dir)
            except OSError as exc:
                logger.warning("delete_skill: could not remove %s: %s", skill_dir, exc)

    return True


# ---------------------------------------------------------------------------
# registry_search
# ---------------------------------------------------------------------------


def registry_search(query: str) -> list[dict]:
    """Load data/skills_registry.json and filter by query.

    Case-insensitive match on name + description + tags.
    Empty query returns all entries.
    """
    registry_file = _registry_path()
    try:
        entries: list[dict] = json.loads(registry_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("skills_service: could not load registry: %s", exc)
        return []

    if not query:
        return entries

    q = query.lower()
    results = []
    for entry in entries:
        haystack = " ".join([
            entry.get("name", ""),
            entry.get("description", ""),
            " ".join(entry.get("tags", [])),
        ]).lower()
        if q in haystack:
            results.append(entry)
    return results
