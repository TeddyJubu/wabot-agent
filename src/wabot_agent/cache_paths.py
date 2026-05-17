from __future__ import annotations

import os
from pathlib import Path

from .config import Settings


def configure_process_caches(settings: Settings) -> Path:
    """Use writable paths under data/ for model caches (systemd ProtectHome-safe)."""
    hf_home = settings.data_dir.resolve() / "hf-cache"
    xdg_cache = settings.data_dir.resolve() / "cache"
    hf_home.mkdir(parents=True, exist_ok=True)
    xdg_cache.mkdir(parents=True, exist_ok=True)
    hub_cache = hf_home / "hub"
    hub_cache.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("HF_HOME", str(hf_home))
    os.environ.setdefault("HF_HUB_CACHE", str(hub_cache))
    os.environ.setdefault("XDG_CACHE_HOME", str(xdg_cache))
    return hf_home
