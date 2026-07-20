from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash

from app.auth import (
    begin_google_oidc_intent,
    csrf_token,
    is_demo_user,
    require_csrf,
    roles_required,
    session_user,
    signed_in_required,
    start_user_session,
)
from app.database import db
from app.models import (
    ClassroomStudent,
    SavedConsultation,
    StudentAcademicRecord,
    StudentCourseRecord,
    TeacherClassroom,
)
from app.services.account_emails import (
    AccountEmailError,
    account_email_available,
    send_email_verification,
)
from app.services.account_security import (
    change_password,
    disconnect_google_identity,
    google_identity_for_user,
    issue_email_verification_token,
)
from app.services.classroom_links import (
    ClassroomLinkError,
    connect_student_account,
    disconnect_student_account,
    linked_classrooms_for_student,
)
from app.services.consultations import list_consultation_programs
from app.services.demo_workspace import demo_academic_records
from app.services.membership import MembershipError
from app.services.public_student_profiles import (
    GENERAL_GRADUATE,
    VOCATIONAL_CURRENT,
)
from app.services.student_record_access import (
    StudentRecordAccessError,
    academic_record_courses,
    can_access_academic_record,
    can_access_saved_consultation,
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


def _google_enabled() -> bool:
    return bool(
        current_app.config.get("GOOGLE_OIDC_ENABLED")
        or current_app.config.get("DEMO_GOOGLE_STUB_ENABLED")
    )


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


def _render_security(*, error: str | None = None, status: int = 200) -> Response:
    user = session_user()
    assert user is not None
    return _private(
        render_template(
            "account_security.html",
            current_user=user,
            csrf_token=csrf_token(),
            error=error,
            message=request.args.get("message"),
            demo_mode=is_demo_user(user),
            email_available=account_email_available(),
            google_enabled=_google_enabled(),
            google_identity=google_identity_for_user(cast(Session, db.session), user=user),
        ),
        status,
    )


def _mutable_security_user() -> Any:
    user = session_user()
    assert user is not None
    if is_demo_user(user):
        abort(403)
    return user


@bp.get("/security")
@signed_in_required
def security() -> Response:
    return _render_security()


@bp.post("/security/password")
@signed_in_required
def change_security_password() -> Any:
    require_csrf()
    user = _mutable_security_user()
    new_password = request.form.get("new_password", "")
    if new_password != request.form.get("new_password_confirmation", ""):
        return _render_security(error="비밀번호 확인이 일치하지 않습니다.", status=400)
    try:
        changed = change_password(
            cast(Session, db.session),
            user=user,
            current_password=request.form.get("current_password", ""),
            new_password=new_password,
            occurred_at=datetime.now(UTC),
        )
        db.session.commit()
    except MembershipError as error:
        db.session.rollback()
        return _render_security(error=str(error), status=400)
    start_user_session(changed)
    return redirect(url_for("account.security", message="password_changed"), code=303)


@bp.post("/security/email")
@signed_in_required
def change_security_email() -> Any:
    require_csrf()
    user = _mutable_security_user()
    if user.status != "ACTIVE":
        return _render_security(
            error="활성 계정에서만 로그인 이메일을 변경할 수 있습니다.", status=403
        )
    if not account_email_available():
        return _render_security(error="인증 메일 발송 설정이 필요합니다.", status=503)
    if user.password_hash is None or not check_password_hash(
        user.password_hash, request.form.get("current_password", "")
    ):
        return _render_security(error="현재 비밀번호를 확인하세요.", status=400)
    target_email = request.form.get("email", "").strip().lower()
    if current_app.config.get("DEMO_SANDBOX_ENABLED") and not target_email.endswith(".invalid"):
        return _render_security(
            error="체험 환경에는 개인정보가 아닌 .invalid 예시 이메일을 입력하세요.",
            status=400,
        )
    try:
        raw_token = issue_email_verification_token(
            cast(Session, db.session),
            user=user,
            target_email=target_email,
            occurred_at=datetime.now(UTC),
        )
        db.session.commit()
    except MembershipError as error:
        db.session.rollback()
        if str(error) == "이미 사용 중인 이메일입니다.":
            return redirect(url_for("account.security", message="email_requested"), code=303)
        return _render_security(error=str(error), status=400)
    try:
        send_email_verification(recipient=target_email, raw_token=raw_token)
    except AccountEmailError as error:
        return _render_security(error=str(error), status=503)
    return redirect(url_for("account.security", message="email_requested"), code=303)


@bp.post("/security/google/connect")
@signed_in_required
def connect_google() -> Any:
    require_csrf()
    user = _mutable_security_user()
    if user.status != "ACTIVE":
        return _render_security(
            error="활성 계정에서만 Google 계정을 연결할 수 있습니다.", status=403
        )
    if not _google_enabled():
        return _render_security(error="Google 로그인 설정이 필요합니다.", status=503)
    if user.email_verified_at is None:
        return _render_security(error="이메일을 먼저 인증하세요.", status=400)
    if user.password_hash is None or not check_password_hash(
        user.password_hash, request.form.get("current_password", "")
    ):
        return _render_security(error="현재 비밀번호를 확인하세요.", status=400)
    begin_google_oidc_intent(kind="link", user=user)
    return redirect(url_for("auth.google_start", intent="link"), code=303)


@bp.post("/security/google/disconnect")
@signed_in_required
def disconnect_google() -> Any:
    require_csrf()
    user = _mutable_security_user()
    try:
        disconnect_google_identity(
            cast(Session, db.session),
            user=user,
            current_password=request.form.get("current_password", ""),
            occurred_at=datetime.now(UTC),
        )
        db.session.commit()
    except MembershipError as error:
        db.session.rollback()
        return _render_security(error=str(error), status=400)
    start_user_session(user)
    return redirect(url_for("account.security", message="google_disconnected"), code=303)


def _render_records(*, error: str | None = None, status: int = 200) -> Response:
    user = session_user()
    assert user is not None
    demo_mode = is_demo_user(user)
    records: tuple[StudentAcademicRecord, ...]
    consultations: tuple[SavedConsultation, ...]
    courses_by_record: dict[str, tuple[StudentCourseRecord, ...]]
    linked_classrooms: tuple[tuple[ClassroomStudent, TeacherClassroom], ...] = ()
    if demo_mode:
        records, courses_by_record = demo_academic_records(user)
        consultations = ()
    else:
        try:
            records = visible_academic_records(cast(Session, db.session), user=user)
            consultations = visible_saved_consultations(cast(Session, db.session), user=user)
            courses_by_record = academic_record_courses(cast(Session, db.session), records=records)
            if user.role == "STUDENT":
                linked_classrooms = linked_classrooms_for_student(
                    cast(Session, db.session), user=user
                )
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
            demo_mode=demo_mode,
            linked_classrooms=linked_classrooms,
            manageable_record_ids=(
                frozenset()
                if demo_mode
                else frozenset(
                    record.id for record in records if can_access_academic_record(user, record)
                )
            ),
            manageable_consultation_ids=frozenset(
                consultation.id
                for consultation in consultations
                if can_access_saved_consultation(user, consultation)
            ),
            message=request.args.get("message"),
        ),
        status,
    )


