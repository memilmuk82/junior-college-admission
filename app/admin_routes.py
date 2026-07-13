from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
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
    session,
    url_for,
)
from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash

from app.database import db
from app.models import AdmissionTrack, RuleVersionLineage, ScoreRule, SourceCitation
from app.services.consultation_forms import (
    CONSULTATION_FORM_FIELDS,
    ConsultationFormResult,
    parse_consultation_form,
)
from app.services.consultations import (
    ConsultationError,
    ConsultationResult,
    list_consultation_targets,
    run_consultation,
)
from app.services.rule_admin import (
    HumanApproval,
    RuleAdministrationError,
    clone_published_rule_as_draft,
    compare_rule_payloads,
    human_approve_tested_rule,
    publish_human_approved_rule,
    rule_model_for_type,
)
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
from app.services.temporary_uploads import TemporaryUploadStore

bp = Blueprint("admin", __name__, url_prefix="/admin")

RULE_TYPE_LABELS = {
    "ADMISSION_ELIGIBILITY_RULE": "지원자격",
    "GRADE_SOURCE_SCOPE_RULE": "성적 범위",
    "SCORE_RULE": "성적 계산",
    "MULTIPLE_APPLICATION_RULE": "복수지원",
    "DISQUALIFICATION_RULE": "결격",
}

CONSULTATION_DEFAULTS = {field: "" for field in CONSULTATION_FORM_FIELDS} | {
    "home_school_type": "GENERAL",
    "final_school_type": "GENERAL",
    "graduation_status": "EXPECTED",
    "vocational_training_status": "PARTICIPATING",
    "transferred": "FALSE",
    "ged": "FALSE",
}


def _csrf_token() -> str:
    token = session.get("admin_csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        session["admin_csrf_token"] = token
    return token


def _require_csrf() -> None:
    expected = session.get("admin_csrf_token")
    supplied = request.form.get("csrf_token", "")
    if not isinstance(expected, str) or not hmac.compare_digest(expected, supplied):
        abort(400)


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
    actor = session.get("admin_actor_ref")
    if not isinstance(actor, str) or not actor:
        abort(401)
    return actor


def _upload_store() -> TemporaryUploadStore:
    return TemporaryUploadStore(str(current_app.config["TEMP_UPLOAD_ROOT"]))


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


def admin_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        actor = session.get("admin_actor_ref")
        if not isinstance(actor, str) or not actor:
            return redirect(url_for("admin.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@bp.route("/login", methods=["GET", "POST"])
def login() -> Any:
    error: str | None = None
    if request.method == "POST":
        _require_csrf()
        configured_user = current_app.config.get("ADMIN_USERNAME")
        password_hash = current_app.config.get("ADMIN_PASSWORD_HASH")
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        valid = (
            isinstance(configured_user, str)
            and isinstance(password_hash, str)
            and hmac.compare_digest(username, configured_user)
            and check_password_hash(password_hash, password)
        )
        if valid:
            session.clear()
            session["admin_actor_ref"] = username
            session["admin_csrf_token"] = secrets.token_urlsafe(32)
            return redirect(url_for("admin.rules"))
        error = "관리자 인증 정보를 확인하세요."
    return _private(
        render_template("admin_login.html", csrf_token=_csrf_token(), error=error),
        401 if error else 200,
    )


@bp.post("/logout")
@admin_required
def logout() -> Any:
    _require_csrf()
    session.clear()
    return redirect(url_for("admin.login"))


@bp.get("/rules")
@admin_required
def rules() -> Response:
    database_session = cast(Session, db.session)
    grouped: list[tuple[str, str, tuple[Any, ...]]] = []
    for rule_type, label in RULE_TYPE_LABELS.items():
        model = rule_model_for_type(rule_type)
        rows = tuple(database_session.scalars(select(model).order_by(model.created_at.desc())))
        grouped.append((rule_type, label, rows))
    return _private(
        render_template(
            "admin_rules.html",
            grouped=tuple(grouped),
            csrf_token=_csrf_token(),
            actor_ref=_actor_ref(),
        )
    )


def _render_consultation_form(
    values: dict[str, str],
    *,
    errors: tuple[str, ...] = (),
    status: int = 200,
) -> Response:
    targets = list_consultation_targets(cast(Session, db.session))
    return _private(
        render_template(
            "admin_consultation_form.html",
            values=values,
            targets=targets,
            errors=errors,
            csrf_token=_csrf_token(),
            actor_ref=_actor_ref(),
        ),
        status,
    )


def _evaluate_consultation_form(parsed: ConsultationFormResult) -> ConsultationResult:
    if parsed.request is None:
        raise ConsultationError("상담 입력을 확인하세요.")
    return run_consultation(cast(Session, db.session), parsed.request)


@bp.route("/consultations/new", methods=["GET", "POST"])
@admin_required
def new_consultation() -> Response:
    if request.method == "GET":
        return _render_consultation_form(dict(CONSULTATION_DEFAULTS))
    _require_csrf()
    parsed = parse_consultation_form(request.form)
    if parsed.errors:
        return _render_consultation_form(parsed.values, errors=parsed.errors, status=400)
    try:
        result = _evaluate_consultation_form(parsed)
    except ValueError as error:
        return _render_consultation_form(parsed.values, errors=(str(error),), status=400)
    return _private(
        render_template(
            "admin_consultation_result.html",
            result=result,
            values=parsed.values,
            consultation_note=parsed.consultation_note,
            csrf_token=_csrf_token(),
            actor_ref=_actor_ref(),
        )
    )


@bp.post("/consultations/print/<audience>")
@admin_required
def print_consultation(audience: str) -> Response:
    if audience not in {"student", "teacher"}:
        abort(404)
    _require_csrf()
    parsed = parse_consultation_form(request.form)
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
            result=result,
            consultation_note=parsed.consultation_note,
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
    return redirect(url_for("admin.rule_detail", rule_type=rule_type, rule_id=rule_id))
