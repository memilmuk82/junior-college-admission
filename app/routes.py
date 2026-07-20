from __future__ import annotations

import hmac
import secrets
from dataclasses import replace
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

from app.auth import actor_ref, is_demo_user, roles_required, session_user
from app.database import db
from app.services.admission_result_imports import list_published_result_years
from app.services.ai_payloads import (
    build_anonymous_consultation_payload,
    validated_payload_copy,
    validated_saved_payload_copy,
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
from app.services.demo_scores import DEMO_SCORE_ROWS, DemoScoreRow
from app.services.eligibility import EligibilityStatus
from app.services.membership import DEMO_ACTOR_REF, has_teacher_capability
from app.services.public_student_profiles import (
    GENERAL_GRADUATE,
    VOCATIONAL_CURRENT,
    public_record_classification,
    public_student_fact_values,
    resolve_public_student_profile,
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
REFERENCE_TERMS = (
    (2025, 1, 1),
    (2025, 1, 2),
    (2026, 2, 1),
    (2026, 2, 2),
    (2027, 3, 1),
    (2027, 3, 2),
)
REFERENCE_ROWS_PER_TERM = 10
MAX_MANUAL_ROWS = len(REFERENCE_TERMS) * REFERENCE_ROWS_PER_TERM


def _classify_public_preview(
    preview: StructuredImportPreview, *, student_profile: str
) -> StructuredImportPreview:
    resolved_profile = resolve_public_student_profile(student_profile)
    rows = []
    for row in preview.rows:
        if row.grade not in {1, 2, 3} or row.semester not in {1, 2}:
            rows.append(row)
            continue
        assert row.semester is not None
        record_source, is_vocational = public_record_classification(
            resolved_profile, grade=row.grade, semester=row.semester
        )
        rows.append(
            replace(
                row,
                record_source=record_source,
                is_vocational_training_semester=is_vocational,
            )
        )
    return replace(preview, rows=tuple(rows))


def _classify_public_values(
    values: tuple[dict[str, str], ...], *, student_profile: str
) -> tuple[dict[str, str], ...]:
    resolved = []
    for source in values:
        row = dict(source)
        try:
            grade = int(row.get("grade", ""))
            semester = int(row.get("semester", ""))
            record_source, is_vocational = public_record_classification(
                student_profile, grade=grade, semester=semester
            )
        except ValueError:
            pass
        else:
            row["record_source"] = record_source
            row["is_vocational_training_semester"] = "TRUE" if is_vocational else "FALSE"
        resolved.append(row)
    return tuple(resolved)


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
    allowed_owner_refs = {_current_review_owner_ref()}
    anonymous_owner = session.get(ANONYMOUS_OWNER_SESSION_KEY)
    if isinstance(anonymous_owner, str):
        # 공개 계산은 로그인 상태에서도 계정 DB와 분리된 일회성 세션을 사용한다.
        allowed_owner_refs.add(f"anonymous:{anonymous_owner}")
    if state.owner_actor_ref not in allowed_owner_refs:
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
    if not isinstance(expected, str) or not hmac.compare_digest(
        expected.encode("utf-8"), supplied.encode("utf-8")
    ):
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
    anonymous_mode = state.owner_actor_ref.startswith("anonymous:")
    if anonymous_mode:
        resolved_values = _classify_public_values(values, student_profile=state.student_profile)
    else:
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
        anonymous_mode=anonymous_mode,
        student_profile=state.student_profile,
        requires_ocr_review=any(
            issue.code == "OCR_REVIEW_REQUIRED" for issue in state.preview.issues
        ),
    )
    return _private_response(response, status_code)


@bp.get("/")
def index() -> Response:
    # 공개 상담이 제품의 기본 진입점이다. 로그인은 저장 기능에서만 요구한다.
    return cast(Response, redirect(url_for("main.public_calculation_input")))


@bp.get("/dashboard")
@roles_required("ADMIN", "ASSISTANT_ADMIN", "MEMBER", "TEACHER", "STUDENT", allow_legacy=False)
def dashboard() -> Response:
    user = session_user()
    assert user is not None
    if user.actor_ref == DEMO_ACTOR_REF:
        return cast(Response, redirect(url_for("main.public_calculation_input", example="1")))
    return _private_response(
        render_template(
            "account_dashboard.html",
            current_user=user,
            csrf_token=_csrf_token(),
        )
    )


def _manual_preview(form: MultiDict[str, str]) -> StructuredImportPreview:
    headers = (
        "학년도\t학년\t학기\t교과\t과목\t이수단위\t원점수\t평균\t"
        "표준편차\t성취도\t수강자수\t석차등급\t성적 출처\t위탁학기 여부"
    )
    lines = [headers]
    for index in range(MAX_MANUAL_ROWS):
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


def _input_defaults(
    *, example: bool, student_profile: str = VOCATIONAL_CURRENT
) -> tuple[dict[str, str], ...]:
    resolved_profile = resolve_public_student_profile(student_profile)
    defaults: list[dict[str, str]] = []
    example_rows_by_term = {
        (academic_year, grade, semester): tuple(
            row
            for row in DEMO_SCORE_ROWS
            if (row.academic_year, row.grade, row.semester) == (academic_year, grade, semester)
        )
        for academic_year, grade, semester in REFERENCE_TERMS
    }
    source_rows: list[DemoScoreRow | None] = []
    for academic_year, grade, semester in REFERENCE_TERMS:
        examples = example_rows_by_term[(academic_year, grade, semester)] if example else ()
        source_rows.extend(examples)
        source_rows.extend(None for _ in range(REFERENCE_ROWS_PER_TERM - len(examples)))
    term_index = 0
    for source in source_rows:
        if source is None:
            academic_year, grade, semester = REFERENCE_TERMS[term_index // REFERENCE_ROWS_PER_TERM]
            group = subject = credits = rank_grade = ""
            raw_score = course_mean = standard_deviation = ""
        else:
            academic_year, grade, semester = (
                source.academic_year,
                source.grade,
                source.semester,
            )
            group = source.subject_group
            subject = source.subject_name
            credits = source.credits
            rank_grade = source.rank_grade
            raw_score = source.raw_score
            course_mean = source.course_mean
            standard_deviation = source.standard_deviation
        record_source, is_vocational = public_record_classification(
            resolved_profile, grade=grade, semester=semester
        )
        defaults.append(
            {
                "academic_year": str(academic_year),
                "grade": str(grade),
                "semester": str(semester),
                "subject_group": group,
                "subject_name": subject,
                "credits": credits,
                "raw_score": raw_score,
                "course_mean": course_mean,
                "standard_deviation": standard_deviation,
                "achievement_level": "",
                "enrollment_count": "",
                "rank_grade": rank_grade,
                "record_source": record_source,
                "is_vocational_training_semester": "TRUE" if is_vocational else "FALSE",
            }
        )
        term_index += 1
    return tuple(defaults)


def _submitted_manual_rows(
    form: MultiDict[str, str], *, student_profile: str = VOCATIONAL_CURRENT
) -> tuple[dict[str, str], ...]:
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
    rows: list[dict[str, str]] = []
    for index in range(MAX_MANUAL_ROWS):
        values = {field: form.get(f"rows-{index}-{field}", "") for field in fields}
        if values["academic_year"] or values["subject_name"]:
            rows.append(values)
    source_rows = tuple(rows) or _input_defaults(example=False, student_profile=student_profile)
    return _classify_public_values(source_rows, student_profile=student_profile)


def _render_public_input(
    *,
    errors: tuple[str, ...] = (),
    status: int = 200,
    example: bool = False,
    rows: tuple[dict[str, str], ...] | None = None,
    input_mode: str = "manual",
    record_source: str = "HOME_SCHOOL_RECORD",
    pasted_table: str = "",
    is_vocational_training_semester: bool = False,
    student_profile: str = VOCATIONAL_CURRENT,
) -> Response:
    resolved_profile = resolve_public_student_profile(student_profile)
    return _private_response(
        render_template(
            "public_calculation_input.html",
            csrf_token=_csrf_token(),
            rows=rows or _input_defaults(example=example, student_profile=resolved_profile),
            current_user=session_user(),
            errors=errors,
            example=example,
            selected_input_mode=input_mode,
            selected_record_source=record_source,
            pasted_table=pasted_table,
            selected_vocational_semester=is_vocational_training_semester,
            selected_student_profile=resolved_profile,
            vocational_current_profile=VOCATIONAL_CURRENT,
            general_graduate_profile=GENERAL_GRADUATE,
        ),
        status,
    )


@bp.get("/calculate")
def public_calculation_input() -> Response:
    _upload_store().purge_expired_sessions()
    try:
        student_profile = resolve_public_student_profile(request.args.get("student_profile"))
    except ValueError as error:
        return _render_public_input(errors=(str(error),), status=400)
    return _render_public_input(
        example=request.args.get("example") == "1",
        student_profile=student_profile,
    )


@bp.post("/calculate/input")
def start_public_calculation() -> Response:
    _require_csrf()
    _upload_store().purge_expired_sessions()
    mode = request.form.get("input_mode", "manual")
    try:
        student_profile = resolve_public_student_profile(request.form.get("student_profile"))
    except ValueError as error:
        return _render_public_input(
            errors=(str(error),),
            status=400,
            rows=_submitted_manual_rows(request.form),
            input_mode=mode,
            record_source="HOME_SCHOOL_RECORD",
            pasted_table=request.form.get("pasted_table", ""),
            student_profile=VOCATIONAL_CURRENT,
        )
    # 공개 입력은 사용자 선택 출처를 신뢰하지 않고 프로필·학년으로 행마다 분류한다.
    record_source = "HOME_SCHOOL_RECORD"
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
        preview = _classify_public_preview(preview, student_profile=student_profile)
        if not preview.rows:
            raise ValueError("확인할 성적 행이 없습니다. 과목과 머리글을 확인하세요.")
    except (UnicodeError, ValueError, StructuredInputLimitError) as error:
        return _render_public_input(
            errors=(str(error),),
            status=400,
            rows=_submitted_manual_rows(request.form, student_profile=student_profile),
            input_mode=mode,
            record_source=record_source,
            pasted_table=request.form.get("pasted_table", ""),
            student_profile=student_profile,
        )

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
            is_vocational_training_semester=False,
            student_profile=student_profile,
        )
    except Exception:
        _upload_store().purge_session(calculation_id)
        raise
    session[ANONYMOUS_ID_SESSION_KEY] = calculation_id
    return cast(Response, redirect(url_for("main.review_input", review_session_id=calculation_id)))


def _public_target_values(
    form: MultiDict[str, str] | None = None, *, student_profile: str | None = None
) -> dict[str, str]:
    source = form or MultiDict()
    fields = (
        "student_profile",
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
    resolved_profile = resolve_public_student_profile(
        student_profile if student_profile is not None else values["student_profile"]
    )
    # 공개 상담의 대상 사실값은 브라우저 hidden 값이 아니라 승인된 프로필로 확정한다.
    values["academic_year"] = "2027"
    values["admission_result_year"] = values["admission_result_year"] or "2026"
    values.update(public_student_fact_values(resolved_profile))
    if resolved_profile == GENERAL_GRADUATE:
        values["vocational_training_semesters"] = ""
        values["vocational_training_hours"] = ""
        values["vocational_training_months"] = ""
    return values


def _render_public_targets(
    calculation_id: str,
    *,
    form: MultiDict[str, str] | None = None,
    errors: tuple[str, ...] = (),
    status: int = 200,
) -> Response:
    state = _anonymous_state(calculation_id)
    values = _public_target_values(form, student_profile=state.student_profile)
    try:
        academic_year = int(values["academic_year"])
    except ValueError:
        academic_year = 2027
    programs = list_consultation_programs(cast(Session, db.session), academic_year)
    published_result_years = list_published_result_years(cast(Session, db.session), academic_year)
    # 2026 공개 자료는 Phase 17의 기준 자료다. 아직 seed 전인 개발 DB에서도
    # 선택값과 서버 기본값이 달라지지 않도록 기준연도를 먼저 노출한다.
    if 2026 not in published_result_years:
        published_result_years = (2026, *published_result_years)
    selected = set(form.getlist("program_ids") if form is not None else ())
    return _private_response(
        render_template(
            "public_calculation_targets.html",
            calculation_id=calculation_id,
            csrf_token=_csrf_token(),
            values=values,
            programs=programs,
            published_result_years=published_result_years,
            selected_program_ids=selected,
            errors=errors,
            current_user=session_user(),
            vocational_current_profile=VOCATIONAL_CURRENT,
            general_graduate_profile=GENERAL_GRADUATE,
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
    state = _anonymous_state(calculation_id)
    derived_values = _public_target_values(form, student_profile=state.student_profile)
    augmented = MultiDict(form)
    for field, value in derived_values.items():
        augmented[field] = value
    augmented["student_id"] = f"anonymous-{calculation_id}"
    augmented["admission_track_id"] = ""
    augmented["consultation_note"] = ""
    parsed = parse_consultation_form(augmented)
    if parsed.errors or not isinstance(parsed.request, BatchConsultationRequest):
        return parsed, None
    records = to_academic_record_inputs(state)
    result = run_batch_consultation(
        cast(Session, db.session),
        parsed.request,
        records_loader=lambda: records,
    )
    return parsed, _filter_public_consultation_result(result)


def _filter_public_consultation_result(
    result: BatchConsultationResult,
) -> BatchConsultationResult:
    public_items = tuple(
        item
        for item in result.items
        if item.result is None or item.result.eligibility.status is not EligibilityStatus.INELIGIBLE
    )
    return replace(result, items=public_items)


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
    payload = build_anonymous_consultation_payload(result)
    result_snapshot = (
        validated_payload_copy(payload)
        if result.items
        else validated_saved_payload_copy(payload.data)
    )
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
            current_user=session_user(),
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
    if user.status != "ACTIVE" or (user.role != "STUDENT" and not has_teacher_capability(user)):
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
    if is_demo_user() and not state.owner_actor_ref.startswith("anonymous:"):
        abort(403)
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
    anonymous_mode = state.owner_actor_ref.startswith("anonymous:")
    review_form = request.form.copy()
    if anonymous_mode:
        # 공개 화면에서 숨긴 출처 값은 파서에 넘기기 전에도 신뢰하지 않는다.
        for index in range(len(state.preview.rows)):
            try:
                grade = int(review_form.get(f"rows-{index}-grade", ""))
                semester = int(review_form.get(f"rows-{index}-semester", ""))
                record_source, is_vocational = public_record_classification(
                    state.student_profile, grade=grade, semester=semester
                )
            except ValueError:
                record_source, is_vocational = "HOME_SCHOOL_RECORD", False
            review_form[f"rows-{index}-record_source"] = record_source
            review_form[f"rows-{index}-is_vocational_training_semester"] = (
                "TRUE" if is_vocational else "FALSE"
            )
    submission = parse_review_submission(review_form, state.preview)
    if anonymous_mode:
        submission = replace(
            submission,
            preview=_classify_public_preview(
                submission.preview, student_profile=state.student_profile
            ),
            values=_classify_public_values(
                submission.values, student_profile=state.student_profile
            ),
        )
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
            student_profile=state.student_profile,
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
    if is_demo_user() and not state.owner_actor_ref.startswith("anonymous:"):
        abort(403)
    _upload_store().purge_session(review_session_id)
    if state.owner_actor_ref.startswith("anonymous:"):
        session.pop(ANONYMOUS_ID_SESSION_KEY, None)
        return redirect(url_for("main.public_calculation_input"))
    return redirect(url_for("main.index", discarded="1"))
