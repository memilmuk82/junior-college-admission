from __future__ import annotations

import os
import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from flask import render_template, request, session
from werkzeug.datastructures import MultiDict

from app import create_app
from app.routes import (
    ANONYMOUS_ID_SESSION_KEY,
    ANONYMOUS_OWNER_SESSION_KEY,
    _filter_public_consultation_result,
    _parse_public_consultation,
    _public_target_values,
)
from app.services.admission_result_imports import PublishedImportedAdmissionResult
from app.services.anonymous_calculations import (
    AnonymousCalculationStore,
    to_academic_record_inputs,
)
from app.services.consultations import (
    BatchConsultationItem,
    BatchConsultationResult,
    ConsultationItemStatus,
    ConsultationProgram,
)
from app.services.eligibility import EligibilityStatus
from app.services.public_student_profiles import GENERAL_GRADUATE, VOCATIONAL_CURRENT
from app.services.review_state import ReviewStateStore
from app.services.structured_imports import NormalizedCourseRow
from app.services.temporary_uploads import TemporaryUploadStore


def _csrf(body: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', body)
    assert match is not None
    return match.group(1)


def _manual_form(csrf_token: str, *, grade: str = "2") -> dict[str, str]:
    return {
        "csrf_token": csrf_token,
        "input_mode": "manual",
        "record_source": "HOME_SCHOOL_RECORD",
        "rows-0-academic_year": "2025",
        "rows-0-grade": "1",
        "rows-0-semester": "1",
        "rows-0-subject_group": "국어",
        "rows-0-subject_name": "합성 국어",
        "rows-0-credits": "4",
        "rows-0-raw_score": "0",
        "rows-0-course_mean": "",
        "rows-0-standard_deviation": "",
        "rows-0-achievement_level": "",
        "rows-0-enrollment_count": "",
        "rows-0-rank_grade": grade,
    }


def test_public_target_values_default_to_the_2026_reference_year() -> None:
    values = _public_target_values()

    assert values["academic_year"] == "2027"
    assert values["admission_result_year"] == "2026"
    assert values["student_profile"] == VOCATIONAL_CURRENT


def test_public_targets_render_published_years_as_a_2026_default_select(
    tmp_path: Path,
) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )
    with app.test_request_context():
        page = render_template(
            "public_calculation_targets.html",
            calculation_id="synthetic-calculation",
            csrf_token="synthetic-csrf",
            values=_public_target_values(),
            programs=(),
            published_result_years=(2026, 2025),
            selected_program_ids=set(),
            errors=(),
            current_user=None,
            vocational_current_profile=VOCATIONAL_CURRENT,
            general_graduate_profile=GENERAL_GRADUATE,
        )

    assert '<select name="admission_result_year">' in page
    assert 'value="2026" selected' in page
    assert "2026학년도" in page
    assert "2025학년도" in page
    assert 'name="admission_result_year" type="number"' not in page


def test_public_result_excludes_only_confirmed_ineligible_tracks() -> None:
    items = tuple(
        SimpleNamespace(
            result=(
                None
                if status is None
                else SimpleNamespace(eligibility=SimpleNamespace(status=status))
            )
        )
        for status in (
            EligibilityStatus.ELIGIBLE,
            EligibilityStatus.CONDITIONALLY_ELIGIBLE,
            EligibilityStatus.NEEDS_REVIEW,
            EligibilityStatus.INSUFFICIENT_DATA,
            EligibilityStatus.INELIGIBLE,
            None,
        )
    )
    result = BatchConsultationResult(
        academic_year=2027,
        selected_programs=(),
        items=cast(tuple[BatchConsultationItem, ...], items),
    )

    public_result = _filter_public_consultation_result(result)

    assert public_result.items == items[:4] + items[5:]


def test_public_result_and_print_render_an_empty_relevant_track_state(tmp_path: Path) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )
    result = BatchConsultationResult(academic_year=2027, selected_programs=(), items=())
    with app.test_request_context():
        page = render_template(
            "public_calculation_result.html",
            calculation_id="synthetic-calculation",
            csrf_token="synthetic-csrf",
            result=result,
            values=MultiDict(),
        )
        printed = render_template(
            "public_calculation_print.html",
            calculation_id="synthetic-calculation",
            audience="student",
            result=result,
        )

    assert "현재 학생 정보에 해당하는 전형이 없습니다" in page
    assert "공식 자격 판정에서 지원 불가가 확정된 전형은 제외했습니다" in printed


