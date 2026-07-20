from __future__ import annotations

from collections.abc import Callable, Mapping
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
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import (
    actor_ref,
    admin_required,
    byok_actor_ref,
    csrf_token,
    end_user_session,
    is_demo_user,
    member_required,
    non_demo_required,
    require_csrf,
    roles_required,
    session_user,
)
from app.auth_routes import login_view
from app.database import db
from app.models import (
    AdmissionRound,
    AdmissionTrack,
    AiConsultationDraft,
    AiProviderCredential,
    Campus,
    Institution,
    Program,
    RuleAuditEvent,
    RuleGoldenTestArtifact,
    RuleReview,
    RuleVersionLineage,
    ScoreRule,
    SourceCitation,
    StudentAcademicRecord,
    UserAccount,
)
from app.services.account_consultations import (
    AccountConsultationError,
    save_account_consultation,
)
from app.services.ai_credentials import (
    ByokCredentialCipher,
    ByokCredentialError,
    delete_provider_credential,
    save_provider_credential,
)
from app.services.ai_drafts import (
    AiDraftError,
    confirm_ai_draft,
    delete_ai_draft,
    reject_ai_draft,
)
from app.services.ai_http_providers import provider_adapter
from app.services.ai_narratives import AiNarrativeError, generate_consultation_narrative
from app.services.ai_providers import PROVIDER_CODES, NarrativeProviderError
from app.services.catalog_admin import (
    CatalogDuplicateError,
    CatalogValidationError,
    create_admission_round,
    create_admission_track,
    create_campus,
    create_institution,
    create_program,
)
from app.services.consultation_forms import (
    CONSULTATION_FORM_FIELDS,
    ConsultationFormResult,
    parse_consultation_form,
)
from app.services.consultations import (
    BatchConsultationItem,
    BatchConsultationRequest,
    BatchConsultationResult,
    ConsultationError,
    ConsultationItemStatus,
    ConsultationProgram,
    ConsultationResult,
    list_consultation_programs,
    run_batch_consultation,
    run_consultation,
)
from app.services.public_student_profiles import student_profile_from_facts
from app.services.rule_admin import (
    RULE_CONTRACT_SCHEMA_VERSION,
    HumanApproval,
    RuleAdministrationError,
    RuleExtractionEvidence,
    RuleTestEvidence,
    RuleVerificationEvidence,
    clone_published_rule_as_draft,
    compare_rule_payloads,
    human_approve_tested_rule,
    mark_rule_extracted,
    mark_rule_tested,
    publish_human_approved_rule,
    rule_contract_digest,
    rule_model_for_type,
    rule_payload_digest,
    verify_extracted_rule,
)
from app.services.score_inputs import load_academic_record_inputs
from app.services.score_rule_csv_drafts import (
    ScoreRuleDraftPersistenceError,
    load_managed_score_rules,
    managed_score_rule_from_record,
    persist_score_rule_drafts,
    update_score_rule_draft,
)
from app.services.score_rule_csv_preview import (
    DraftSelectionError,
    ScoreRuleCsvPreview,
    build_score_rule_csv_preview,
    prepare_selected_score_rule_drafts,
)
from app.services.score_rule_schema import (
    BOOLEAN_FIELDS,
    SCORE_RULE_CSV_HEADERS,
    parse_score_rule_form,
    score_rule_form_values,
    write_score_rule_csv,
)
from app.services.student_record_access import can_read_academic_record
from app.services.temporary_uploads import TemporaryUploadStore
from app.services.verified_source_rules import (
    VerifiedSourceRuleError,
    confirm_verified_source_rule,
    confirmed_verified_source_rule,
    load_verified_source_rules,
)

bp = Blueprint("admin", __name__, url_prefix="/admin")

RULE_TYPE_LABELS = {
    "ADMISSION_ELIGIBILITY_RULE": "지원자격",
    "GRADE_SOURCE_SCOPE_RULE": "성적 범위",
    "SCORE_RULE": "성적 계산",
    "MULTIPLE_APPLICATION_RULE": "복수지원",
    "DISQUALIFICATION_RULE": "결격",
}

CONSULTATION_DEFAULTS = {field: "" for field in CONSULTATION_FORM_FIELDS} | {
    "academic_year": "2027",
    "home_school_type": "GENERAL",
    "final_school_type": "GENERAL",
    "graduation_status": "EXPECTED",
    "vocational_training_status": "PARTICIPATING",
    "transferred": "FALSE",
    "ged": "FALSE",
}


def _csrf_token() -> str:
    return csrf_token()


def _require_csrf() -> None:
    require_csrf()


def _private(content: str, status: int = 200) -> Response:
    response = make_response(content, status)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    return response


def _private_csv(content: bytes, filename: str) -> Response:
    response = make_response(content)
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _actor_ref() -> str:
    return actor_ref()


def _byok_actor_ref() -> str:
    user = session_user()
    if is_demo_user(user) and (user is None or user.role not in {"STUDENT", "TEACHER"}):
        abort(403)
    return byok_actor_ref()


def _upload_store() -> TemporaryUploadStore:
    return TemporaryUploadStore(str(current_app.config["TEMP_UPLOAD_ROOT"]))


def _byok_cipher() -> ByokCredentialCipher:
    master_key = current_app.config.get("BYOK_MASTER_KEY")
    if not isinstance(master_key, str):
        raise ByokCredentialError("BYOK 키 암호화 설정이 없어 공급자 키를 저장할 수 없습니다.")
    return ByokCredentialCipher(master_key)


