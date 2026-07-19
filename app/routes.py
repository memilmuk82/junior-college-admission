from __future__ import annotations

import hmac
import secrets
from typing import cast

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy.orm import Session
from werkzeug.datastructures import MultiDict

from app.auth import actor_ref, session_user
from app.database import db
from app.services.ai_payloads import (
    build_anonymous_consultation_payload,
    validated_payload_copy,
)
from app.services.anonymous_calculations import (
    AnonymousCalculationError,
    AnonymousCalculationState,
    AnonymousCalculationStore,
    save_anonymous_consultation,
    save_anonymous_records,
    to_academic_record_inputs,
)
from app.services.confirmed_imports import (
    ConfirmationValidationError,
    confirm_structured_import,
)
from app.services.consultation_forms import ConsultationFormResult, parse_consultation_form
from app.services.consultations import (
    BatchConsultationRequest,
    BatchConsultationResult,
    ConsultationError,
    list_consultation_programs,
    run_batch_consultation,
)
from app.services.review_forms import parse_review_submission, preview_values
from app.services.review_state import ReviewState, ReviewStateError, ReviewStateStore
from app.services.structured_imports import (
    StructuredImportPreview,
    StructuredInputLimitError,
    parse_structured_text,
    parse_xlsx_bytes,
)
from app.services.temporary_uploads import TemporaryUploadStore
from app.services.z_score_previews import build_z_score_previews

bp = Blueprint("main", __name__)

SOURCE_FORMAT_LABELS = {
    "csv": "CSV",
    "pasted_table": "표 붙여넣기",
    "xlsx": "XLSX",
    "text_pdf": "텍스트 PDF",
    "image_png": "PNG 이미지",
    "image_jpeg": "JPEG 이미지",
    "clipboard_image": "클립보드 이미지",
    "scanned_pdf": "이미지형 PDF",
}

ANONYMOUS_OWNER_SESSION_KEY = "anonymous_calculation_owner"
ANONYMOUS_ID_SESSION_KEY = "anonymous_calculation_id"
ALLOWED_RECORD_SOURCES = frozenset(
    {
        "HOME_SCHOOL_RECORD",
        "VOCATIONAL_TRAINING_RECORD",
        "GED_RECORD",
        "MANUAL_INPUT",
    }
)
EXAMPLE_COURSE_ROWS = (
    (2025, 1, 1, "국어", "국어", "4", "2"),
    (2025, 1, 1, "수학", "수학", "4", "3"),
    (2025, 1, 2, "영어", "영어", "4", "2"),
    (2025, 1, 2, "사회", "통합사회", "3", "3"),
    (2026, 2, 1, "국어", "문학", "4", "2"),
    (2026, 2, 1, "수학", "수학Ⅰ", "4", "2"),
    (2026, 2, 2, "영어", "영어Ⅰ", "4", "1"),
    (2026, 2, 2, "과학", "통합과학", "3", "2"),
    (2027, 3, 1, "국어", "화법과 작문", "3", "2"),
    (2027, 3, 1, "수학", "확률과 통계", "3", "2"),
)


def _upload_store() -> TemporaryUploadStore:
    return TemporaryUploadStore(str(current_app.config["TEMP_UPLOAD_ROOT"]))


def _anonymous_owner_token() -> str:
    token = session.get(ANONYMOUS_OWNER_SESSION_KEY)
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        session[ANONYMOUS_OWNER_SESSION_KEY] = token
    return token


def _current_review_owner_ref() -> str:
    if session_user() is not None or isinstance(session.get("admin_actor_ref"), str):
        return actor_ref()
    return f"anonymous:{_anonymous_owner_token()}"


def _review_state(review_session_id: str) -> ReviewState:
    try:
        state = ReviewStateStore(_upload_store()).load(review_session_id)
    except (FileNotFoundError, ReviewStateError, ValueError):
        abort(404)
    if state.owner_actor_ref != _current_review_owner_ref():
        abort(404)
    return state


def _anonymous_state(calculation_id: str) -> AnonymousCalculationState:
    if session.get(ANONYMOUS_ID_SESSION_KEY) != calculation_id:
        abort(404)
    try:
        return AnonymousCalculationStore(_upload_store()).load(
            calculation_id, owner_token=_anonymous_owner_token()
        )
    except AnonymousCalculationError:
        abort(404)