def test_public_preparing_result_renders_each_2026_reference_scale(tmp_path: Path) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )
    program = ConsultationProgram(
        "synthetic-program",
        2027,
        "합성공개대학교",
        "경기 지역",
        "합성학과",
        "SYNTHETIC-PROGRAM",
        "DAY",
    )

    def reference(score_basis: str, average: str) -> PublishedImportedAdmissionResult:
        return PublishedImportedAdmissionResult(
            dataset_id="synthetic-dataset",
            publication_version="2026-PUBLIC-REFERENCE-V1",
            result_academic_year=2026,
            target_academic_year=2027,
            institution_code="SYNTHETIC-INSTITUTION",
            campus_code="SYNTHETIC-CAMPUS",
            program_code="SYNTHETIC-PROGRAM",
            admission_round_code="SUSI1",
            admission_track_code="GENERAL",
            day_night="DAY",
            capacity=20,
            applicant_count=None,
            admitted_count=None,
            competition_rate=Decimal("4.57"),
            best_score=None,
            average_score=Decimal(average),
            cutoff_score=Decimal("4.70"),
            score_basis=score_basis,
            score_direction="LOWER_IS_BETTER",
            historical_score_rule_id=None,
            historical_score_rule_version=None,
            historical_score_rule_year=None,
            source_reference="synthetic-public-source",
        )

    item = BatchConsultationItem(
        program=program,
        target=None,
        status=ConsultationItemStatus.PREPARING,
        result=None,
        message="2027 공식 계산 기준 준비 중",
        reference_results=(
            reference("RANK_GRADE", "4.23"),
            reference("CSAT_GRADE", "3.10"),
        ),
    )
    result = BatchConsultationResult(2027, (program,), (item,))

    with app.test_request_context():
        page = render_template(
            "public_calculation_result.html",
            calculation_id="synthetic-calculation",
            csrf_token="synthetic-csrf",
            result=result,
            values=MultiDict(),
        )

    assert "2026학년도 공개 입시결과 2건 보기" in page
    assert "학생부 석차등급" in page
    assert "수능 등급(참고용)" in page
    assert "직접 비교 불가" in page
    assert "평균 4.23" in page


def test_public_result_parsing_uses_session_profile_instead_of_tampered_hidden_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )
    upload_store = TemporaryUploadStore(tmp_path)
    calculation_id = upload_store.create_session()
    owner_token = "synthetic-public-profile-owner"
    AnonymousCalculationStore(upload_store).save(
        calculation_id,
        owner_token=owner_token,
        record_source="HOME_SCHOOL_RECORD",
        is_vocational_training_semester=False,
        student_profile=VOCATIONAL_CURRENT,
        rows=(
            NormalizedCourseRow(
                academic_year=2025,
                grade=1,
                semester=1,
                subject_group="국어",
                subject_name="합성 국어",
                credits=Decimal("4"),
                raw_score=None,
                course_mean=None,
                standard_deviation=None,
                achievement_level=None,
                enrollment_count=None,
                rank_grade=Decimal("2"),
                record_source="HOME_SCHOOL_RECORD",
                is_vocational_training_semester=False,
            ),
        ),
    )
    captured = {}

    def fake_batch(_database_session, consultation_request, **_kwargs):  # type: ignore[no-untyped-def]
        captured["request"] = consultation_request
        return BatchConsultationResult(
            academic_year=2027,
            selected_programs=(),
            items=(),
        )

    monkeypatch.setattr("app.routes.run_batch_consultation", fake_batch)
    with app.test_request_context(
        f"/calculate/{calculation_id}/results",
        method="POST",
        data={
            "program_ids": "synthetic-program",
            "student_profile": GENERAL_GRADUATE,
            "home_school_type": "VOCATIONAL",
            "final_school_type": "VOCATIONAL",
            "graduation_status": "GRADUATED",
            "vocational_training_status": "NONE",
            "ged": "TRUE",
        },
    ):
        session[ANONYMOUS_ID_SESSION_KEY] = calculation_id
        session[ANONYMOUS_OWNER_SESSION_KEY] = owner_token
        parsed, result = _parse_public_consultation(calculation_id, request.form)

    assert not parsed.errors
    assert result is not None
    facts = captured["request"].facts
    assert facts.home_school_type == "GENERAL"
    assert facts.final_school_type == "GENERAL"
    assert facts.graduation_status == "EXPECTED"
    assert facts.vocational_training_status == "PARTICIPATING"
    assert facts.ged is False