def _csv_artifact(review_session_id: str):  # type: ignore[no-untyped-def]
    original = _upload_store().session_path(review_session_id) / "original"
    files = tuple(original.glob("*.csv")) if original.is_dir() else ()
    if len(files) != 1:
        abort(404)
    return files[0]


def _csv_preview(review_session_id: str) -> ScoreRuleCsvPreview:
    csv_path = _csv_artifact(review_session_id)
    database_session = cast(Session, db.session)
    return build_score_rule_csv_preview(
        csv_path.read_bytes(), load_managed_score_rules(database_session)
    )


@bp.route("/login", methods=["GET", "POST"])
def login() -> Any:
    return login_view()


@bp.post("/logout")
@member_required
def logout() -> Any:
    _require_csrf()
    end_user_session()
    return redirect(url_for("admin.login"))


@bp.get("/rules")
@admin_required
def rules() -> Response:
    database_session = cast(Session, db.session)
    demo_mode = is_demo_user()
    grouped: list[tuple[str, str, tuple[Any, ...]]] = []
    for rule_type, label in RULE_TYPE_LABELS.items():
        if demo_mode:
            rows: tuple[Any, ...] = ()
        else:
            model = rule_model_for_type(rule_type)
            rows = tuple(database_session.scalars(select(model).order_by(model.created_at.desc())))
        grouped.append((rule_type, label, rows))
    return _private(
        render_template(
            "admin_rules.html",
            grouped=tuple(grouped),
            csrf_token=_csrf_token(),
            actor_ref=_actor_ref(),
            demo_mode=demo_mode,
        )
    )


def _render_consultation_form(
    values: dict[str, str],
    *,
    errors: tuple[str, ...] = (),
    status: int = 200,
) -> Response:
    demo_mode = False
    try:
        academic_year = int(values.get("academic_year") or "2027")
    except ValueError:
        academic_year = 2027
    programs = list_consultation_programs(cast(Session, db.session), academic_year)
    selected_program_ids = tuple(item for item in values.get("program_ids", "").split(",") if item)
    return _private(
        render_template(
            "admin_consultation_form.html",
            values=values,
            programs=programs,
            selected_program_ids=selected_program_ids,
            errors=errors,
            csrf_token=_csrf_token(),
            actor_ref=_actor_ref(),
            demo_mode=demo_mode,
            current_user=session_user(),
        ),
        status,
    )


def _evaluate_consultation_form(
    parsed: ConsultationFormResult,
) -> ConsultationResult | BatchConsultationResult:
    if parsed.request is None:
        raise ConsultationError("상담 입력을 확인하세요.")
    records_loader = _authorized_records_loader(parsed.request.student_id)
    if isinstance(parsed.request, BatchConsultationRequest):
        return run_batch_consultation(
            cast(Session, db.session), parsed.request, records_loader=records_loader
        )
    return run_consultation(
        cast(Session, db.session), parsed.request, records_loader=records_loader
    )


def _authorized_records_loader(student_id: str) -> Callable[[], tuple]:
    user = session_user()
    database_session = cast(Session, db.session)
    if user is None:
        # 이 helper를 호출하는 route의 member_required가 검증한 기존 구성 관리자다.
        return lambda: load_academic_record_inputs(database_session, student_id)
    if user.status != "ACTIVE":
        raise ConsultationError("활성 계정의 상담 성적만 조회할 수 있습니다.")
    records = tuple(
        database_session.scalars(
            select(StudentAcademicRecord).where(StudentAcademicRecord.student_id == student_id)
        )
    )
    if user.role in {"STUDENT", "TEACHER"}:
        if not records or any(
            not can_read_academic_record(database_session, user=user, record=record)
            for record in records
        ):
            raise ConsultationError("연결되었거나 직접 관리하는 학생 성적만 사용할 수 있습니다.")
    elif user.role != "ADMIN":
        raise ConsultationError("기존 일반 회원은 저장 성적 DB 상담을 사용할 수 없습니다.")
    return lambda: load_academic_record_inputs(database_session, student_id)


def _batch_result(result: ConsultationResult | BatchConsultationResult) -> BatchConsultationResult:
    if isinstance(result, BatchConsultationResult):
        return result
    program = ConsultationProgram(
        result.target.admission_track_id,
        result.target.academic_year,
        result.target.institution_name,
        result.target.campus_name,
        result.target.program_name,
        result.target.program_code,
    )
    return BatchConsultationResult(
        result.target.academic_year,
        (program,),
        (
            BatchConsultationItem(
                program,
                result.target,
                ConsultationItemStatus.EVALUATED,
                result,
            ),
        ),
    )


def _render_consultation_result(
    parsed: ConsultationFormResult,
    result: ConsultationResult | BatchConsultationResult,
    *,
    ai_error: str | None = None,
    save_error: str | None = None,
    status: int = 200,
) -> Response:
    actor_ref = _actor_ref()
    demo_mode = is_demo_user()
    credentials = (
        ()
        if demo_mode
        else tuple(
            cast(Session, db.session).scalars(
                select(AiProviderCredential)
                .where(AiProviderCredential.actor_ref == actor_ref)
                .order_by(AiProviderCredential.provider)
            )
        )
    )
    return _private(
        render_template(
            "admin_consultation_result.html",
            result=_batch_result(result),
            values=parsed.values,
            consultation_note=parsed.consultation_note,
            csrf_token=_csrf_token(),
            actor_ref=actor_ref,
            credentials=credentials,
            ai_error=ai_error,
            save_error=save_error,
            demo_mode=demo_mode,
            current_user=session_user(),
        ),
        status,
    )