def _csrf_token() -> str:
    token = session.get("csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _require_csrf() -> None:
    expected = session.get("csrf_token")
    supplied = request.form.get("csrf_token", "")
    if not isinstance(expected, str) or not hmac.compare_digest(expected, supplied):
        abort(400)


def _private_response(content: str, status_code: int = 200) -> Response:
    response = make_response(content, status_code)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'"
    )
    return response


def _render_review(
    review_session_id: str,
    state: ReviewState,
    *,
    values: tuple[dict[str, str], ...],
    selected_indices: tuple[int, ...] = (),
    field_errors: dict[str, str] | None = None,
    blocking_errors: tuple[str, ...] = (),
    status_code: int = 200,
):
    resolved_values = tuple(dict(row) for row in values)
    for row in resolved_values:
        if not row.get("record_source"):
            row["record_source"] = state.record_source
        if not row.get("is_vocational_training_semester"):
            row["is_vocational_training_semester"] = (
                "TRUE" if state.is_vocational_training_semester else "FALSE"
            )
    response = render_template(
        "review.html",
        review_session_id=review_session_id,
        preview=state.preview,
        values=resolved_values,
        selected_indices=set(selected_indices),
        field_errors=field_errors or {},
        blocking_errors=blocking_errors,
        csrf_token=_csrf_token(),
        source_format_label=SOURCE_FORMAT_LABELS[state.preview.source_format],
        z_score_previews=build_z_score_previews(resolved_values),
        anonymous_mode=state.owner_actor_ref.startswith("anonymous:"),
        requires_ocr_review=any(
            issue.code == "OCR_REVIEW_REQUIRED" for issue in state.preview.issues
        ),
    )
    return _private_response(response, status_code)


@bp.get("/")
def index() -> Response:
    # 공개 상담이 제품의 기본 진입점이다. 로그인은 저장 기능에서만 요구한다.
    return cast(Response, redirect(url_for("main.public_calculation_input")))


def _manual_preview(form: MultiDict[str, str]) -> StructuredImportPreview:
    headers = (
        "학년도\t학년\t학기\t교과\t과목\t이수단위\t원점수\t평균\t"
        "표준편차\t성취도\t수강자수\t석차등급\t성적 출처\t위탁학기 여부"
    )
    lines = [headers]
    for index in range(40):
        subject = form.get(f"rows-{index}-subject_name", "").strip()
        if not subject:
            continue
        fields = (
            "academic_year",
            "grade",
            "semester",
            "subject_group",
            "subject_name",
            "credits",
            "raw_score",
            "course_mean",
            "standard_deviation",
            "achievement_level",
            "enrollment_count",
            "rank_grade",
            "record_source",
            "is_vocational_training_semester",
        )
        lines.append("\t".join(form.get(f"rows-{index}-{field}", "") for field in fields))
    return parse_structured_text("\n".join(lines), source_format="pasted_table")


def _input_defaults(*, example: bool) -> tuple[dict[str, str], ...]:
    defaults: list[dict[str, str]] = []
    source_rows: tuple[tuple[int, int, int, str, str, str, str], ...]
    if example:
        source_rows = EXAMPLE_COURSE_ROWS
    else:
        source_rows = tuple(
            (2025 + (grade - 1), grade, semester, "", "", "", "")
            for grade, semester in ((1, 1), (1, 2), (2, 1), (2, 2), (3, 1))
        )
    for academic_year, grade, semester, group, subject, credits, rank_grade in source_rows:
        defaults.append(
            {
                "academic_year": str(academic_year),
                "grade": str(grade),
                "semester": str(semester),
                "subject_group": group,
                "subject_name": subject,
                "credits": credits,
                "raw_score": "",
                "course_mean": "",
                "standard_deviation": "",
                "achievement_level": "",
                "enrollment_count": "",
                "rank_grade": rank_grade,
                "record_source": "HOME_SCHOOL_RECORD" if example else "MANUAL_INPUT",
                "is_vocational_training_semester": "FALSE",
            }
        )
    return tuple(defaults)


