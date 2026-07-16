from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app import create_app
from app.models import ImportBatch, StudentCourseRecord
from app.services.review_state import ReviewStateStore
from app.services.structured_imports import (
    NormalizationIssue,
    StructuredImportPreview,
    parse_structured_text,
)
from app.services.temporary_uploads import TemporaryUploadStore


def _seed_review(tmp_path: Path) -> tuple[str, StructuredImportPreview]:
    upload_store = TemporaryUploadStore(tmp_path)
    review_session_id = upload_store.create_session()
    upload_store.write_artifact(
        review_session_id,
        b"synthetic-original",
        kind="original",
        suffix=".pdf",
    )
    preview = parse_structured_text(
        "학년도,학년,학기,교과,과목,이수단위,원점수,평균,표준편차,성취도,수강자수,석차등급\n"
        "2026,3,1,보통교과,합성 과목 A,3,91,72.4,12.1,A,120,2\n"
        "2026,3,1,전문교과,합성 과목 B,4,77,68.3,15.4,B,118,5\n"
        "2026,3,2,보통교과,합성 과목 C,2,85,74.1,11.6,A,115,3",
        source_format="csv",
    )
    preview = StructuredImportPreview(
        source_hash=preview.source_hash,
        source_format="scanned_pdf",
        rows=preview.rows,
        issues=(NormalizationIssue("OCR_REVIEW_REQUIRED", "ocr_text", 0),),
        ignored_headers=(),
    )
    ReviewStateStore(upload_store).save(
        review_session_id,
        preview,
        student_id="synthetic-review-student",
        record_source="HOME_SCHOOL_RECORD",
        owner_actor_ref="synthetic-admin",
    )
    return review_session_id, preview


def _csrf_token(response_text: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', response_text)
    assert match is not None
    return match.group(1)


def _authenticate_legacy(client) -> None:  # type: ignore[no-untyped-def]
    with client.session_transaction() as browser_session:
        browser_session["admin_actor_ref"] = "synthetic-admin"


def _row_form(preview: StructuredImportPreview) -> dict[str, str | list[str]]:
    form: dict[str, str | list[str]] = {
        "confirmed_row_indices": ["0", "2"],
    }
    for index, row in enumerate(preview.rows):
        values = {
            "academic_year": row.academic_year,
            "grade": row.grade,
            "semester": row.semester,
            "subject_group": row.subject_group,
            "subject_name": row.subject_name,
            "credits": row.credits,
            "raw_score": row.raw_score,
            "course_mean": row.course_mean,
            "standard_deviation": row.standard_deviation,
            "achievement_level": row.achievement_level,
            "enrollment_count": row.enrollment_count,
            "rank_grade": row.rank_grade,
        }
        for field, value in values.items():
            form[f"rows-{index}-{field}"] = "" if value is None else str(value)
    form["rows-0-subject_name"] = "교사 수정 과목"
    return form


def test_review_screen_and_no_javascript_confirmation_flow(
    postgres_engine: Engine, tmp_path: Path
) -> None:
    review_session_id, preview = _seed_review(tmp_path)
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )
    client = app.test_client()
    _authenticate_legacy(client)

    get_response = client.get(f"/input/review/{review_session_id}")
    response_text = get_response.get_data(as_text=True)

    assert get_response.status_code == 200
    assert "학생 성적 입력 검수" in response_text
    assert "합성 과목 A" in response_text
    assert "OCR 결과는 교사 확인이 필요합니다" in response_text
    assert "synthetic-original" not in response_text
    assert get_response.headers["Cache-Control"] == "no-store, max-age=0"
    assert get_response.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in get_response.headers["Content-Security-Policy"]

    form = _row_form(preview)
    form["csrf_token"] = _csrf_token(response_text)
    post_response = client.post(f"/input/review/{review_session_id}", data=form)

    assert post_response.status_code == 200
    assert "2개 행을 저장했습니다" in post_response.get_data(as_text=True)
    assert not TemporaryUploadStore(tmp_path).session_path(review_session_id).exists()

    with Session(postgres_engine) as session:
        batch = session.scalar(
            select(ImportBatch).where(ImportBatch.source_hash == preview.source_hash)
        )
        assert batch is not None
        courses = session.scalars(
            select(StudentCourseRecord)
            .where(StudentCourseRecord.import_batch_id == batch.id)
            .order_by(StudentCourseRecord.subject_name)
        ).all()
        assert [course.subject_name for course in courses] == [
            "교사 수정 과목",
            "합성 과목 C",
        ]


def test_review_rejects_empty_selection_without_deleting_session(
    postgres_engine: Engine, tmp_path: Path
) -> None:
    review_session_id, preview = _seed_review(tmp_path)
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )
    client = app.test_client()
    _authenticate_legacy(client)
    get_response = client.get(f"/input/review/{review_session_id}")
    form = _row_form(preview)
    form.pop("confirmed_row_indices")
    form["csrf_token"] = _csrf_token(get_response.get_data(as_text=True))

    response = client.post(f"/input/review/{review_session_id}", data=form)

    assert response.status_code == 400
    assert "저장할 행을 선택하세요" in response.get_data(as_text=True)
    assert TemporaryUploadStore(tmp_path).session_path(review_session_id).exists()


def test_discard_requires_post_and_purges_review_session(
    postgres_engine: Engine, tmp_path: Path
) -> None:
    review_session_id, _preview = _seed_review(tmp_path)
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )
    client = app.test_client()
    _authenticate_legacy(client)
    get_response = client.get(f"/input/review/{review_session_id}")
    csrf_token = _csrf_token(get_response.get_data(as_text=True))

    response = client.post(
        f"/input/review/{review_session_id}/discard",
        data={"csrf_token": csrf_token},
    )

    assert response.status_code == 302
    assert not TemporaryUploadStore(tmp_path).session_path(review_session_id).exists()


def test_review_rejects_missing_csrf_without_deleting_session(
    postgres_engine: Engine, tmp_path: Path
) -> None:
    review_session_id, preview = _seed_review(tmp_path)
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )
    client = app.test_client()
    _authenticate_legacy(client)

    response = client.post(f"/input/review/{review_session_id}", data=_row_form(preview))

    assert response.status_code == 400
    assert TemporaryUploadStore(tmp_path).session_path(review_session_id).exists()
