from __future__ import annotations

import csv
from io import StringIO
from typing import Any, cast

from flask import Blueprint, Response, make_response, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import (
    csrf_token,
    is_demo_user,
    require_csrf,
    roles_required,
    session_user,
    teacher_required,
)
from app.database import db
from app.models import (
    ClassroomStudent,
    StudentAcademicRecord,
    StudentCourseRecord,
    TeacherClassroom,
)
from app.services.classroom_links import (
    ClassroomLinkError,
    add_classroom_course,
    add_classroom_student,
    classroom_student_records,
    classroom_student_reference,
    create_classroom,
    disconnect_student_account,
    list_classroom_students,
    list_teacher_classrooms,
    rotate_connection_code,
)
from app.services.institutional_results import (
    InstitutionalOutcomeView,
    InstitutionalResultError,
    create_outcome,
    delete_outcome,
    list_outcomes,
    list_track_options,
    summarize_outcomes,
)
from app.services.student_record_access import academic_record_courses

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


def _render_classrooms(
    *,
    error: str | None = None,
    status: int = 200,
    connection_code: str | None = None,
    issued_student_id: str | None = None,
) -> Response:
    user = session_user()
    assert user is not None
    demo_mode = is_demo_user(user)
    database_session = cast(Session, db.session)
    classrooms: tuple[TeacherClassroom, ...]
    students_by_classroom: dict[str, tuple[ClassroomStudent, ...]]
    selected_student: ClassroomStudent | None
    records: tuple[StudentAcademicRecord, ...]
    courses_by_record: dict[str, tuple[StudentCourseRecord, ...]]
    if demo_mode:
        classrooms = ()
        students_by_classroom = {}
        selected_student = None
        records = ()
        courses_by_record = {}
    else:
        classrooms = list_teacher_classrooms(database_session, user=user)
        students_by_classroom = {
            classroom.id: list_classroom_students(
                database_session, user=user, classroom_id=classroom.id
            )
            for classroom in classrooms
        }
        selected_student_id = request.args.get("student_id", "").strip() or issued_student_id
        selected_student = next(
            (
                student
                for students in students_by_classroom.values()
                for student in students
                if student.id == selected_student_id
            ),
            None,
        )
        records = (
            classroom_student_records(
                database_session, user=user, classroom_student_id=selected_student.id
            )
            if selected_student is not None
            else ()
        )
        courses_by_record = academic_record_courses(database_session, records=records)
    return _private(
        render_template(
            "teacher_classrooms.html",
            current_user=user,
            csrf_token=csrf_token(),
            classrooms=classrooms,
            students_by_classroom=students_by_classroom,
            selected_student=selected_student,
            selected_student_reference=(
                classroom_student_reference(selected_student.id)
                if selected_student is not None
                else None
            ),
            records=records,
            courses_by_record=courses_by_record,
            error=error,
            connection_code=connection_code,
            issued_student_id=issued_student_id,
            message=request.args.get("message"),
            demo_mode=demo_mode,
        ),
        status,
    )


@bp.get("/classrooms")
@teacher_required
def classrooms() -> Response:
    return _render_classrooms()


@bp.post("/classrooms")
@teacher_required
def create_classroom_route() -> Response | Any:
    require_csrf()
    user = session_user()
    assert user is not None
    try:
        classroom = create_classroom(cast(Session, db.session), user=user, values=request.form)
        db.session.commit()
    except ClassroomLinkError as error:
        db.session.rollback()
        return _render_classrooms(error=str(error), status=400)
    except IntegrityError:
        db.session.rollback()
        return _render_classrooms(error="같은 학년도·학과·학급이 이미 있습니다.", status=409)
    return redirect(url_for("teacher.classrooms", classroom_id=classroom.id, message="created"))


@bp.post("/classrooms/<classroom_id>/students")
@teacher_required
def add_classroom_student_route(classroom_id: str) -> Response:
    require_csrf()
    user = session_user()
    assert user is not None
    try:
        issued = add_classroom_student(
            cast(Session, db.session),
            user=user,
            classroom_id=classroom_id,
            anonymous_code=request.form.get("anonymous_code", ""),
        )
        db.session.commit()
    except ClassroomLinkError as error:
        db.session.rollback()
        return _render_classrooms(error=str(error), status=400)
    except IntegrityError:
        db.session.rollback()
        return _render_classrooms(error="같은 학급에 동일한 비식별 코드가 있습니다.", status=409)
    return _render_classrooms(
        connection_code=issued.connection_code,
        issued_student_id=issued.student.id,
        status=201,
    )


@bp.post("/students/<classroom_student_id>/link-code")
@teacher_required
def rotate_student_link_code(classroom_student_id: str) -> Response:
    require_csrf()
    user = session_user()
    assert user is not None
    try:
        issued = rotate_connection_code(
            cast(Session, db.session),
            user=user,
            classroom_student_id=classroom_student_id,
        )
        db.session.commit()
    except ClassroomLinkError as error:
        db.session.rollback()
        return _render_classrooms(error=str(error), status=400)
    return _render_classrooms(
        connection_code=issued.connection_code,
        issued_student_id=issued.student.id,
    )


@bp.post("/students/<classroom_student_id>/disconnect")
@teacher_required
def disconnect_student_route(classroom_student_id: str) -> Response | Any:
    require_csrf()
    user = session_user()
    assert user is not None
    try:
        disconnect_student_account(
            cast(Session, db.session),
            user=user,
            classroom_student_id=classroom_student_id,
        )
        db.session.commit()
    except ClassroomLinkError as error:
        db.session.rollback()
        return _render_classrooms(error=str(error), status=404)
    return redirect(url_for("teacher.classrooms", message="disconnected"))


@bp.post("/students/<classroom_student_id>/courses")
@teacher_required
def add_student_course(classroom_student_id: str) -> Response | Any:
    require_csrf()
    user = session_user()
    assert user is not None
    try:
        add_classroom_course(
            cast(Session, db.session),
            user=user,
            classroom_student_id=classroom_student_id,
            values=request.form,
        )
        db.session.commit()
    except ClassroomLinkError as error:
        db.session.rollback()
        return _render_classrooms(
            error=str(error), status=400, issued_student_id=classroom_student_id
        )
    return redirect(
        url_for("teacher.classrooms", student_id=classroom_student_id, message="course_added")
    )


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
    demo_mode = is_demo_user(user)
    filters = _filters()
    if demo_mode:
        rows: tuple[InstitutionalOutcomeView, ...] = ()
    else:
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
            demo_mode=demo_mode,
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