def _render_public_input(
    *, errors: tuple[str, ...] = (), status: int = 200, example: bool = False
) -> Response:
    programs = (
        list_consultation_programs(cast(Session, db.session), 2027)
        if current_app.config.get("DATABASE_URL")
        else ()
    )
    return _private_response(
        render_template(
            "public_calculation_input.html",
            csrf_token=_csrf_token(),
            rows=_input_defaults(example=example),
            programs=programs,
            current_user=session_user(),
            errors=errors,
            example=example,
        ),
        status,
    )


@bp.get("/calculate")
def public_calculation_input() -> Response:
    _upload_store().purge_expired_sessions()
    return _render_public_input(example=request.args.get("example") == "1")


@bp.post("/calculate/input")
def start_public_calculation() -> Response:
    _require_csrf()
    _upload_store().purge_expired_sessions()
    mode = request.form.get("input_mode", "manual")
    record_source = request.form.get("record_source", "MANUAL_INPUT")
    if record_source not in ALLOWED_RECORD_SOURCES:
        return _render_public_input(errors=("성적 출처를 확인하세요.",), status=400)
    previous_id = session.get(ANONYMOUS_ID_SESSION_KEY)
    if isinstance(previous_id, str):
        _upload_store().purge_session(previous_id)
    try:
        if mode == "manual":
            preview = _manual_preview(request.form)
            original: bytes | None = None
            suffix = ".txt"
        elif mode == "paste":
            pasted = request.form.get("pasted_table", "")
            if len(pasted.encode("utf-8")) > 2 * 1024 * 1024:
                raise ValueError("붙여넣기 입력 크기 제한을 초과했습니다.")
            preview = parse_structured_text(pasted, source_format="pasted_table")
            original = pasted.encode("utf-8")
            suffix = ".txt"
        elif mode == "upload":
            uploaded = request.files.get("score_file")
            if uploaded is None or not uploaded.filename:
                raise ValueError("CSV 또는 XLSX 파일을 선택하세요.")
            original = uploaded.read(20 * 1024 * 1024 + 1)
            suffix = ".xlsx" if uploaded.filename.lower().endswith(".xlsx") else ".csv"
            if suffix == ".xlsx":
                preview = parse_xlsx_bytes(original)
            elif uploaded.filename.lower().endswith(".csv"):
                preview = parse_structured_text(original.decode("utf-8-sig"), source_format="csv")
            else:
                raise ValueError("CSV와 XLSX 파일만 사용할 수 있습니다.")
        else:
            raise ValueError("입력 방식을 확인하세요.")
        if not preview.rows:
            raise ValueError("확인할 성적 행이 없습니다. 과목과 머리글을 확인하세요.")
    except (UnicodeError, ValueError, StructuredInputLimitError) as error:
        return _render_public_input(errors=(str(error),), status=400)

    calculation_id = _upload_store().create_session()
    try:
        if original is not None:
            _upload_store().write_artifact(calculation_id, original, kind="original", suffix=suffix)
        ReviewStateStore(_upload_store()).save(
            calculation_id,
            preview,
            student_id="anonymous-one-time",
            record_source=record_source,
            owner_actor_ref=f"anonymous:{_anonymous_owner_token()}",
            is_vocational_training_semester=(
                request.form.get("is_vocational_training_semester") == "TRUE"
            ),
        )
    except Exception:
        _upload_store().purge_session(calculation_id)
        raise
    session[ANONYMOUS_ID_SESSION_KEY] = calculation_id
    return cast(Response, redirect(url_for("main.review_input", review_session_id=calculation_id)))


def _public_target_values(form: MultiDict[str, str] | None = None) -> dict[str, str]:
    source = form or MultiDict()
    fields = (
        "academic_year",
        "admission_result_year",
        "home_school_type",
        "final_school_type",
        "graduation_status",
        "vocational_training_status",
        "vocational_training_semesters",
        "vocational_training_hours",
        "vocational_training_months",
        "transferred",
        "ged",
    )
    values = {field: source.get(field, "") for field in fields}
    # 이 서비스의 2027 상담 대상은 일반고 직업위탁 재학생으로 고정되어 있다.
    # 화면에서 다시 묻지 않더라도 서버 계약에서 같은 값을 강제한다.
    values["academic_year"] = "2027"
    values["admission_result_year"] = values["admission_result_year"] or "2025"
    values["home_school_type"] = "GENERAL"
    values["final_school_type"] = "GENERAL"
    values["graduation_status"] = "EXPECTED"
    values["vocational_training_status"] = "PARTICIPATING"
    values["ged"] = "FALSE"
    return values


