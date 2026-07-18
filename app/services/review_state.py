from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from app.services.structured_imports import (
    NormalizationIssue,
    NormalizedCourseRow,
    ScoreValue,
    SourceFormat,
    StructuredImportPreview,
)
from app.services.temporary_uploads import TemporaryUploadStore

REVIEW_STATE_FILENAME = "review-state.json"
MAX_REVIEW_STATE_BYTES = 2 * 1024 * 1024
MAX_REVIEW_AGE_SECONDS = 30 * 60


class ReviewStateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReviewState:
    preview: StructuredImportPreview
    student_id: str
    record_source: str
    owner_actor_ref: str
    is_vocational_training_semester: bool = False


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    return value


def _row_payload(row: NormalizedCourseRow) -> dict[str, object]:
    return {
        "academic_year": row.academic_year,
        "grade": row.grade,
        "semester": row.semester,
        "subject_group": row.subject_group,
        "subject_name": row.subject_name,
        "credits": _json_value(row.credits),
        "raw_score": _json_value(row.raw_score),
        "course_mean": _json_value(row.course_mean),
        "standard_deviation": _json_value(row.standard_deviation),
        "achievement_level": row.achievement_level,
        "enrollment_count": row.enrollment_count,
        "rank_grade": _json_value(row.rank_grade),
        "source_sheet": row.source_sheet,
        "source_row_number": row.source_row_number,
        "source_page": row.source_page,
        "record_source": row.record_source,
        "is_vocational_training_semester": row.is_vocational_training_semester,
    }


def _issue_payload(issue: NormalizationIssue) -> dict[str, object]:
    return {
        "code": issue.code,
        "field": issue.field,
        "row_number": issue.row_number,
        "sheet_name": issue.sheet_name,
        "source_page": issue.source_page,
    }


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _optional_integer(value: object) -> int | None:
    return int(str(value)) if value is not None else None


def _row_from_payload(payload: dict[str, Any]) -> NormalizedCourseRow:
    raw_score_value = payload.get("raw_score")
    raw_score: ScoreValue = "P" if raw_score_value == "P" else _decimal(raw_score_value)
    return NormalizedCourseRow(
        academic_year=_optional_integer(payload.get("academic_year")),
        grade=_optional_integer(payload.get("grade")),
        semester=_optional_integer(payload.get("semester")),
        subject_group=_optional_string(payload.get("subject_group")),
        subject_name=_optional_string(payload.get("subject_name")),
        credits=_decimal(payload.get("credits")),
        raw_score=raw_score,
        course_mean=_decimal(payload.get("course_mean")),
        standard_deviation=_decimal(payload.get("standard_deviation")),
        achievement_level=_optional_string(payload.get("achievement_level")),
        enrollment_count=_optional_integer(payload.get("enrollment_count")),
        rank_grade=_decimal(payload.get("rank_grade")),
        source_sheet=_optional_string(payload.get("source_sheet")),
        source_row_number=_optional_integer(payload.get("source_row_number")),
        source_page=_optional_integer(payload.get("source_page")),
        record_source=_optional_string(payload.get("record_source")),
        is_vocational_training_semester=(
            bool(payload["is_vocational_training_semester"])
            if payload.get("is_vocational_training_semester") is not None
            else None
        ),
    )


class ReviewStateStore:
    def __init__(self, upload_store: TemporaryUploadStore) -> None:
        self.upload_store = upload_store

    def _path(self, review_session_id: str) -> Path:
        return self.upload_store.session_path(review_session_id) / "derived" / REVIEW_STATE_FILENAME

    def save(
        self,
        review_session_id: str,
        preview: StructuredImportPreview,
        *,
        student_id: str,
        record_source: str,
        owner_actor_ref: str,
        is_vocational_training_semester: bool = False,
    ) -> None:
        session_path = self.upload_store.session_path(review_session_id)
        if not session_path.is_dir():
            raise FileNotFoundError("검수 세션이 존재하지 않습니다.")
        if not owner_actor_ref or owner_actor_ref != owner_actor_ref.strip():
            raise ReviewStateError("검수 세션 소유자 식별자가 유효하지 않습니다.")
        payload = {
            "source_hash": preview.source_hash,
            "source_format": preview.source_format,
            "rows": [_row_payload(row) for row in preview.rows],
            "issues": [_issue_payload(issue) for issue in preview.issues],
            "ignored_headers": list(preview.ignored_headers),
            "student_id": student_id,
            "record_source": record_source,
            "owner_actor_ref": owner_actor_ref,
            "is_vocational_training_semester": is_vocational_training_semester,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        if len(encoded) > MAX_REVIEW_STATE_BYTES:
            raise ReviewStateError("검수 상태 크기 제한을 초과했습니다.")

        state_path = self._path(review_session_id)
        state_path.parent.mkdir(mode=0o700, exist_ok=True)
        temporary_path = state_path.with_suffix(".tmp")
        try:
            with temporary_path.open("wb") as state_file:
                state_file.write(encoded)
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, state_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def load(self, review_session_id: str) -> ReviewState:
        state_path = self._path(review_session_id)
        if not state_path.is_file():
            raise FileNotFoundError("검수 상태가 존재하지 않습니다.")
        if time.time() - state_path.stat().st_mtime > MAX_REVIEW_AGE_SECONDS:
            self.upload_store.purge_session(review_session_id)
            raise FileNotFoundError("검수 상태가 만료되었습니다.")
        if state_path.stat().st_size > MAX_REVIEW_STATE_BYTES:
            raise ReviewStateError("검수 상태 크기 제한을 초과했습니다.")
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            rows = tuple(_row_from_payload(row) for row in payload["rows"])
            issues = tuple(
                NormalizationIssue(
                    code=str(issue["code"]),
                    field=str(issue["field"]),
                    row_number=int(issue["row_number"]),
                    sheet_name=_optional_string(issue.get("sheet_name")),
                    source_page=_optional_integer(issue.get("source_page")),
                )
                for issue in payload["issues"]
            )
            source_format = str(payload["source_format"])
            if source_format not in {
                "csv",
                "pasted_table",
                "xlsx",
                "text_pdf",
                "image_png",
                "image_jpeg",
                "clipboard_image",
                "scanned_pdf",
            }:
                raise ValueError("지원하지 않는 입력 형식입니다.")
            preview = StructuredImportPreview(
                source_hash=str(payload["source_hash"]),
                source_format=cast(SourceFormat, source_format),
                rows=rows,
                issues=issues,
                ignored_headers=tuple(str(item) for item in payload["ignored_headers"]),
            )
            owner_actor_ref = str(payload["owner_actor_ref"])
            if not owner_actor_ref or owner_actor_ref != owner_actor_ref.strip():
                raise ValueError("검수 세션 소유자가 유효하지 않습니다.")
            return ReviewState(
                preview=preview,
                student_id=str(payload["student_id"]),
                record_source=str(payload["record_source"]),
                owner_actor_ref=owner_actor_ref,
                is_vocational_training_semester=bool(
                    payload.get("is_vocational_training_semester", False)
                ),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ReviewStateError("검수 상태를 읽을 수 없습니다.") from error