def test_anonymous_manual_entry_reaches_review_and_keeps_zero_distinct(tmp_path: Path) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )
    client = app.test_client()
    start = client.get("/calculate?example=1")
    assert start.status_code == 200
    assert "합성 예시 성적을 불러왔습니다" in start.get_data(as_text=True)

    submitted = client.post(
        "/calculate/input",
        data=_manual_form(_csrf(start.get_data(as_text=True))),
        follow_redirects=True,
    )
    body = submitted.get_data(as_text=True)
    assert submitted.status_code == 200
    assert "학생 성적 입력 검수" in body
    assert "합성 국어" in body
    assert 'value="0"' in body
    assert "계정 DB에 저장되지 않습니다" in body


def test_demo_example_uses_the_requested_five_term_score_sheet(tmp_path: Path) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )
    body = app.test_client().get("/calculate?example=1").get_data(as_text=True)

    for subject in (
        "국어",
        "통합사회",
        "통합과학",
        "문학",
        "수학Ⅰ",
        "독서",
        "수학Ⅱ",
        "빅데이터 프로그래밍",
        "웹 프로그래밍 실무",
        "응용 프로그래밍 개발",
    ):
        assert f'value="{subject}"' in body
    assert 'value="91.35"' in body
    assert 'value="63.50"' in body
    assert 'value="27.50"' in body
    assert 'value="93.50"' in body
    assert 'value="56.90"' in body
    assert 'value="23.40"' in body
    assert 'value="93.00"' in body
    assert 'value="76.10"' in body
    assert 'value="21.80"' in body


def test_anonymous_review_session_is_hidden_from_another_browser(tmp_path: Path) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )
    owner = app.test_client()
    start = owner.get("/calculate")
    submitted = owner.post(
        "/calculate/input",
        data=_manual_form(_csrf(start.get_data(as_text=True))),
    )

    assert submitted.status_code == 302
    review_url = submitted.headers["Location"]
    assert owner.get(review_url).status_code == 200
    assert app.test_client().get(review_url).status_code == 404


def test_public_manual_rows_use_server_derived_vocational_profile_sources(tmp_path: Path) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )
    client = app.test_client()
    start = client.get("/calculate")
    form = _manual_form(_csrf(start.get_data(as_text=True)))
    form.update(
        {
            "student_profile": VOCATIONAL_CURRENT,
            "rows-0-record_source": "VOCATIONAL_TRAINING_RECORD",
            "rows-0-is_vocational_training_semester": "TRUE",
            "rows-40-academic_year": "2027",
            "rows-40-grade": "3",
            "rows-40-semester": "1",
            "rows-40-subject_group": "위탁",
            "rows-40-subject_name": "합성 위탁 과목",
            "rows-40-credits": "3",
            "rows-40-rank_grade": "2",
            "rows-40-record_source": "HOME_SCHOOL_RECORD",
            "rows-40-is_vocational_training_semester": "FALSE",
        }
    )

    response = client.post("/calculate/input", data=form)

    assert response.status_code == 302
    review_id = response.headers["Location"].rsplit("/", 1)[-1]
    state = ReviewStateStore(TemporaryUploadStore(tmp_path)).load(review_id)
    assert state.student_profile == VOCATIONAL_CURRENT
    assert [
        (row.record_source, row.is_vocational_training_semester) for row in state.preview.rows
    ] == [
        ("HOME_SCHOOL_RECORD", False),
        ("VOCATIONAL_TRAINING_RECORD", True),
    ]
    review_body = client.get(response.headers["Location"]).get_data(as_text=True)
    assert 'id="rows-0-record_source" name="rows-0-record_source" type="hidden"' in review_body
    assert 'id="rows-1-record_source" name="rows-1-record_source" type="hidden"' in review_body
    assert '<select id="rows-0-record_source"' not in review_body
    assert "원적교 학교생활기록부 · 일반 학기" in review_body
    assert "직업위탁 성적 · 위탁 학기" in review_body