@bp.route("/consultations/new", methods=["GET", "POST"])
@roles_required("ADMIN", "MEMBER", "TEACHER", "STUDENT")
def new_consultation() -> Response:
    if is_demo_user():
        return cast(Response, redirect(url_for("main.public_calculation_input", example="1")))
    if request.method == "GET":
        values = dict(CONSULTATION_DEFAULTS)
        user = session_user()
        requested_student_id = request.args.get("student_id", "").strip()
        if requested_student_id:
            try:
                _authorized_records_loader(requested_student_id)
            except ValueError:
                abort(404)
            values["student_id"] = requested_student_id
        elif user is not None and user.role == "STUDENT":
            values["student_id"] = f"account:{user.id}"
        return _render_consultation_form(values)
    _require_csrf()
    parsed = parse_consultation_form(request.form)
    if parsed.program_ids:
        parsed.values["program_ids"] = ",".join(parsed.program_ids)
    if parsed.errors:
        return _render_consultation_form(parsed.values, errors=parsed.errors, status=400)
    try:
        result = _evaluate_consultation_form(parsed)
    except ValueError as error:
        return _render_consultation_form(parsed.values, errors=(str(error),), status=400)
    return _render_consultation_result(parsed, result)


@bp.post("/consultations/save")
@roles_required("ADMIN", "TEACHER", "STUDENT", allow_legacy=False)
def save_consultation_result() -> Response | Any:
    _require_csrf()
    parsed = parse_consultation_form(request.form)
    if parsed.program_ids:
        parsed.values["program_ids"] = ",".join(parsed.program_ids)
    if parsed.errors:
        return _render_consultation_form(parsed.values, errors=parsed.errors, status=400)
    try:
        result = _evaluate_consultation_form(parsed)
    except ValueError as error:
        return _render_consultation_form(parsed.values, errors=(str(error),), status=400)
    user = session_user()
    assert user is not None
    assert parsed.request is not None
    try:
        save_account_consultation(
            cast(Session, db.session),
            user=user,
            student_reference=parsed.values["student_id"],
            result=_batch_result(result),
            student_profile=student_profile_from_facts(parsed.request.facts),
            counselor_note=parsed.consultation_note,
        )
        db.session.commit()
    except AccountConsultationError as error:
        db.session.rollback()
        return _render_consultation_result(parsed, result, save_error=str(error), status=400)
    except IntegrityError:
        db.session.rollback()
        return _render_consultation_result(
            parsed,
            result,
            save_error="상담자료를 저장하지 못했습니다. 다시 시도하세요.",
            status=409,
        )
    return redirect(url_for("account.records", message="consultation_saved"))


@bp.get("/verified-source-rules")
@admin_required
def verified_source_rule_reviews() -> Response:
    database_session = cast(Session, db.session)
    rules = load_verified_source_rules()
    confirmations = {
        (rule.rule_id, rule.version): confirmed_verified_source_rule(database_session, rule)
        for rule in rules
    }
    return _private(
        render_template(
            "admin_verified_source_rules.html",
            rules=rules,
            confirmations=confirmations,
            csrf_token=_csrf_token(),
        )
    )


@bp.post("/verified-source-rules/<rule_id>/<rule_version>/confirm")
@admin_required
def confirm_verified_source_rule_review(rule_id: str, rule_version: str) -> Response:
    _require_csrf()
    rule = next(
        (
            item
            for item in load_verified_source_rules()
            if item.rule_id == rule_id and item.version == rule_version
        ),
        None,
    )
    if rule is None:
        abort(404)
    user = session_user()
    if user is None:
        user = cast(Session, db.session).scalar(
            select(UserAccount).where(UserAccount.actor_ref == _actor_ref())
        )
    if user is None:
        abort(409)
    try:
        confirm_verified_source_rule(cast(Session, db.session), rule=rule, actor=user)
        db.session.commit()
    except VerifiedSourceRuleError as error:
        db.session.rollback()
        return _private(str(error), 403)
    return cast(Response, redirect(url_for("admin.verified_source_rule_reviews")))


@bp.post("/consultations/ai-draft")
@member_required
@non_demo_required
def generate_ai_consultation_draft() -> Response | Any:
    _require_csrf()
    parsed = parse_consultation_form(request.form)
    if parsed.program_ids:
        parsed.values["program_ids"] = ",".join(parsed.program_ids)
    if parsed.errors:
        return _render_consultation_form(parsed.values, errors=parsed.errors, status=400)
    try:
        result = _evaluate_consultation_form(parsed)
    except ValueError as error:
        return _render_consultation_form(parsed.values, errors=(str(error),), status=400)
    provider_code = request.form.get("provider", "")
    model_name = request.form.get("model_name", "")
    try:
        adapter = provider_adapter(provider_code, model_name)
        draft = generate_consultation_narrative(
            cast(Session, db.session),
            actor_ref=_actor_ref(),
            provider_code=provider_code,
            model_name=model_name,
            result=result,
            provider=adapter,
            cipher=_byok_cipher(),
        )
        db.session.commit()
    except (AiNarrativeError, ByokCredentialError, NarrativeProviderError) as error:
        db.session.rollback()
        status = 503 if isinstance(error, ByokCredentialError) else 400
        return _render_consultation_result(parsed, result, ai_error=str(error), status=status)
    return redirect(url_for("admin.ai_draft_detail", draft_id=draft.id))


