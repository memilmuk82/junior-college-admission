from __future__ import annotations

import os
import re
from pathlib import Path

from app import create_app
from app.services.anonymous_calculations import (
    AnonymousCalculationStore,
    to_academic_record_inputs,
)
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