def test_general_graduate_profile_forces_third_grade_to_home_school_source(
    tmp_path: Path,
) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )
    client = app.test_client()
    start = client.get("/calculate")
    form = _manual_form(_csrf(start.get_data(as_text=True)))
    form.update(
        {
            "student_profile": GENERAL_GRADUATE,
            "rows-0-academic_year": "2027",
            "rows-0-grade": "3",
            "rows-0-semester": "2",
            "rows-0-record_source": "VOCATIONAL_TRAINING_RECORD",
            "rows-0-is_vocational_training_semester": "TRUE",
        }
    )

    response = client.post("/calculate/input", data=form)

    assert response.status_code == 302
    review_id = response.headers["Location"].rsplit("/", 1)[-1]
    state = ReviewStateStore(TemporaryUploadStore(tmp_path)).load(review_id)
    assert state.student_profile == GENERAL_GRADUATE
    assert state.preview.rows[0].record_source == "HOME_SCHOOL_RECORD"
    assert state.preview.rows[0].is_vocational_training_semester is False


def test_anonymous_review_ignores_tampered_source_hidden_values(tmp_path: Path) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )
    client = app.test_client()
    start = client.get("/calculate")
    form = _manual_form(_csrf(start.get_data(as_text=True)))
    form.update(
        {
            "student_profile": VOCATIONAL_CURRENT,
            "rows-0-academic_year": "2027",
            "rows-0-grade": "3",
            "rows-0-semester": "1",
        }
    )
    submitted = client.post("/calculate/input", data=form)
    review_url = submitted.headers["Location"]
    review = client.get(review_url)

    confirmed = client.post(
        review_url,
        data={
            "csrf_token": _csrf(review.get_data(as_text=True)),
            "confirmed_row_indices": "0",
            "rows-0-academic_year": "2027",
            "rows-0-grade": "3",
            "rows-0-semester": "1",
            "rows-0-subject_group": "국어",
            "rows-0-subject_name": "합성 국어",
            "rows-0-credits": "4",
            "rows-0-raw_score": "",
            "rows-0-course_mean": "",
            "rows-0-standard_deviation": "",
            "rows-0-achievement_level": "",
            "rows-0-enrollment_count": "",
            "rows-0-rank_grade": "2",
            "rows-0-record_source": "NOT_A_RECORD_SOURCE",
            "rows-0-is_vocational_training_semester": "NOT_A_BOOLEAN",
        },
    )

    assert confirmed.status_code == 302
    calculation_id = review_url.rsplit("/", 1)[-1]
    with client.session_transaction() as browser_session:
        owner = str(browser_session["anonymous_calculation_owner"])
    state = AnonymousCalculationStore(TemporaryUploadStore(tmp_path)).load(
        calculation_id, owner_token=owner
    )
    assert state.student_profile == VOCATIONAL_CURRENT
    records = to_academic_record_inputs(state)
    assert records[0].record_source == "VOCATIONAL_TRAINING_RECORD"
    assert records[0].is_vocational_training_semester is True


def test_public_input_uses_excel_term_grids_without_fake_program_picker(tmp_path: Path) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )

    response = app.test_client().get("/calculate")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    for term in (
        "1학년 1학기",
        "1학년 2학기",
        "2학년 1학기",
        "2학년 2학기",
        "3학년 1학기",
        "3학년 2학기",
    ):
        assert term in body
    assert body.count("data-score-row") == 60
    assert 'name="rows-59-subject_name"' in body
    assert "학기당 10과목 · 총 60칸" in body
    assert "선택 입력 · 비워도 계산 가능" in body
    assert 'id="record-source"' not in body
    assert 'type="checkbox" name="is_vocational_training_semester"' not in body
    assert '<select id="rows-0-record_source"' not in body
    assert 'name="student_profile" value="VOCATIONAL_CURRENT"' in body
    assert 'name="student_profile" value="GENERAL_GRADUATE"' in body
    assert "data-add-score-row" not in body
    assert "data-delete-score-row" not in body
    assert "단위수" in body
    assert "원점수" in body
    assert "과목평균" in body
    assert "표준편차" in body
    assert "data-preview-program" not in body
    assert "성적 확인 다음 단계에서 대학·학과를 선택합니다" in body