def _render_public_targets(
    calculation_id: str,
    *,
    form: MultiDict[str, str] | None = None,
    errors: tuple[str, ...] = (),
    status: int = 200,
) -> Response:
    _anonymous_state(calculation_id)
    values = _public_target_values(form)
    try:
        academic_year = int(values["academic_year"])
    except ValueError:
        academic_year = 2027
    programs = list_consultation_programs(cast(Session, db.session), academic_year)
    selected = set(form.getlist("program_ids") if form is not None else ())
    return _private_response(
        render_template(
            "public_calculation_targets.html",
            calculation_id=calculation_id,
            csrf_token=_csrf_token(),
            values=values,
            programs=programs,
            selected_program_ids=selected,
            errors=errors,
        ),
        status,
    )


@bp.get("/calculate/<calculation_id>/targets")
def public_calculation_targets(calculation_id: str) -> Response:
    return _render_public_targets(
        calculation_id,
        form=MultiDict(request.args) if request.args else None,
    )


def _parse_public_consultation(
    calculation_id: str, form: MultiDict[str, str]
) -> tuple[ConsultationFormResult, BatchConsultationResult | None]:
    augmented = MultiDict(form)
    augmented["student_id"] = f"anonymous-{calculation_id}"
    augmented["admission_track_id"] = ""
    augmented["consultation_note"] = ""
    parsed = parse_consultation_form(augmented)
    if parsed.errors or not isinstance(parsed.request, BatchConsultationRequest):
        return parsed, None
    state = _anonymous_state(calculation_id)
    records = to_academic_record_inputs(state)
    result = run_batch_consultation(
        cast(Session, db.session),
        parsed.request,
        records_loader=lambda: records,
    )
    return parsed, result


@bp.post("/calculate/<calculation_id>/results")
def public_calculation_results(calculation_id: str) -> Response:
    _require_csrf()
    try:
        parsed, result = _parse_public_consultation(calculation_id, request.form)
    except (AnonymousCalculationError, ConsultationError, ValueError) as error:
        return _render_public_targets(
            calculation_id, form=request.form, errors=(str(error),), status=400
        )
    if result is None:
        return _render_public_targets(
            calculation_id, form=request.form, errors=parsed.errors, status=400
        )
    result_snapshot = validated_payload_copy(build_anonymous_consultation_payload(result))
    AnonymousCalculationStore(_upload_store()).attach_consultation_snapshot(
        calculation_id,
        owner_token=_anonymous_owner_token(),
        snapshot={
            "academic_year": result.academic_year,
            "selected_targets": [
                {
                    "program_id": item.program_id,
                    "institution_name": item.institution_name,
                    "campus_name": item.campus_name,
                    "program_name": item.program_name,
                }
                for item in result.selected_programs
            ],
            "result_snapshot": result_snapshot,
        },
    )
    return _private_response(
        render_template(
            "public_calculation_result.html",
            calculation_id=calculation_id,
            csrf_token=_csrf_token(),
            result=result,
            values=request.form,
        )
    )


@bp.post("/calculate/<calculation_id>/print/<audience>")
def public_calculation_print(calculation_id: str, audience: str) -> Response:
    if audience not in {"student", "teacher"}:
        abort(404)
    _require_csrf()
    try:
        parsed, result = _parse_public_consultation(calculation_id, request.form)
    except (AnonymousCalculationError, ConsultationError, ValueError) as error:
        return _render_public_targets(
            calculation_id, form=request.form, errors=(str(error),), status=400
        )
    if result is None:
        return _render_public_targets(
            calculation_id, form=request.form, errors=parsed.errors, status=400
        )
    return _private_response(
        render_template(
            "public_calculation_print.html",
            calculation_id=calculation_id,
            audience=audience,
            result=result,
        )
    )


