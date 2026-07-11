from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from dataclasses import replace
from io import BytesIO
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError

from app.services.structured_imports import (
    NormalizationIssue,
    StructuredImportPreview,
    StructuredInputLimitError,
)
from app.services.text_pdf_imports import parse_academic_record_page_texts

ImageInputFormat = Literal["image_png", "image_jpeg", "clipboard_image"]
OcrEngine = Callable[[Image.Image], str]
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_SIDE = 12_000
TESSERACT_TIMEOUT_SECONDS = 45


class UnsupportedImageError(ValueError):
    pass


class ImageInputLimitError(StructuredInputLimitError):
    pass


class LocalOcrError(RuntimeError):
    pass


def run_local_tesseract(image: Image.Image) -> str:
    encoded = BytesIO()
    image.save(encoded, format="PNG")
    try:
        completed = subprocess.run(
            [
                "tesseract",
                "stdin",
                "stdout",
                "-l",
                "kor+eng",
                "--psm",
                "6",
            ],
            input=encoded.getvalue(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=TESSERACT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as error:
        raise LocalOcrError("로컬 Tesseract 실행 파일을 찾을 수 없습니다.") from error
    except subprocess.TimeoutExpired as error:
        raise LocalOcrError("로컬 OCR 처리 시간이 제한을 초과했습니다.") from error

    if completed.returncode != 0:
        raise LocalOcrError("로컬 OCR 처리가 실패했습니다.")
    return completed.stdout.decode("utf-8", errors="replace")


def _normalized_image(source: bytes, source_format: ImageInputFormat) -> Image.Image:
    if len(source) > MAX_IMAGE_BYTES:
        raise ImageInputLimitError("이미지 입력 크기 제한을 초과했습니다.")
    try:
        with Image.open(BytesIO(source)) as opened:
            opened.load()
            detected_format = (opened.format or "").upper()
            if detected_format not in {"PNG", "JPEG"}:
                raise UnsupportedImageError("PNG 또는 JPEG 이미지만 지원합니다.")
            if source_format == "image_png" and detected_format != "PNG":
                raise UnsupportedImageError("선언된 PNG 형식과 실제 이미지가 다릅니다.")
            if source_format == "image_jpeg" and detected_format != "JPEG":
                raise UnsupportedImageError("선언된 JPEG 형식과 실제 이미지가 다릅니다.")
            width, height = opened.size
            if (
                width <= 0
                or height <= 0
                or width > MAX_IMAGE_SIDE
                or height > MAX_IMAGE_SIDE
                or width * height > MAX_IMAGE_PIXELS
            ):
                raise ImageInputLimitError("이미지 해상도 제한을 초과했습니다.")
            return ImageOps.exif_transpose(opened).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise UnsupportedImageError("이미지 구조를 읽을 수 없습니다.") from error


def parse_image_bytes(
    source: bytes,
    *,
    source_format: ImageInputFormat,
    ocr_engine: OcrEngine = run_local_tesseract,
) -> StructuredImportPreview:
    source_hash = hashlib.sha256(source).hexdigest()
    image = _normalized_image(source, source_format)
    try:
        ocr_text = ocr_engine(image)
    finally:
        image.close()

    if not ocr_text.strip():
        return StructuredImportPreview(
            source_hash=source_hash,
            source_format=source_format,
            rows=(),
            issues=(NormalizationIssue("OCR_TEXT_NOT_AVAILABLE", "ocr_text", 0),),
            ignored_headers=(),
        )

    text_preview = parse_academic_record_page_texts((ocr_text,), source_hash=source_hash)
    return StructuredImportPreview(
        source_hash=source_hash,
        source_format=source_format,
        rows=tuple(replace(row, source_page=None) for row in text_preview.rows),
        issues=tuple(
            [replace(issue, source_page=None) for issue in text_preview.issues]
            + [NormalizationIssue("OCR_REVIEW_REQUIRED", "ocr_text", 0)]
        ),
        ignored_headers=text_preview.ignored_headers,
    )
