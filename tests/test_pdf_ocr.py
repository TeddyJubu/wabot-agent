from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from wabot_agent.config import Settings
from wabot_agent.file_processing import _read_pdf


def test_read_pdf_uses_ocr_when_text_extraction_empty(tmp_path: Path) -> None:
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    settings = Settings(
        file_use_system_tools=True,
        file_ocr_enabled=True,
        file_pdf_ocr_max_pages=5,
        _env_file=None,
    )

    with (
        patch(
            "wabot_agent.system_tools.pdftotext_extract",
            return_value=("", ["pdftotext produced no output (scanned PDF?)"]),
        ),
        patch(
            "wabot_agent.file_processing._read_pdf_pypdf",
            return_value=("", ["no extractable text in PDF (may be scanned images)"]),
        ),
        patch(
            "wabot_agent.system_tools.pdf_ocr_extract",
            return_value=("[page 1]\nHow to Work With Manus", ["pdf OCR: 1 page(s) at 200 dpi"]),
        ),
    ):
        body, warnings = _read_pdf(pdf, 5000, use_system=True, settings=settings)

    assert "Manus" in body
    assert any("page OCR" in w for w in warnings)
