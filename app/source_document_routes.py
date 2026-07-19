from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from flask import (
    Blueprint,
    Response,
    current_app,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import csrf_token, require_csrf, roles_required, session_user
from app.database import db
from app.models import AdmissionRound, DataValidationDecision, Institution, SourceDocument
from app.services.source_documents import (
    SourceDocumentError,
    create_validation_decision,
    register_source_document,
    resolve_validation_decision,
)

bp = Blueprint("source_admin", __name__, url_prefix="/admin/sources")


def _private(content: str, status: int = 200) -> Response:
    response = make_response(content, status)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _render_index(*, error: str | None = None, status: int = 200) -> Response:
    database_session = cast(Session, db.session)
    documents = tuple(
        database_session.scalars(
            select(SourceDocument).order_by(
                SourceDocument.academic_year.desc(),
                SourceDocument.is_current.desc(),
                SourceDocument.created_at.desc(),
            )
        )
    )
    decisions = tuple(
        database_session.scalars(
            select(DataValidationDecision).order_by(
                DataValidationDecision.resolution_status,
                DataValidationDecision.created_at.desc(),
            )
        )
    )
    institutions = tuple(database_session.scalars(select(Institution).order_by(Institution.name)))
    rounds = tuple(
        database_session.scalars(
            select(AdmissionRound)
            .where(AdmissionRound.academic_year == 2027)
            .order_by(AdmissionRound.name)
        )
    )
    return _private(
        render_template(
            "admin_source_documents.html",
            csrf_token=csrf_token(),
            documents=documents,
            decisions=decisions,
            institutions=institutions,
            rounds=rounds,
            error=error,
        ),
        status,
    )


@bp.get("")
@roles_required("ADMIN", allow_legacy=False)
def index() -> Response:
    return _render_index()


@bp.post("/upload")
@roles_required("ADMIN", allow_legacy=False)
def upload() -> Response | Any:
    require_csrf()
    uploaded = request.files.get("source_file")
    if uploaded is None or not uploaded.filename:
        return _render_index(error="출처 파일을 선택하세요.", status=400)
    body = uploaded.read(100 * 1024 * 1024 + 1)
    try:
        register_source_document(
            cast(Session, db.session),
            storage_root=Path(current_app.config["TEMP_UPLOAD_ROOT"]),
            filename=uploaded.filename,
            body=body,
            academic_year=request.form.get("academic_year", ""),
            document_type=request.form.get("document_type", ""),
            institution_id=request.form.get("institution_id", ""),
            admission_round_id=request.form.get("admission_round_id", ""),
            original_url=request.form.get("original_url", ""),
            announced_at=request.form.get("announced_at", ""),
            revision_label=request.form.get("revision_label", ""),
        )
        db.session.commit()
    except SourceDocumentError as error:
        db.session.rollback()
        return _render_index(error=str(error), status=400)
    except IntegrityError:
        db.session.rollback()
        return _render_index(error="출처 메타데이터가 기존 자료와 충돌합니다.", status=409)
    return redirect(url_for("source_admin.index"))


@bp.post("/validations")
@roles_required("ADMIN", allow_legacy=False)
def add_validation() -> Response | Any:
    require_csrf()
    try:
        create_validation_decision(
            cast(Session, db.session),
            source_document_id=request.form.get("source_document_id", ""),
            entity_type=request.form.get("entity_type", ""),
            entity_reference=request.form.get("entity_reference", ""),
            field_name=request.form.get("field_name", ""),
            current_value=request.form.get("current_value", ""),
            portal_value=request.form.get("portal_value", ""),
            document_value=request.form.get("document_value", ""),
        )
        db.session.commit()
    except SourceDocumentError as error:
        db.session.rollback()
        return _render_index(error=str(error), status=400)
    return redirect(url_for("source_admin.index"))


@bp.post("/validations/<decision_id>/resolve")
@roles_required("ADMIN", allow_legacy=False)
def resolve_validation(decision_id: str) -> Response | Any:
    require_csrf()
    user = session_user()
    assert user is not None
    try:
        resolve_validation_decision(
            cast(Session, db.session),
            decision_id=decision_id,
            user=user,
            resolution_status=request.form.get("resolution_status", ""),
            resolved_value=request.form.get("resolved_value", ""),
            resolution_reason=request.form.get("resolution_reason", ""),
        )
        db.session.commit()
    except SourceDocumentError as error:
        db.session.rollback()
        return _render_index(error=str(error), status=400)
    return redirect(url_for("source_admin.index"))


__all__ = ["bp"]
