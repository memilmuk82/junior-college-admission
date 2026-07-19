from __future__ import annotations

from typing import Any, cast

from flask import Blueprint, Response, make_response, redirect, render_template, request, url_for
from sqlalchemy.orm import Session

from app.auth import csrf_token, require_csrf, roles_required, session_user
from app.database import db
from app.services.consultations import list_consultation_programs
from app.services.student_record_access import (
    StudentRecordAccessError,
    academic_record_courses,
    delete_academic_record,
    delete_saved_consultation,
    get_saved_consultation,
    saved_consultation_input_rows,
    update_academic_record_courses,
    update_consultation_note,
    visible_academic_records,
    visible_saved_consultations,
)

bp = Blueprint("account", __name__, url_prefix="/account")


def _private(content: str, status: int = 200) -> Response:
    response = make_response(content, status)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; img-src 'self' data:; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    return response


def _render_records(*, error: str | None = None, status: int = 200) -> Response:
    user = session_user()
    assert user is not None
    try:
        records = visible_academic_records(cast(Session, db.session), user=user)
        consultations = visible_saved_consultations(cast(Session, db.session), user=user)
        courses_by_record = academic_record_courses(cast(Session, db.session), records=records)
    except StudentRecordAccessError as access_error:
        return _private(str(access_error), 403)
    return _private(
        render_template(
            "account_records.html",
            current_user=user,
            records=records,
            courses_by_record=courses_by_record,
            consultations=consultations,
            csrf_token=csrf_token(),
            error=error,
        ),
        status,
    )


@bp.get("/records")
@roles_required("STUDENT", "TEACHER", "ADMIN", allow_legacy=False)
def records() -> Response:
    return _render_records()


@bp.post("/records/<record_id>/delete")
@roles_required("STUDENT", "TEACHER", "ADMIN", allow_legacy=False)
def delete_record(record_id: str) -> Any:
    require_csrf()
    user = session_user()
    assert user is not None
    try:
        delete_academic_record(cast(Session, db.session), user=user, record_id=record_id)
        db.session.commit()
    except StudentRecordAccessError as error:
        db.session.rollback()
        return _render_records(error=str(error), status=404)
    return redirect(url_for("account.records"))


@bp.post("/records/<record_id>/edit")
@roles_required("STUDENT", "TEACHER", "ADMIN", allow_legacy=False)
def edit_record(record_id: str) -> Any:
    require_csrf()
    user = session_user()
    assert user is not None
    try:
        update_academic_record_courses(
            cast(Session, db.session),
            user=user,
            record_id=record_id,
            values=request.form,
        )
        db.session.commit()
    except StudentRecordAccessError as error:
        db.session.rollback()
        return _render_records(error=str(error), status=400)
    return redirect(url_for("account.records"))


@bp.post("/consultations/<consultation_id>/note")
@roles_required("TEACHER", allow_legacy=False)
def edit_consultation_note(consultation_id: str) -> Any:
    require_csrf()
    user = session_user()
    assert user is not None
    try:
        update_consultation_note(
            cast(Session, db.session),
            user=user,
            consultation_id=consultation_id,
            counselor_note=request.form.get("counselor_note", ""),
        )
        db.session.commit()
    except StudentRecordAccessError as error:
        db.session.rollback()
        return _render_records(error=str(error), status=404)
    return redirect(url_for("account.records"))


@bp.post("/consultations/<consultation_id>/delete")
@roles_required("STUDENT", "TEACHER", "ADMIN", allow_legacy=False)
def delete_consultation(consultation_id: str) -> Any:
    require_csrf()
    user = session_user()
    assert user is not None
    try:
        delete_saved_consultation(
            cast(Session, db.session), user=user, consultation_id=consultation_id
        )
        db.session.commit()
    except StudentRecordAccessError as error:
        db.session.rollback()
        return _render_records(error=str(error), status=404)
    return redirect(url_for("account.records"))


@bp.get("/consultations/<consultation_id>/clone")
@roles_required("STUDENT", "TEACHER", "ADMIN", allow_legacy=False)
def clone_consultation(consultation_id: str) -> Response:
    user = session_user()
    assert user is not None
    try:
        rows = saved_consultation_input_rows(
            cast(Session, db.session), user=user, consultation_id=consultation_id
        )
    except StudentRecordAccessError as error:
        return _render_records(error=str(error), status=404)
    return _private(
        render_template(
            "public_calculation_input.html",
            csrf_token=csrf_token(),
            rows=rows,
            programs=list_consultation_programs(cast(Session, db.session), 2027),
            current_user=user,
            errors=(),
            example=False,
            cloned_from=consultation_id,
        )
    )


@bp.get("/consultations/<consultation_id>/print/<audience>")
@roles_required("STUDENT", "TEACHER", "ADMIN", allow_legacy=False)
def print_saved_consultation(consultation_id: str, audience: str) -> Response:
    if audience not in {"student", "teacher"}:
        return _private("출력 구분을 찾을 수 없습니다.", 404)
    user = session_user()
    assert user is not None
    try:
        consultation = get_saved_consultation(
            cast(Session, db.session), user=user, consultation_id=consultation_id
        )
    except StudentRecordAccessError as error:
        return _private(str(error), 404)
    snapshot = (
        consultation.student_print_snapshot
        if audience == "student"
        else consultation.teacher_print_snapshot
    )
    return _private(
        render_template(
            "account_saved_consultation_print.html",
            consultation=consultation,
            audience=audience,
            payload=snapshot.get("result", {}),
        )
    )


__all__ = ["bp"]
