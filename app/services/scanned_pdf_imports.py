from __future__ import annotations

import hashlib
from collections.abc import Callable
from io import BytesIO

import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.services.image_imports import OcrEngine, run_local_tesseract
from app.services.structured_imports import (
    NormalizationIssue,
    StructuredImportPreview,
    StructuredInputLimitError,
)
from app.services.text_pdf_imports import (
    DETAIL_SECTION_MARKERS,
    parse_academic_record_page_texts,
)

MAX_SCANNED_PDF_BYTES = 20 * 1024 * 1024
MAX_SCANNED_PDF_PAGES = 50
MAX_RENDERED_PAGE_PIXELS = 20_000_000
MAX_RENDERED_TOTAL_PIXELS = 120_000_000
PDF_RENDER_SCALE = 2.5


class ScannedPdfParseError(ValueError):
    pass


class EncryptedScannedPdfError(ScannedPdfParseError):
    pass


class ScannedPdfInputLimitError(StructuredInputLimitError):
    pass


def _is_encrypted(source: bytes) -> bool:
    try:
        return PdfReader(BytesIO(source), strict=False).is_encrypted
    except (PdfReadError, OSError, ValueError):
        return False


def _contains_detail_section(text: str) -> bool:
    return any(marker in text for marker in DETAIL_SECTION_MARKERS)


def _rendered_page(
    page: pdfium.PdfPage,
    *,
    account_pixels: Callable[[int], None],
) -> Image.Image:
    width, height = page.get_size()
    rendered_width = max(1, int(width * PDF_RENDER_SCALE))
    rendered_height = max(1, int(height * PDF_RENDER_SCALE))
    pixels = rendered_width * rendered_height
    account_pixels(pixels)
    bitmap = None
    try:
        bitmap = page.render(scale=PDF_RENDER_SCALE)
        return bitmap.to_pil().convert("RGB")
    except Exception as error:
        raise ScannedPdfParseError("PDF 페이지 이미지 렌더링에 실패했습니다.") from error
    finally:
        if bitmap is not None:
            bitmap.close()


def parse_scanned_pdf_bytes(
    source: bytes, *, ocr_engine: OcrEngine = run_local_tesseract
) -> StructuredImportPreview:
    if len(source) > MAX_SCANNED_PDF_BYTES:
        raise ScannedPdfInputLimitError("이미지형 PDF 입력 크기 제한을 초과했습니다.")
    if _is_encrypted(source):
        raise EncryptedScannedPdfError("암호화된 PDF는 OCR 입력으로 처리할 수 없습니다.")

    try:
        document = pdfium.PdfDocument(source)
    except pdfium.PdfiumError as error:
        raise ScannedPdfParseError("이미지형 PDF 구조를 복구하거나 읽을 수 없습니다.") from error

    try:
        page_count = len(document)
        if page_count == 0:
            raise ScannedPdfParseError("이미지형 PDF에 페이지가 없습니다.")
        if page_count > MAX_SCANNED_PDF_PAGES:
            raise ScannedPdfInputLimitError("이미지형 PDF 페이지 수 제한을 초과했습니다.")

        total_pixels = 0

        def account_pixels(pixels: int) -> None:
            nonlocal total_pixels
            if pixels > MAX_RENDERED_PAGE_PIXELS:
                raise ScannedPdfInputLimitError(
                    "PDF 한 페이지의 렌더링 해상도 제한을 초과했습니다."
                )
            total_pixels += pixels
            if total_pixels > MAX_RENDERED_TOTAL_PIXELS:
                raise ScannedPdfInputLimitError("PDF 전체 렌더링 해상도 제한을 초과했습니다.")

        page_texts: list[str] = []
        for page_index in range(page_count):
            page = document[page_index]
            try:
                image = _rendered_page(page, account_pixels=account_pixels)
            finally:
                page.close()
            try:
                ocr_text = ocr_engine(image)
            finally:
                image.close()
            page_texts.append(ocr_text)
            if _contains_detail_section(ocr_text):
                break
    finally:
        document.close()

    source_hash = hashlib.sha256(source).hexdigest()
    if not any(text.strip() for text in page_texts):
        return StructuredImportPreview(
            source_hash=source_hash,
            source_format="scanned_pdf",
            rows=(),
            issues=(NormalizationIssue("OCR_TEXT_NOT_AVAILABLE", "ocr_text", 0),),
            ignored_headers=(),
        )

    text_preview = parse_academic_record_page_texts(tuple(page_texts), source_hash=source_hash)
    return StructuredImportPreview(
        source_hash=source_hash,
        source_format="scanned_pdf",
        rows=text_preview.rows,
        issues=tuple(
            list(text_preview.issues) + [NormalizationIssue("OCR_REVIEW_REQUIRED", "ocr_text", 0)]
        ),
        ignored_headers=text_preview.ignored_headers,
    )