def _render_ai_settings(*, error: str | None = None, status: int = 200) -> Response:
    owner_ref = _byok_actor_ref()
    database_session = cast(Session, db.session)
    credentials = tuple(
        database_session.scalars(
            select(AiProviderCredential)
            .where(AiProviderCredential.actor_ref == owner_ref)
            .order_by(AiProviderCredential.provider)
        )
    )
    drafts = tuple(
        database_session.scalars(
            select(AiConsultationDraft)
            .where(AiConsultationDraft.actor_ref == owner_ref)
            .order_by(AiConsultationDraft.created_at.desc())
            .limit(20)
        )
    )
    try:
        _byok_cipher()
        encryption_available = True
    except ByokCredentialError:
        encryption_available = False
    return _private(
        render_template(
            "admin_ai_settings.html",
            actor_ref=_actor_ref(),
            csrf_token=_csrf_token(),
            credentials=credentials,
            drafts=drafts,
            providers=tuple(sorted(PROVIDER_CODES)),
            encryption_available=encryption_available,
            error=error,
            current_user=session_user(),
        ),
        status,
    )


@bp.get("/ai/settings")
@member_required
def ai_settings() -> Response:
    return _render_ai_settings()


@bp.post("/ai/credentials")
@member_required
def save_ai_credential() -> Response | Any:
    _require_csrf()
    try:
        save_provider_credential(
            cast(Session, db.session),
            actor_ref=_byok_actor_ref(),
            provider=request.form.get("provider", ""),
            api_key=request.form.get("api_key", ""),
            cipher=_byok_cipher(),
        )
        db.session.commit()
    except ByokCredentialError as error:
        db.session.rollback()
        status = 503 if not current_app.config.get("BYOK_MASTER_KEY") else 400
        return _render_ai_settings(error=str(error), status=status)
    return redirect(url_for("admin.ai_settings"))


@bp.post("/ai/credentials/<provider>/delete")
@member_required
def delete_ai_credential(provider: str) -> Any:
    _require_csrf()
    try:
        delete_provider_credential(
            cast(Session, db.session), actor_ref=_byok_actor_ref(), provider=provider
        )
        db.session.commit()
    except ByokCredentialError as error:
        db.session.rollback()
        return _render_ai_settings(error=str(error), status=400)
    return redirect(url_for("admin.ai_settings"))


def _owned_ai_draft(draft_id: str) -> AiConsultationDraft:
    record = cast(Session, db.session).get(AiConsultationDraft, draft_id)
    if record is None or record.actor_ref != _actor_ref():
        abort(404)
    return record


def _render_ai_draft(
    record: AiConsultationDraft,
    *,
    error: str | None = None,
    status: int = 200,
) -> Response:
    return _private(
        render_template(
            "admin_ai_draft.html",
            actor_ref=_actor_ref(),
            csrf_token=_csrf_token(),
            draft=record,
            error=error,
            current_user=session_user(),
        ),
        status,
    )


@bp.get("/ai/drafts/<draft_id>")
@member_required
@non_demo_required
def ai_draft_detail(draft_id: str) -> Response:
    return _render_ai_draft(_owned_ai_draft(draft_id))


@bp.post("/ai/drafts/<draft_id>/confirm")
@member_required
@non_demo_required
def confirm_ai_draft_route(draft_id: str) -> Response | Any:
    _require_csrf()
    record = _owned_ai_draft(draft_id)
    try:
        confirm_ai_draft(
            cast(Session, db.session),
            draft_id=record.id,
            actor_ref=_actor_ref(),
            teacher_text=request.form.get("teacher_text", ""),
            confirmed_at=datetime.now(UTC),
        )
        db.session.commit()
    except AiDraftError as error:
        db.session.rollback()
        record = _owned_ai_draft(draft_id)
        return _render_ai_draft(record, error=str(error), status=400)
    return redirect(url_for("admin.ai_draft_detail", draft_id=record.id))


@bp.post("/ai/drafts/<draft_id>/reject")
@member_required
@non_demo_required
def reject_ai_draft_route(draft_id: str) -> Response | Any:
    _require_csrf()
    record = _owned_ai_draft(draft_id)
    try:
        reject_ai_draft(
            cast(Session, db.session),
            draft_id=record.id,
            actor_ref=_actor_ref(),
        )
        db.session.commit()
    except AiDraftError as error:
        db.session.rollback()
        record = _owned_ai_draft(draft_id)
        return _render_ai_draft(record, error=str(error), status=400)
    return redirect(url_for("admin.ai_draft_detail", draft_id=record.id))


@bp.post("/ai/drafts/<draft_id>/delete")
@member_required
@non_demo_required
def delete_ai_draft_route(draft_id: str) -> Response | Any:
    _require_csrf()
    record = _owned_ai_draft(draft_id)
    try:
        delete_ai_draft(cast(Session, db.session), draft_id=record.id, actor_ref=_actor_ref())
        db.session.commit()
    except AiDraftError as error:
        db.session.rollback()
        return _render_ai_draft(record, error=str(error), status=400)
    return redirect(url_for("admin.ai_settings"))