@bp.get("/records")
@roles_required("STUDENT", "TEACHER", "ADMIN", "MEMBER", allow_legacy=False)
def records() -> Response:
    return _render_records()


@bp.post("/classroom-links")
@roles_required("STUDENT", allow_legacy=False)
def connect_classroom() -> Any:
    require_csrf()
    user = session_user()
    assert user is not None
    try:
        connect_student_account(
            cast(Session, db.session),
            user=user,
            connection_code=request.form.get("connection_code", ""),
            consent_confirmed=request.form.get("share_consent") == "AGREED",
        )
        db.session.commit()
    except ClassroomLinkError as error:
        db.session.rollback()
        return _render_records(error=str(error), status=400)
    except IntegrityError:
        db.session.rollback()
        return _render_records(error="이미 이 학급에 연결되어 있습니다.", status=409)
    return redirect(url_for("account.records", message="classroom_connected"))


@bp.post("/classroom-links/<classroom_student_id>/disconnect")
@roles_required("STUDENT", allow_legacy=False)
def disconnect_classroom(classroom_student_id: str) -> Any:
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
        return _render_records(error=str(error), status=404)
    return redirect(url_for("account.records", message="classroom_disconnected"))


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
@roles_required("ADMIN", "TEACHER", allow_legacy=False)
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
        consultation = get_saved_consultation(
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
            selected_student_profile=consultation.student_profile,
            vocational_current_profile=VOCATIONAL_CURRENT,
            general_graduate_profile=GENERAL_GRADUATE,
            selected_input_mode="manual",
            selected_record_source="HOME_SCHOOL_RECORD",
            selected_vocational_semester=False,
            pasted_table="",
        )
    )


@bp.get("/consultations/<consultation_id>/print/<audience>")
@roles_required("STUDENT", "TEACHER", "ADMIN", allow_legacy=False)
def print_saved_consultation(consultation_id: str, audience: str) -> Response:
    if audience not in {"student", "teacher"}:
        return _private("출력 구분을 찾을 수 없습니다.", 404)
    user = session_user()
    assert user is not None
    if audience == "teacher" and user.role not in {"TEACHER", "ADMIN"}:
        # 학생은 공유 상담의 학생용 결과만 확인하며 교사용 근거·메모를 보지 않는다.
        return _private("상담 이력을 찾을 수 없습니다.", 404)
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
