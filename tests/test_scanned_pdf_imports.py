from __future__ import annotations

from io import BytesIO
from unittest.mock import patch

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from app.services.scanned_pdf_imports import (
    EncryptedScannedPdfError,
    ScannedPdfInputLimitError,
    ScannedPdfParseError,
    parse_scanned_pdf_bytes,
)


def _synthetic_scanned_pdf(page_count: int = 3) -> bytes:
    output = BytesIO()
    canvas = Canvas(output, pagesize=A4)
    page_image = Image.new("RGB", (640, 900), "white")
    for _ in range(page_count):
        canvas.drawInlineImage(page_image, 0, 0, width=A4[0], height=A4[1])
        canvas.showPage()
    canvas.save()
    page_image.close()
    return output.getvalue()


def test_scanned_pdf_renders_pages_and_keeps_academic_source_page() -> None:
    ocr_results = iter(
        (
            "합성 표지",
            "교과학습발달상황\n학년도|학년|학기|과목|원점수\n2026|3|1|합성 스캔 과목|91",
            "세부능력 및 특기사항\nSYNTHETIC_PRIVATE_DETAIL_MUST_NOT_SURVIVE",
        )
    )
    rendered_sizes: list[tuple[int, int]] = []

    def synthetic_ocr(image: Image.Image) -> str:
        rendered_sizes.append(image.size)
        return next(ocr_results)

    preview = parse_scanned_pdf_bytes(_synthetic_scanned_pdf(), ocr_engine=synthetic_ocr)

    assert len(preview.rows) == 1
    assert preview.rows[0].subject_name == "합성 스캔 과목"
    assert preview.rows[0].source_page == 2
    assert preview.source_format == "scanned_pdf"
    assert len(rendered_sizes) == 3
    assert "SYNTHETIC_PRIVATE_DETAIL_MUST_NOT_SURVIVE" not in repr(preview)
    assert ("OCR_REVIEW_REQUIRED", "ocr_text") in [
        (issue.code, issue.field) for issue in preview.issues
    ]


def test_pdf_with_missing_eof_marker_is_recovered_when_pdfium_can_render_it() -> None:
    source = _synthetic_scanned_pdf(1)
    damaged = source.rsplit(b"%%EOF", maxsplit=1)[0]

    preview = parse_scanned_pdf_bytes(
        damaged,
        ocr_engine=lambda _image: (
            "교과학습발달상황\n학년도|학년|학기|과목|원점수\n2026|3|1|합성 복구 과목|90"
        ),
    )

    assert preview.rows[0].subject_name == "합성 복구 과목"


def test_encrypted_scanned_pdf_is_rejected_without_password_guessing() -> None:
    reader = PdfReader(BytesIO(_synthetic_scanned_pdf(1)))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt("synthetic-password")
    output = BytesIO()
    writer.write(output)

    with pytest.raises(EncryptedScannedPdfError):
        parse_scanned_pdf_bytes(output.getvalue(), ocr_engine=lambda _image: "")


def test_corrupt_pdf_is_rejected_without_partial_rows() -> None:
    with pytest.raises(ScannedPdfParseError):
        parse_scanned_pdf_bytes(b"%PDF-1.7\ncorrupt", ocr_engine=lambda _image: "")


def test_scanned_pdf_page_limit_is_checked_before_ocr() -> None:
    with patch("app.services.scanned_pdf_imports.MAX_SCANNED_PDF_PAGES", 1):
        with pytest.raises(ScannedPdfInputLimitError):
            parse_scanned_pdf_bytes(_synthetic_scanned_pdf(2), ocr_engine=lambda _image: "")
