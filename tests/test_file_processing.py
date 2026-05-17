from __future__ import annotations

from pathlib import Path

from wabot_agent.config import Settings
from wabot_agent.file_processing import (
    classify_file,
    process_file_at_path,
    whatsapp_send_kind_for_path,
)


def test_classify_and_process_text(tmp_path: Path) -> None:
    path = tmp_path / "note.txt"
    path.write_text("hello file processing", encoding="utf-8")
    assert classify_file(path) == "text"
    result = process_file_at_path(path, settings=Settings(_env_file=None))
    assert result["ok"] is True
    assert "hello" in result["excerpt"]


def test_whatsapp_send_kind_routing(tmp_path: Path) -> None:
    assert whatsapp_send_kind_for_path(tmp_path / "x.png") == "image"
    assert whatsapp_send_kind_for_path(tmp_path / "x.mp4") == "video"
    assert whatsapp_send_kind_for_path(tmp_path / "x.pdf") == "document"