@bp.post("/consultations/print/<audience>")
@member_required
def print_consultation(audience: str) -> Response:
    if audience not in {"student", "teacher"}:
        abort(404)
    _require_csrf()
    parsed = parse_consultation_form(request.form)
    if parsed.program_ids:
        parsed.values["program_ids"] = ",".join(parsed.program_ids)
    if parsed.errors:
        return _render_consultation_form(parsed.values, errors=parsed.errors, status=400)
    try:
        result = _evaluate_consultation_form(parsed)
    except ValueError as error:
        return _render_consultation_form(parsed.values, errors=(str(error),), status=400)
    return _private(
        render_template(
            "consultation_print.html",
            audience=audience,
            result=_batch_result(result),
            consultation_note=parsed.consultation_note,
            demo_mode=is_demo_user(),
        )
    )


def _render_csv_review(
    review_session_id: str | None,
    preview: ScoreRuleCsvPreview | None,
    *,
    error: str | None = None,
    status: int = 200,
) -> Response:
    return _private(
        render_template(
            "admin_rule_csv.html",
            review_session_id=review_session_id,
            preview=preview,
            error=error,
            csrf_token=_csrf_token(),
            actor_ref=_actor_ref(),
        ),
        status,
    )


def _render_score_rule_edit(
    rule: ScoreRule,
    values: dict[str, str],
    *,
    errors: tuple[str, ...] = (),
    status: int = 200,
) -> Response:
    database_session = cast(Session, db.session)
    tracks = tuple(database_session.scalars(select(AdmissionTrack).order_by(AdmissionTrack.name)))
    citations = tuple(
        database_session.scalars(
            select(SourceCitation).order_by(
                SourceCitation.source_document_id,
                SourceCitation.page_number,
            )
        )
    )
    return _private(
        render_template(
            "admin_score_rule_edit.html",
            rule=rule,
            fields=SCORE_RULE_CSV_HEADERS,
            boolean_fields=BOOLEAN_FIELDS,
            textarea_fields={"evidence_location", "change_reason", "administrator_note"},
            values=values,
            tracks=tracks,
            citations=citations,
            errors=errors,
            csrf_token=_csrf_token(),
            actor_ref=_actor_ref(),
        ),
        status,
    )


