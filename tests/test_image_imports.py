from __future__ import annotations

from io import BytesIO
from unittest.mock import patch

import pytest
from PIL import Image

from app.services.image_imports import (
    ImageInputLimitError,
    UnsupportedImageError,
    parse_image_bytes,
)

SYNTHETIC_OCR_TEXT = "\n".join(
    [
        "교과학습발달상황",
        "학년도|학년|학기|과목|원점수",
        "2026|3|1|합성 이미지 과목|91",
        "세부능력 및 특기사항",
        "SYNTHETIC_PRIVATE_DETAIL_MUST_NOT_SURVIVE",
    ]
)


def _synthetic_image_bytes(image_format: str = "PNG") -> bytes:
    image = Image.new("RGB", (640, 480), "white")
    output = BytesIO()
    image.save(output, format=image_format)
    image.close()
    return output.getvalue()


def _synthetic_ocr(_image: Image.Image) -> str:
    return SYNTHETIC_OCR_TEXT


def test_png_and_clipboard_image_use_same_local_normalization_contract() -> None:
    source = _synthetic_image_bytes()

    png_preview = parse_image_bytes(source, source_format="image_png", ocr_engine=_synthetic_ocr)
    clipboard_preview = parse_image_bytes(
        source,
        source_format="clipboard_image",
        ocr_engine=_synthetic_ocr,
    )

    assert png_preview.rows == clipboard_preview.rows
    assert png_preview.rows[0].subject_name == "합성 이미지 과목"
    assert png_preview.source_format == "image_png"
    assert clipboard_preview.source_format == "clipboard_image"
    assert "SYNTHETIC_PRIVATE_DETAIL_MUST_NOT_SURVIVE" not in repr(png_preview)
    assert ("OCR_REVIEW_REQUIRED", "ocr_text") in [
        (issue.code, issue.field) for issue in png_preview.issues
    ]


def test_jpeg_image_is_accepted_after_content_signature_validation() -> None:
    preview = parse_image_bytes(
        _synthetic_image_bytes("JPEG"),
        source_format="image_jpeg",
        ocr_engine=_synthetic_ocr,
    )

    assert len(preview.rows) == 1
    assert preview.source_format == "image_jpeg"


def test_invalid_image_bytes_are_rejected_before_ocr() -> None:
    with pytest.raises(UnsupportedImageError):
        parse_image_bytes(
            b"not-an-image",
            source_format="image_png",
            ocr_engine=_synthetic_ocr,
        )


def test_image_pixel_limit_is_checked_before_ocr() -> None:
    with patch("app.services.image_imports.MAX_IMAGE_PIXELS", 100):
        with pytest.raises(ImageInputLimitError):
            parse_image_bytes(
                _synthetic_image_bytes(),
                source_format="image_png",
                ocr_engine=_synthetic_ocr,
            )
