from __future__ import annotations

import os

from wabot_agent.cache_paths import configure_process_caches
from wabot_agent.config import Settings


def test_configure_process_caches_uses_data_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    settings = Settings(data_dir=tmp_path / "data", _env_file=None)
    settings.ensure_dirs()
    hf_home = configure_process_caches(settings)
    assert hf_home == (tmp_path / "data" / "hf-cache").resolve()
    assert os.environ["HF_HOME"] == str(hf_home)
    assert os.environ["HF_HUB_CACHE"] == str(hf_home / "hub")
    assert os.environ["XDG_CACHE_HOME"] == str((tmp_path / "data" / "cache").resolve())
