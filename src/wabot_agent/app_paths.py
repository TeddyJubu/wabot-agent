from __future__ import annotations

from pathlib import Path


def resolve_app_root() -> Path:
    """Directory containing main.py, static/, and data/ (editable or installed layout)."""
    here = Path(__file__).resolve().parent
    for candidate in (here.parent, here.parent.parent, here.parent.parent.parent):
        if (candidate / "main.py").is_file():
            return candidate
    return Path.cwd()


def static_directory() -> Path:
    return resolve_app_root() / "static"


def knowledge_templates_directory() -> Path:
    return resolve_app_root() / "knowledge" / "templates"