@bp.post("/calculate/<calculation_id>/complete")
def complete_public_calculation(calculation_id: str) -> Response:
    _require_csrf()
    _anonymous_state(calculation_id)
    _upload_store().purge_session(calculation_id)
    session.pop(ANONYMOUS_ID_SESSION_KEY, None)
    return cast(Response, redirect(url_for("main.index", calculation_deleted="1")))


@bp.route("/calculate/<calculation_id>/save", methods=["GET", "POST"])
def save_public_calculation(calculation_id: str) -> Response:
    state = _anonymous_state(calculation_id)
    user = session_user()
    if user is None:
        return cast(
            Response,
            redirect(
                url_for(
                    "auth.login",
                    next=url_for("main.save_public_calculation", calculation_id=calculation_id),
                )
            ),
        )
    if user.status != "ACTIVE" or user.role not in {"STUDENT", "TEACHER"}:
        abort(403)
    if request.method == "GET":
        return _private_response(
            render_template(
                "public_calculation_save.html",
                calculation_id=calculation_id,
                current_user=user,
                record_count=len(to_academic_record_inputs(state)),
                csrf_token=_csrf_token(),
            )
        )
    _require_csrf()
    try:
        save_anonymous_records(
            cast(Session, db.session),
            state=state,
            calculation_id=calculation_id,
            user=user,
        )
        save_anonymous_consultation(
            cast(Session, db.session),
            state=state,
            calculation_id=calculation_id,
            user=user,
            counselor_note=request.form.get("counselor_note", ""),
        )
        db.session.commit()
    except AnonymousCalculationError as error:
        db.session.rollback()
        return _private_response(str(error), 409)
    _upload_store().purge_session(calculation_id)
    session.pop(ANONYMOUS_ID_SESSION_KEY, None)
    return cast(Response, redirect(url_for("account.records")))


@bp.get("/health")
def health():
    return jsonify(service="junior-college-admission", status="ok")


@bp.route("/input/review/<review_session_id>", methods=["GET", "POST"])
def review_input(review_session_id: str):
    state = _review_state(review_session_id)
    if request.method == "GET":
        selected_indices = (
            tuple(range(len(state.preview.rows)))
            if state.owner_actor_ref.startswith("anonymous:")
            else ()
        )
        return _render_review(
            review_session_id,
            state,
            values=preview_values(state.preview),
            selected_indices=selected_indices,
        )

    _require_csrf()
    submission = parse_review_submission(request.form, state.preview)
    if not submission.is_valid:
        return _render_review(
            review_session_id,
            state,
            values=submission.values,
            selected_indices=submission.selected_indices,
            field_errors=submission.field_errors,
            blocking_errors=submission.blocking_errors,
            status_code=400,
        )
    if state.owner_actor_ref.startswith("anonymous:"):
        selected_rows = tuple(
            submission.preview.rows[index] for index in submission.selected_indices
        )
        AnonymousCalculationStore(_upload_store()).save(
            review_session_id,
            owner_token=_anonymous_owner_token(),
            record_source=state.record_source,
            is_vocational_training_semester=state.is_vocational_training_semester,
            rows=selected_rows,
        )
        return redirect(
            url_for("main.public_calculation_targets", calculation_id=review_session_id)
        )
    try:
        result = confirm_structured_import(
            cast(Session, db.session),
            preview=submission.preview,
            confirmed_row_indices=submission.selected_indices,
            student_id=state.student_id,
            record_source=state.record_source,
            upload_store=_upload_store(),
            review_session_id=review_session_id,
        )
    except ConfirmationValidationError as error:
        return _render_review(
            review_session_id,
            state,
            values=submission.values,
            selected_indices=submission.selected_indices,
            field_errors=submission.field_errors,
            blocking_errors=(str(error),),
            status_code=400,
        )
    return _private_response(
        render_template(
            "review_complete.html",
            confirmed_count=len(result.course_record_ids),
        )
    )


@bp.post("/input/review/<review_session_id>/discard")
def discard_review(review_session_id: str):
    _require_csrf()
    state = _review_state(review_session_id)
    _upload_store().purge_session(review_session_id)
    if state.owner_actor_ref.startswith("anonymous:"):
        session.pop(ANONYMOUS_ID_SESSION_KEY, None)
        return redirect(url_for("main.public_calculation_input"))
    return redirect(url_for("main.index", discarded="1"))
