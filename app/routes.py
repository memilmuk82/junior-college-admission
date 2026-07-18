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

from app.auth import actor_ref, member_required, non_demo_required, session_user
from app.auth import csrf_token as auth_csrf_token
from app.database import db
from app.services.confirmed_imports import (
    ConfirmationValidationError,
    confirm_structured_import,
)
from app.services.review_forms import parse_review_submission, preview_values
from app.services.review_state import ReviewState, ReviewStateError, ReviewStateStore
from app.services.temporary_uploads import TemporaryUploadStore

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


def _upload_store() -> TemporaryUploadStore:
    return TemporaryUploadStore(str(current_app.config["TEMP_UPLOAD_ROOT"]))


def _review_state(review_session_id: str) -> ReviewState:
    try:
        state = ReviewStateStore(_upload_store()).load(review_session_id)
    except (FileNotFoundError, ReviewStateError, ValueError):
        abort(404)
    if state.owner_actor_ref != actor_ref():
        abort(404)
    return state


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
    response = render_template(
        "review.html",
        review_session_id=review_session_id,
        preview=state.preview,
        values=values,
        selected_indices=set(selected_indices),
        field_errors=field_errors or {},
        blocking_errors=blocking_errors,
        csrf_token=_csrf_token(),
        source_format_label=SOURCE_FORMAT_LABELS[state.preview.source_format],
        requires_ocr_review=any(
            issue.code == "OCR_REVIEW_REQUIRED" for issue in state.preview.issues
        ),
    )
    return _private_response(response, status_code)


@bp.get("/")
def index() -> Response:
    return _private_response(
        render_template(
            "index.html",
            current_user=session_user(),
            csrf_token=auth_csrf_token(),
        )
    )


@bp.get("/health")
def health():
    return jsonify(service="junior-college-admission", status="ok")


@bp.route("/input/review/<review_session_id>", methods=["GET", "POST"])
@member_required
@non_demo_required
def review_input(review_session_id: str):
    state = _review_state(review_session_id)
    if request.method == "GET":
        return _render_review(
            review_session_id,
            state,
            values=preview_values(state.preview),
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
@member_required
@non_demo_required
def discard_review(review_session_id: str):
    _require_csrf()
    _review_state(review_session_id)
    _upload_store().purge_session(review_session_id)
    return redirect(url_for("main.index", discarded="1"))
