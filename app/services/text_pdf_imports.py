from __future__ import annotations

import csv
import hashlib
from dataclasses import replace
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.services.structured_imports import (
    HEADER_ALIASES,
    NormalizationIssue,
    NormalizedCourseRow,
    StructuredImportPreview,
    StructuredInputLimitError,
    parse_structured_text,
)

MAX_TEXT_PDF_BYTES = 20 * 1024 * 1024
MAX_TEXT_PDF_PAGES = 100
ACADEMIC_SECTION_MARKERS = ("교과학습발달상황", "ACADEMIC_RECORD_TABLE")
DETAIL_SECTION_MARKERS = ("세부능력 및 특기사항", "DETAIL_NOTES")
TABLE_DELIMITERS = ("\t", "|", ",", ";")


class TextPdfParseError(ValueError):
    pass


class EncryptedTextPdfError(TextPdfParseError):
    pass


def _first_marker(text: str, markers: tuple[str, ...]) -> tuple[int, str] | None:
    matches = ((text.find(marker), marker) for marker in markers)
    present = tuple((position, marker) for position, marker in matches if position >= 0)
    return min(present, default=None, key=lambda item: item[0])


def _table_header_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        for delimiter in TABLE_DELIMITERS:
            if delimiter not in line:
                continue
            headers = next(csv.reader([line], delimiter=delimiter))
            recognized = tuple(
                HEADER_ALIASES[header.strip()]
                for header in headers
                if header.strip() in HEADER_ALIASES
            )
            if "subject_name" in recognized and len(recognized) >= 2:
                return index
    return None


def parse_academic_record_page_texts(
    page_texts: tuple[str, ...], *, source_hash: str
) -> StructuredImportPreview:
    if len(source_hash) != 64:
        raise ValueError("PDF SHA-256 형식이 올바르지 않습니다.")

    academic_section_found = False
    table_header_found = False
    rows: list[NormalizedCourseRow] = []
    issues: list[NormalizationIssue] = []
    ignored_headers: list[str] = []

    for page_number, page_text in enumerate(page_texts, start=1):
        section_text = page_text
        if not academic_section_found:
            academic_marker = _first_marker(section_text, ACADEMIC_SECTION_MARKERS)
            if academic_marker is None:
                continue
            academic_section_found = True
            marker_position, marker = academic_marker
            section_text = section_text[marker_position + len(marker) :]

        detail_marker = _first_marker(section_text, DETAIL_SECTION_MARKERS)
        stop_after_page = detail_marker is not None
        if detail_marker is not None:
            section_text = section_text[: detail_marker[0]]

        lines = [line.strip() for line in section_text.splitlines() if line.strip()]
        header_index = _table_header_index(lines)
        if header_index is not None:
            table_header_found = True
            table_preview = parse_structured_text(
                "\n".join(lines[header_index:]), source_format="pasted_table"
            )
            rows.extend(replace(row, source_page=page_number) for row in table_preview.rows)
            issues.extend(replace(issue, source_page=page_number) for issue in table_preview.issues)
            for header in table_preview.ignored_headers:
                if header not in ignored_headers:
                    ignored_headers.append(header)

        if stop_after_page:
            break

    if not academic_section_found:
        issues.append(NormalizationIssue("ACADEMIC_SECTION_NOT_FOUND", "academic_section", 0))
    elif not table_header_found:
        issues.append(NormalizationIssue("TABLE_HEADER_NOT_FOUND", "table_header", 0))

    return StructuredImportPreview(
        source_hash=source_hash,
        source_format="text_pdf",
        rows=tuple(rows),
        issues=tuple(issues),
        ignored_headers=tuple(ignored_headers),
    )


def parse_text_pdf_bytes(source: bytes) -> StructuredImportPreview:
    if len(source) > MAX_TEXT_PDF_BYTES:
        raise StructuredInputLimitError("텍스트 PDF 입력 크기 제한을 초과했습니다.")

    try:
        reader = PdfReader(BytesIO(source), strict=False)
    except (PdfReadError, OSError, ValueError) as error:
        raise TextPdfParseError("텍스트 PDF 구조를 읽을 수 없습니다.") from error

    if reader.is_encrypted:
        raise EncryptedTextPdfError("암호화된 PDF는 텍스트 입력으로 처리할 수 없습니다.")
    if len(reader.pages) > MAX_TEXT_PDF_PAGES:
        raise StructuredInputLimitError("텍스트 PDF 페이지 수 제한을 초과했습니다.")

    try:
        page_texts = tuple(page.extract_text() or "" for page in reader.pages)
    except Exception as error:
        raise TextPdfParseError("PDF 텍스트 추출에 실패했습니다.") from error

    source_hash = hashlib.sha256(source).hexdigest()
    if not any(text.strip() for text in page_texts):
        return StructuredImportPreview(
            source_hash=source_hash,
            source_format="text_pdf",
            rows=(),
            issues=(NormalizationIssue("TEXT_NOT_AVAILABLE", "pdf_text", 0),),
            ignored_headers=(),
        )
    return parse_academic_record_page_texts(page_texts, source_hash=source_hash)
