from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from app.services.structured_imports import StructuredInputLimitError
from app.services.text_pdf_imports import (
    MAX_TEXT_PDF_BYTES,
    EncryptedTextPdfError,
    parse_academic_record_page_texts,
    parse_text_pdf_bytes,
)


def _synthetic_text_pdf() -> bytes:
    output = BytesIO()
    canvas = Canvas(output, pagesize=A4)
    canvas.drawString(72, 760, "SYNTHETIC PREAMBLE")
    canvas.showPage()
    text = canvas.beginText(72, 760)
    for line in (
        "ACADEMIC_RECORD_TABLE",
        "academic_year|grade|semester|subject_name|raw_score",
        "2026|3|1|Synthetic subject|91",
        "DETAIL_NOTES",
        "SYNTHETIC_PRIVATE_DETAIL_MUST_NOT_SURVIVE",
    ):
        text.textLine(line)
    canvas.drawText(text)
    canvas.save()
    return output.getvalue()


def test_text_pdf_finds_academic_table_without_fixed_page_and_excludes_details() -> None:
    preview = parse_text_pdf_bytes(_synthetic_text_pdf())

    assert len(preview.rows) == 1
    assert preview.rows[0].subject_name == "Synthetic subject"
    assert preview.rows[0].source_page == 2
    assert preview.source_format == "text_pdf"
    assert "SYNTHETIC_PRIVATE_DETAIL_MUST_NOT_SURVIVE" not in repr(preview)


def test_korean_section_marker_is_found_and_detail_section_is_excluded() -> None:
    preview = parse_academic_record_page_texts(
        (
            "합성 표지",
            "교과학습발달상황\n학년도|학년|학기|과목|원점수\n2026|3|1|합성 과목|P",
            "세부능력 및 특기사항\n합성 민감 원문",
        ),
        source_hash="a" * 64,
    )

    assert len(preview.rows) == 1
    assert preview.rows[0].raw_score == "P"
    assert preview.rows[0].source_page == 2
    assert "합성 민감 원문" not in repr(preview)


def test_missing_academic_section_is_reported_without_guessing() -> None:
    preview = parse_academic_record_page_texts(
        ("합성 표지", "관련 없는 합성 본문"), source_hash="b" * 64
    )

    assert preview.rows == ()
    assert [(issue.code, issue.source_page) for issue in preview.issues] == [
        ("ACADEMIC_SECTION_NOT_FOUND", None)
    ]


def test_encrypted_text_pdf_is_rejected() -> None:
    reader = PdfReader(BytesIO(_synthetic_text_pdf()))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt("synthetic-password")
    output = BytesIO()
    writer.write(output)

    with pytest.raises(EncryptedTextPdfError):
        parse_text_pdf_bytes(output.getvalue())


def test_oversized_text_pdf_is_rejected_before_parsing() -> None:
    with pytest.raises(StructuredInputLimitError):
        parse_text_pdf_bytes(b"x" * (MAX_TEXT_PDF_BYTES + 1))
