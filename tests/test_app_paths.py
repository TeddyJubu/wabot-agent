from __future__ import annotations

from wabot_agent.app_paths import resolve_app_root, static_directory


def test_resolve_app_root_from_src_layout() -> None:
    root = resolve_app_root()
    assert (root / "main.py").is_file()
    assert (root / "static").is_dir()


def test_static_directory_points_at_built_assets() -> None:
    static = static_directory()
    assets = list((static / "assets").glob("index-*.js"))
    assert assets, "expected at least one built dashboard bundle"
