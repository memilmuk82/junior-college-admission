from __future__ import annotations

import csv
from io import StringIO
from typing import Any, cast

from flask import Blueprint, Response, make_response, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import csrf_token, require_csrf, roles_required, session_user
from app.database import db
from app.services.institutional_results import (
    InstitutionalOutcomeView,
    InstitutionalResultError,
    create_outcome,
    delete_outcome,
    list_outcomes,
    list_track_options,
    summarize_outcomes,
)

bp = Blueprint("teacher", __name__, url_prefix="/teacher")


def _private(content: str, status: int = 200, mimetype: str = "text/html") -> Response:
    response = make_response(content, status)
    response.mimetype = mimetype
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _filters() -> dict[str, str]:
    return {
        "academic_year": request.args.get("academic_year", "2027").strip(),
        "institution_id": request.args.get("institution_id", "").strip(),
        "program_id": request.args.get("program_id", "").strip(),
        "admission_track_id": request.args.get("admission_track_id", "").strip(),
        "outcome_status": request.args.get("outcome_status", "").strip(),
    }


def _filtered_rows() -> tuple[InstitutionalOutcomeView, ...]:
    user = session_user()
    assert user is not None
    filters = _filters()
    try:
        academic_year = int(filters["academic_year"]) if filters["academic_year"] else None
    except ValueError as error:
        raise InstitutionalResultError("모집학년도 필터를 확인하세요.") from error
    return list_outcomes(
        cast(Session, db.session),
        user=user,
        academic_year=academic_year,
        institution_id=filters["institution_id"],
        program_id=filters["program_id"],
        admission_track_id=filters["admission_track_id"],
        outcome_status=filters["outcome_status"],
    )


def _render_outcomes(*, error: str | None = None, status: int = 200) -> Response:
    user = session_user()
    assert user is not None
    filters = _filters()
    try:
        rows = _filtered_rows()
    except InstitutionalResultError as filter_error:
        rows = ()
        error = error or str(filter_error)
        status = max(status, 400)
    options = list_track_options(cast(Session, db.session), academic_year=2027)
    return _private(
        render_template(
            "teacher_outcomes.html",
            current_user=user,
            csrf_token=csrf_token(),
            rows=rows,
            summary=summarize_outcomes(rows),
            track_options=options,
            filters=filters,
            error=error,
        ),
        status,
    )


@bp.route("/outcomes", methods=["GET", "POST"])
@roles_required("TEACHER", "ADMIN", allow_legacy=False)
def outcomes() -> Response | Any:
    if request.method == "GET":
        return _render_outcomes()
    require_csrf()
    user = session_user()
    assert user is not None
    try:
        create_outcome(cast(Session, db.session), user=user, values=request.form)
        db.session.commit()
    except InstitutionalResultError as error:
        db.session.rollback()
        return _render_outcomes(error=str(error), status=400)
    except IntegrityError:
        db.session.rollback()
        return _render_outcomes(
            error="같은 익명 학생·학년도·전형의 결과가 이미 있습니다.", status=409
        )
    return redirect(url_for("teacher.outcomes"))


@bp.post("/outcomes/<outcome_id>/delete")
@roles_required("TEACHER", "ADMIN", allow_legacy=False)
def delete_outcome_route(outcome_id: str) -> Response | Any:
    require_csrf()
    user = session_user()
    assert user is not None
    try:
        delete_outcome(cast(Session, db.session), user=user, outcome_id=outcome_id)
        db.session.commit()
    except InstitutionalResultError as error:
        db.session.rollback()
        return _render_outcomes(error=str(error), status=404)
    return redirect(url_for("teacher.outcomes"))


@bp.get("/outcomes.csv")
@roles_required("TEACHER", "ADMIN", allow_legacy=False)
def outcomes_csv() -> Response:
    try:
        rows = _filtered_rows()
    except InstitutionalResultError as error:
        return _private(str(error), 400, "text/plain")
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        (
            "모집학년도",
            "익명학생코드",
            "대학",
            "캠퍼스",
            "학과",
            "모집시기",
            "전형",
            "반영등급",
            "결과",
            "최초예비번호",
            "최종예비번호",
            "출처상태",
        )
    )
    for row in rows:
        writer.writerow(
            (
                row.outcome.academic_year,
                row.outcome.anonymous_student_code,
                row.track.institution_name,
                row.track.campus_name,
                row.track.program_name,
                row.track.round_name,
                row.track.track_name,
                row.outcome.reflected_grade or "",
                row.outcome.outcome_status,
                row.outcome.initial_waitlist_number or "",
                row.outcome.final_waitlist_number or "",
                row.outcome.source_status,
            )
        )
    response = _private("\ufeff" + buffer.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = (
        'attachment; filename="institutional-outcomes-2027.csv"'
    )
    return response


__all__ = ["bp"]