@bp.route("/rules/SCORE_RULE/<rule_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_score_rule(rule_id: str) -> Response | Any:
    database_session = cast(Session, db.session)
    rule = database_session.get(ScoreRule, rule_id)
    if rule is None:
        abort(404)
    if rule.lifecycle_status != "DRAFT":
        abort(409)
    try:
        current = managed_score_rule_from_record(rule)
    except ScoreRuleDraftPersistenceError as error:
        return _private(str(error), 409)
    if request.method == "GET":
        return _render_score_rule_edit(rule, score_rule_form_values(current))

    _require_csrf()
    values = {header: request.form.get(header, "") for header in SCORE_RULE_CSV_HEADERS}
    parsed = parse_score_rule_form(values)
    if parsed.issues or len(parsed.rows) != 1:
        messages = tuple(issue.message for issue in parsed.issues) or (
            "규칙 입력을 canonical schema로 변환할 수 없습니다.",
        )
        return _render_score_rule_edit(rule, values, errors=messages, status=400)
    try:
        update_score_rule_draft(
            database_session,
            rule_id=rule.id,
            managed=parsed.rows[0],
            admission_track_id=request.form.get("admission_track_id") or None,
            source_citation_id=request.form.get("source_citation_id") or None,
            actor_ref=_actor_ref(),
            occurred_at=datetime.now(UTC),
        )
        db.session.commit()
    except ScoreRuleDraftPersistenceError as error:
        db.session.rollback()
        rule = database_session.get(ScoreRule, rule_id)
        assert rule is not None
        return _render_score_rule_edit(rule, values, errors=(str(error),), status=400)
    return redirect(url_for("admin.rule_detail", rule_type="SCORE_RULE", rule_id=rule.id))


@bp.route("/rules/csv", methods=["GET", "POST"])
@admin_required
def rule_csv() -> Response:
    if request.method == "GET":
        return _render_csv_review(None, None)
    _require_csrf()
    upload = request.files.get("score_rules_csv")
    if upload is None or not upload.filename:
        return _render_csv_review(None, None, error="CSV 파일을 선택하세요.", status=400)
    review_session_id = _upload_store().create_session()
    try:
        _upload_store().write_artifact(
            review_session_id,
            upload.read(),
            kind="original",
            suffix=".csv",
        )
        preview = _csv_preview(review_session_id)
    except (ValueError, OSError, ScoreRuleDraftPersistenceError) as error:
        _upload_store().purge_session(review_session_id)
        return _render_csv_review(None, None, error=str(error), status=400)
    return _render_csv_review(review_session_id, preview)


@bp.get("/rules/csv/export")
@admin_required
def export_rule_csv() -> Response:
    rows = load_managed_score_rules(cast(Session, db.session))
    return _private_csv(write_score_rule_csv(rows), "score_rules.csv")


@bp.post("/rules/csv/<review_session_id>/confirm")
@admin_required
def confirm_rule_csv(review_session_id: str) -> Any:
    _require_csrf()
    try:
        preview = _csv_preview(review_session_id)
        selected_rows = tuple(int(value) for value in request.form.getlist("selected_row"))
        selected_keys = tuple(
            item.rule.identity.key for item in preview.items if item.row_number in selected_rows
        )
        if len(selected_keys) != len(selected_rows):
            raise DraftSelectionError("선택한 행을 현재 미리보기에서 식별할 수 없습니다.")
        candidates = prepare_selected_score_rule_drafts(preview, selected_keys)
        drafts = persist_score_rule_drafts(
            cast(Session, db.session),
            candidates=candidates,
            actor_ref=_actor_ref(),
            occurred_at=datetime.now(UTC),
        )
        db.session.commit()
        _upload_store().purge_session(review_session_id)
    except (
        DraftSelectionError,
        ScoreRuleDraftPersistenceError,
        ValueError,
        OSError,
    ) as error:
        db.session.rollback()
        try:
            preview = _csv_preview(review_session_id)
        except (FileNotFoundError, ValueError, ScoreRuleDraftPersistenceError):
            abort(404)
        return _render_csv_review(review_session_id, preview, error=str(error), status=400)
    if len(drafts) == 1:
        return redirect(
            url_for(
                "admin.rule_detail",
                rule_type="SCORE_RULE",
                rule_id=drafts[0].id,
            )
        )
    return redirect(url_for("admin.rules"))


@bp.post("/rules/csv/<review_session_id>/discard")
@admin_required
def discard_rule_csv(review_session_id: str) -> Any:
    _require_csrf()
    _csv_artifact(review_session_id)
    _upload_store().purge_session(review_session_id)
    return redirect(url_for("admin.rule_csv"))


def _rule_detail(rule_type: str, rule_id: str) -> tuple[Any, Any | None, tuple[Any, ...]]:
    if rule_type not in RULE_TYPE_LABELS:
        abort(404)
    database_session = cast(Session, db.session)
    model = rule_model_for_type(rule_type)
    rule = database_session.get(model, rule_id)
    if rule is None:
        abort(404)
    lineage = database_session.scalar(
        select(RuleVersionLineage).where(
            RuleVersionLineage.rule_type == rule_type,
            RuleVersionLineage.rule_id == rule.id,
        )
    )
    previous = None if lineage is None else database_session.get(model, lineage.supersedes_rule_id)
    changes = (
        () if previous is None else compare_rule_payloads(previous.rule_payload, rule.rule_payload)
    )
    return rule, previous, changes


@bp.get("/rules/<rule_type>/<rule_id>")
@admin_required
def rule_detail(rule_type: str, rule_id: str) -> Response:
    rule, previous, changes = _rule_detail(rule_type, rule_id)
    return _render_rule_detail(rule_type, rule, previous, changes)


def _render_rule_detail(
    rule_type: str,
    rule: Any,
    previous: Any | None,
    changes: tuple[Any, ...],
    *,
    error: str | None = None,
    status: int = 200,
) -> Response:
    database_session = db.session()
    current_contract_digest = rule_contract_digest(database_session, rule_type, rule)
    current_payload_digest = rule_payload_digest(rule.rule_payload)
    approved_independent_reviews = tuple(
        database_session.scalars(
            select(RuleReview)
            .where(
                RuleReview.rule_type == rule_type,
                RuleReview.rule_id == rule.id,
                RuleReview.review_kind == "INDEPENDENT_VERIFICATION",
                RuleReview.review_status == "APPROVED",
                RuleReview.reviewed_at.is_not(None),
                RuleReview.payload_digest == current_payload_digest,
                RuleReview.__table__.c.contract_digest == current_contract_digest,
                RuleReview.contract_schema_version == RULE_CONTRACT_SCHEMA_VERSION,
                RuleReview.reviewer_ref != _actor_ref(),
            )
            .order_by(RuleReview.reviewed_at, RuleReview.id)
        )
    )
    verified_event = database_session.scalar(
        select(RuleAuditEvent)
        .where(
            RuleAuditEvent.rule_type == rule_type,
            RuleAuditEvent.rule_id == rule.id,
            RuleAuditEvent.action == "VERIFIED",
        )
        .order_by(
            RuleAuditEvent.occurred_at.desc(),
            RuleAuditEvent.created_at.desc(),
            RuleAuditEvent.id.desc(),
        )
        .limit(1)
    )
    verified_review_id = None
    if (
        verified_event is not None
        and verified_event.after_payload_digest == current_payload_digest
        and verified_event.details.get("contract_digest") == current_contract_digest
    ):
        candidate_review_id = verified_event.details.get("independent_review_id")
        approved_review_ids = {review.id for review in approved_independent_reviews}
        if isinstance(candidate_review_id, str) and candidate_review_id in approved_review_ids:
            verified_review_id = candidate_review_id
    passed_golden_artifacts: tuple[RuleGoldenTestArtifact, ...] = ()
    if verified_review_id is not None:
        passed_golden_artifacts = tuple(
            database_session.scalars(
                select(RuleGoldenTestArtifact)
                .where(
                    RuleGoldenTestArtifact.rule_type == rule_type,
                    RuleGoldenTestArtifact.rule_id == rule.id,
                    RuleGoldenTestArtifact.independent_review_id == verified_review_id,
                    RuleGoldenTestArtifact.result_status == "PASSED",
                    func.length(func.btrim(RuleGoldenTestArtifact.suite_ref)) > 0,
                    RuleGoldenTestArtifact.payload_digest == current_payload_digest,
                    RuleGoldenTestArtifact.contract_digest == current_contract_digest,
                    RuleGoldenTestArtifact.contract_schema_version == RULE_CONTRACT_SCHEMA_VERSION,
                    RuleGoldenTestArtifact.executed_at <= datetime.now(UTC),
                )
                .order_by(
                    RuleGoldenTestArtifact.executed_at.desc(),
                    RuleGoldenTestArtifact.id.desc(),
                )
            )
        )
    return _private(
        render_template(
            "admin_rule_detail.html",
            rule_type=rule_type,
            rule_type_label=RULE_TYPE_LABELS[rule_type],
            rule=rule,
            previous=previous,
            changes=changes,
            error=error,
            csrf_token=_csrf_token(),
            actor_ref=_actor_ref(),
            approved_independent_reviews=approved_independent_reviews,
            passed_golden_artifacts=passed_golden_artifacts,
            tested_independent_review_id=verified_review_id,
        ),
        status,
    )


@bp.post("/rules/<rule_type>/<rule_id>/clone")
@admin_required
def clone_rule(rule_type: str, rule_id: str) -> Any:
    _require_csrf()
    try:
        draft = clone_published_rule_as_draft(
            cast(Session, db.session),
            rule_type=rule_type,
            source_rule_id=rule_id,
            new_version=request.form.get("new_version", ""),
            actor_ref=_actor_ref(),
            change_reason=request.form.get("change_reason", ""),
            occurred_at=datetime.now(UTC),
        )
        db.session.commit()
    except RuleAdministrationError as error:
        db.session.rollback()
        rule, previous, changes = _rule_detail(rule_type, rule_id)
        return _render_rule_detail(rule_type, rule, previous, changes, error=str(error), status=400)
    return redirect(url_for("admin.rule_detail", rule_type=rule_type, rule_id=draft.id))


@bp.post("/rules/<rule_type>/<rule_id>/approve")
@admin_required
def approve_rule(rule_type: str, rule_id: str) -> Any:
    _require_csrf()
    try:
        human_approve_tested_rule(
            cast(Session, db.session),
            rule_type=rule_type,
            rule_id=rule_id,
            approval=HumanApproval(
                actor_ref=_actor_ref(),
                approved_at=datetime.now(UTC),
                confirmation=request.form.get("confirmation", ""),
            ),
        )
        db.session.commit()
    except RuleAdministrationError as error:
        db.session.rollback()
        rule, previous, changes = _rule_detail(rule_type, rule_id)
        return _render_rule_detail(rule_type, rule, previous, changes, error=str(error), status=400)
    return redirect(url_for("admin.rule_detail", rule_type=rule_type, rule_id=rule_id))


@bp.post("/rules/<rule_type>/<rule_id>/extract")
@admin_required
def extract_rule(rule_type: str, rule_id: str) -> Any:
    _require_csrf()
    try:
        mark_rule_extracted(
            cast(Session, db.session),
            rule_type=rule_type,
            rule_id=rule_id,
            evidence=RuleExtractionEvidence(
                actor_ref=_actor_ref(),
                extracted_at=datetime.now(UTC),
                confirmation=request.form.get("confirmation", ""),
            ),
        )
        db.session.commit()
    except RuleAdministrationError as error:
        db.session.rollback()
        rule, previous, changes = _rule_detail(rule_type, rule_id)
        return _render_rule_detail(rule_type, rule, previous, changes, error=str(error), status=400)
    return redirect(url_for("admin.rule_detail", rule_type=rule_type, rule_id=rule_id))


@bp.post("/rules/<rule_type>/<rule_id>/verify")
@admin_required
def verify_rule(rule_type: str, rule_id: str) -> Any:
    _require_csrf()
    try:
        verify_extracted_rule(
            cast(Session, db.session),
            rule_type=rule_type,
            rule_id=rule_id,
            evidence=RuleVerificationEvidence(
                actor_ref=_actor_ref(),
                verified_at=datetime.now(UTC),
                confirmation=request.form.get("confirmation", ""),
                independent_review_id=request.form.get("independent_review_id", ""),
            ),
        )
        db.session.commit()
    except RuleAdministrationError as error:
        db.session.rollback()
        rule, previous, changes = _rule_detail(rule_type, rule_id)
        return _render_rule_detail(rule_type, rule, previous, changes, error=str(error), status=400)
    return redirect(url_for("admin.rule_detail", rule_type=rule_type, rule_id=rule_id))


@bp.post("/rules/<rule_type>/<rule_id>/test")
@admin_required
def test_rule(rule_type: str, rule_id: str) -> Any:
    _require_csrf()
    try:
        mark_rule_tested(
            cast(Session, db.session),
            rule_type=rule_type,
            rule_id=rule_id,
            evidence=RuleTestEvidence(
                actor_ref=_actor_ref(),
                tested_at=datetime.now(UTC),
                confirmation=request.form.get("confirmation", ""),
                golden_test_ref=request.form.get("golden_test_ref", ""),
                independent_review_id=request.form.get("independent_review_id", ""),
            ),
        )
        db.session.commit()
    except RuleAdministrationError as error:
        db.session.rollback()
        rule, previous, changes = _rule_detail(rule_type, rule_id)
        return _render_rule_detail(rule_type, rule, previous, changes, error=str(error), status=400)
    return redirect(url_for("admin.rule_detail", rule_type=rule_type, rule_id=rule_id))


@bp.post("/rules/<rule_type>/<rule_id>/publish")
@admin_required
def publish_rule(rule_type: str, rule_id: str) -> Any:
    _require_csrf()
    try:
        publish_human_approved_rule(
            cast(Session, db.session),
            rule_type=rule_type,
            rule_id=rule_id,
            actor_ref=_actor_ref(),
            occurred_at=datetime.now(UTC),
        )
        db.session.commit()
    except RuleAdministrationError as error:
        db.session.rollback()
        rule, previous, changes = _rule_detail(rule_type, rule_id)
        return _render_rule_detail(rule_type, rule, previous, changes, error=str(error), status=400)
    except IntegrityError:
        db.session.rollback()
        rule, previous, changes = _rule_detail(rule_type, rule_id)
        return _render_rule_detail(
            rule_type,
            rule,
            previous,
            changes,
            error="동시에 다른 규칙이 게시되었습니다. 현재 상태를 다시 확인하세요.",
            status=409,
        )
    return redirect(url_for("admin.rule_detail", rule_type=rule_type, rule_id=rule_id))


CatalogCreator = Callable[[Session, Mapping[str, str]], object]

CATALOG_CREATED_MESSAGES = {
    "institution": "대학 정보를 등록했습니다.",
    "campus": "캠퍼스 정보를 등록했습니다.",
    "program": "학과 정보를 등록했습니다.",
    "admission_round": "모집시기 정보를 등록했습니다.",
    "admission_track": "전형 정보를 등록했습니다.",
}


def _render_catalog(
    *,
    error: str | None = None,
    status: int = 200,
    form_name: str | None = None,
    form_values: Mapping[str, str] | None = None,
    load_records: bool = True,
) -> Response:
    database_session = cast(Session, db.session)
    institutions: tuple[Institution, ...]
    campuses: tuple[Campus, ...]
    programs: tuple[Program, ...]
    admission_rounds: tuple[AdmissionRound, ...]
    admission_tracks: tuple[AdmissionTrack, ...]
    if load_records:
        institutions = tuple(
            database_session.scalars(select(Institution).order_by(Institution.name, Institution.id))
        )
        campuses = tuple(
            database_session.scalars(
                select(Campus).order_by(Campus.institution_id, Campus.name, Campus.id)
            )
        )
        programs = tuple(
            database_session.scalars(
                select(Program).order_by(Program.campus_id, Program.name, Program.id)
            )
        )
        admission_rounds = tuple(
            database_session.scalars(
                select(AdmissionRound).order_by(
                    AdmissionRound.academic_year.desc(),
                    AdmissionRound.institution_id,
                    AdmissionRound.code,
                    AdmissionRound.id,
                )
            )
        )
        admission_tracks = tuple(
            database_session.scalars(
                select(AdmissionTrack).order_by(
                    AdmissionTrack.admission_round_id,
                    AdmissionTrack.program_id,
                    AdmissionTrack.code,
                    AdmissionTrack.id,
                )
            )
        )
    else:
        institutions = ()
        campuses = ()
        programs = ()
        admission_rounds = ()
        admission_tracks = ()
    return _private(
        render_template(
            "admin_catalog.html",
            institutions=institutions,
            campuses=campuses,
            programs=programs,
            admission_rounds=admission_rounds,
            admission_tracks=admission_tracks,
            institution_by_id={row.id: row for row in institutions},
            campus_by_id={row.id: row for row in campuses},
            program_by_id={row.id: row for row in programs},
            round_by_id={row.id: row for row in admission_rounds},
            csrf_token=_csrf_token(),
            actor_ref=_actor_ref(),
            message=CATALOG_CREATED_MESSAGES.get(request.args.get("created", "")),
            error=error,
            form_name=form_name,
            form_values=dict(form_values or {}),
        ),
        status,
    )


def _create_catalog_entry(kind: str, creator: CatalogCreator) -> Response:
    _require_csrf()
    database_session = cast(Session, db.session)
    try:
        creator(database_session, request.form)
        database_session.commit()
    except CatalogDuplicateError as error:
        database_session.rollback()
        return _render_catalog(
            error=str(error),
            status=409,
            form_name=kind,
            form_values=request.form,
        )
    except CatalogValidationError as error:
        database_session.rollback()
        return _render_catalog(
            error=str(error),
            status=400,
            form_name=kind,
            form_values=request.form,
        )
    except IntegrityError:
        database_session.rollback()
        return _render_catalog(
            error="같은 업무키의 기준정보가 이미 등록되어 있습니다. 현재 목록을 확인하세요.",
            status=409,
            form_name=kind,
            form_values=request.form,
        )
    except SQLAlchemyError:
        database_session.rollback()
        current_app.logger.warning("기준정보 등록 중 데이터베이스 요청을 처리할 수 없습니다.")
        return _render_catalog(
            error="데이터베이스 요청을 처리할 수 없습니다. 잠시 후 다시 시도하세요.",
            status=503,
            form_name=kind,
            load_records=False,
        )
    return make_response(redirect(url_for("admin.catalog", created=kind)))


@bp.get("/catalog")
@admin_required
def catalog() -> Response:
    return _render_catalog()


@bp.post("/catalog/institutions")
@admin_required
def add_catalog_institution() -> Response:
    return _create_catalog_entry("institution", create_institution)


@bp.post("/catalog/campuses")
@admin_required
def add_catalog_campus() -> Response:
    return _create_catalog_entry("campus", create_campus)


@bp.post("/catalog/programs")
@admin_required
def add_catalog_program() -> Response:
    return _create_catalog_entry("program", create_program)


@bp.post("/catalog/admission-rounds")
@admin_required
def add_catalog_admission_round() -> Response:
    return _create_catalog_entry("admission_round", create_admission_round)


@bp.post("/catalog/admission-tracks")
@admin_required
def add_catalog_admission_track() -> Response:
    return _create_catalog_entry("admission_track", create_admission_track)