def test_manual_input_accepts_the_sixtieth_optional_slot(tmp_path: Path) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )
    client = app.test_client()
    start = client.get("/calculate")

    response = client.post(
        "/calculate/input",
        data={
            "csrf_token": _csrf(start.get_data(as_text=True)),
            "input_mode": "manual",
            "record_source": "HOME_SCHOOL_RECORD",
            "student_profile": GENERAL_GRADUATE,
            "rows-59-academic_year": "2027",
            "rows-59-grade": "3",
            "rows-59-semester": "2",
            "rows-59-subject_group": "합성 교과",
            "rows-59-subject_name": "선택 입력 60번째 합성 과목",
            "rows-59-credits": "3",
            "rows-59-rank_grade": "2",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "학생 성적 입력 검수" in body
    assert "선택 입력 60번째 합성 과목" in body


def test_manual_input_error_keeps_the_submitted_term_and_course_values(tmp_path: Path) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )
    client = app.test_client()
    start = client.get("/calculate")

    response = client.post(
        "/calculate/input",
        data={
            "csrf_token": _csrf(start.get_data(as_text=True)),
            "input_mode": "manual",
            "student_profile": "NOT_A_STUDENT_PROFILE",
            "rows-0-academic_year": "2025",
            "rows-0-grade": "1",
            "rows-0-semester": "1",
            "rows-0-subject_group": "국어",
            "rows-0-subject_name": "다시 입력하지 않을 합성 과목",
            "rows-0-credits": "잘못된 숫자",
            "rows-0-rank_grade": "2",
        },
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 400
    assert "다시 입력하지 않을 합성 과목" in body
    assert 'value="잘못된 숫자"' in body
    assert "학생 구분을 확인하세요." in body
    assert 'id="rows-0-record_source"' in body
    assert 'value="HOME_SCHOOL_RECORD"' in body


def test_anonymous_review_confirmation_deletes_original_and_builds_memory_records(
    tmp_path: Path,
) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )
    client = app.test_client()
    start = client.get("/calculate")
    submitted = client.post(
        "/calculate/input",
        data={
            "csrf_token": _csrf(start.get_data(as_text=True)),
            "input_mode": "paste",
            "record_source": "HOME_SCHOOL_RECORD",
            "pasted_table": (
                "학년도\t학년\t학기\t교과\t과목\t이수단위\t석차등급\n"
                "2025\t1\t1\t국어\t합성 국어\t4\t2"
            ),
        },
    )
    review = client.get(submitted.headers["Location"])
    calculation_id = submitted.headers["Location"].rsplit("/", 1)[-1]
    form = _manual_form(_csrf(review.get_data(as_text=True)))
    form["confirmed_row_indices"] = "0"
    confirmed = client.post(submitted.headers["Location"], data=form)

    assert confirmed.status_code == 302
    assert confirmed.headers["Location"].endswith(f"/calculate/{calculation_id}/targets")
    upload_store = TemporaryUploadStore(tmp_path)
    session_path = upload_store.session_path(calculation_id)
    assert not (session_path / "original").exists()
    with client.session_transaction() as browser_session:
        owner = str(browser_session["anonymous_calculation_owner"])
    state = AnonymousCalculationStore(upload_store).load(calculation_id, owner_token=owner)
    records = to_academic_record_inputs(state)
    assert records[0].courses[0].subject_name == "합성 국어"
    assert str(records[0].courses[0].rank_grade) == "2"
    assert records[0].courses[0].user_verified is True


def test_public_start_sweeps_expired_anonymous_session(tmp_path: Path) -> None:
    upload_store = TemporaryUploadStore(tmp_path)
    expired_id = upload_store.create_session()
    artifact = upload_store.write_artifact(
        expired_id, b"expired-synthetic", kind="original", suffix=".csv"
    )
    os.utime(artifact.path, (1, 1))
    os.utime(upload_store.session_path(expired_id), (1, 1))
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )

    response = app.test_client().get("/calculate")

    assert response.status_code == 200
    assert not upload_store.session_path(expired_id).exists()


def test_scheduled_cleanup_cli_purges_without_http_traffic(tmp_path: Path) -> None:
    upload_store = TemporaryUploadStore(tmp_path)
    expired_id = upload_store.create_session()
    artifact = upload_store.write_artifact(
        expired_id, b"expired-synthetic", kind="original", suffix=".csv"
    )
    os.utime(artifact.path, (1, 1))
    os.utime(upload_store.session_path(expired_id), (1, 1))
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "TEMP_UPLOAD_ROOT": str(tmp_path),
        }
    )

    result = app.test_cli_runner().invoke(
        args=["purge-expired-anonymous-calculations", "--max-age-seconds", "1800"]
    )

    assert result.exit_code == 0
    assert result.output == "expired anonymous sessions purged: 1\n"
    assert not upload_store.session_path(expired_id).exists()
