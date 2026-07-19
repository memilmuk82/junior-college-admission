from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import cast

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import actor_ref, admin_required, csrf_token, require_csrf
from app.crawlers.procollege import PROCOLLEGE_COLUMNS, ProcollegeAdapter, RequestsFormTransport
from app.database import db
from app.models import AdmissionResultImportDataset, AdmissionResultImportRow
from app.services.admission_result_collection_store import persist_raw_collection
from app.services.admission_result_file_imports import (
    AdmissionResultUploadError,
    AdmissionResultUploadPreview,
    parse_admission_result_upload,
)
from app.services.admission_result_imports import (
    AdmissionResultImportError,
    DatabaseCatalogResolver,
    DuplicateAdmissionResultDataset,
    list_published_result_years,
    persist_admission_result_preview,
    publish_admission_result_dataset,
    retarget_admission_result_dataset,
)
from app.services.admission_results import (
    AdmissionResultCollectionError,
    collect_admission_result_raw,
)
from app.services.temporary_uploads import TemporaryUploadStore

bp = Blueprint(
    "admission_result_imports",
    __name__,
    url_prefix="/admin/admission-results",
)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
PAGE_SIZE = 100
ROW_STATUS_FILTERS = frozenset({"ALL", "VALID", "REVIEW", "ERROR"})
COLUMN_LABELS = {
    "result_academic_year": "결과 학년도",
    "region": "지역",
    "institution_name": "대학명",
    "campus_name": "캠퍼스명",
    "admission_round_name": "모집시기",
    "program_name": "학과·전공",
    "day_night": "주야",
    "admission_category": "전형구분",
    "admission_track_name": "전형명·출신교",
    "capacity": "모집인원",
    "applicant_count": "지원자수",
    "admitted_count": "합격자수",
    "competition_rate": "경쟁률",
    "best_score": "최고 성적",
    "average_score": "평균 성적",
    "cutoff_score": "최저·컷 성적",
    "score_basis": "점수 기준",
    "score_direction": "점수 방향",
    "source_reference": "행별 출처",
}


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


@bp.get("")
@admin_required
def index() -> Response:
    datasets = tuple(
        cast(Session, db.session).scalars(
            select(AdmissionResultImportDataset).order_by(
                AdmissionResultImportDataset.created_at.desc()
            )
        )
    )
    return _render_index(datasets=datasets)


@bp.post("")
@admin_required
def upload() -> Response:
    require_csrf()
    upload_file = request.files.get("result_file")
    if upload_file is None or not upload_file.filename:
        return _render_index(error="CSV 또는 XLSX 파일을 선택하세요.", status=400)
    source = upload_file.stream.read(MAX_UPLOAD_BYTES + 1)
    temporary_session_id: str | None = None
    try:
        result_year = int(request.form.get("result_academic_year", ""))
        target_text = request.form.get("target_academic_year", "").strip()
        target_year = int(target_text) if target_text else None
        database_session = cast(Session, db.session)
        preview = parse_admission_result_upload(
            source,
            filename=upload_file.filename,
            result_academic_year=result_year,
            target_academic_year=target_year,
            catalog=DatabaseCatalogResolver(database_session),
        )
        metadata = _validated_upload_metadata(
            source_code=request.form.get("source_code", ""),
            source_dataset_version=request.form.get("source_dataset_version", ""),
            source_reference=request.form.get("source_reference", ""),
            result_academic_year=result_year,
            target_academic_year=preview.target_academic_year,
            suffix=Path(upload_file.filename).suffix.lower(),
        )
        store = _upload_store()
        store.purge_expired_sessions()
        temporary_session_id = store.create_session()
        store.write_artifact(
            temporary_session_id,
            source,
            kind="original",
            suffix=metadata["suffix"],
        )
        store.write_artifact(
            temporary_session_id,
            json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
            kind="derived",
            suffix=".json",
        )
        return _render_mapping_preview(temporary_session_id, preview)
    except (OSError, ValueError, AdmissionResultUploadError, AdmissionResultImportError) as error:
        db.session.rollback()
        if temporary_session_id is not None:
            _upload_store().purge_session(temporary_session_id)
        return _render_index(error=str(error), status=400)


@bp.post("/collect/procollege")
@admin_required
def collect_procollege() -> Response:
    require_csrf()
    temporary_session_id: str | None = None
    try:
        result_year = int(request.form.get("result_academic_year", ""))
        target_year = int(request.form.get("target_academic_year", ""))
        page_count = int(request.form.get("page_count", ""))
        if target_year != result_year + 1:
            raise ValueError("포털 결과의 상담 대상연도는 결과연도 + 1로 확인하세요.")
        adapter = ProcollegeAdapter(page_count=page_count)
        collection = collect_admission_result_raw(
            adapter, RequestsFormTransport(), academic_year=result_year
        )
        if collection.row_count <= 0:
            raise AdmissionResultCollectionError("포털에서 수집된 결과 행이 없습니다.")
        csv_buffer = StringIO()
        fieldnames = ("모집학년도", *PROCOLLEGE_COLUMNS)
        writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
        writer.writeheader()
        for page in collection.pages:
            for raw_row in page.rows:
                writer.writerow(raw_row.as_dict())
        source = csv_buffer.getvalue().encode("utf-8-sig")
        preview = parse_admission_result_upload(
            source,
            filename="procollege-results.csv",
            result_academic_year=result_year,
            target_academic_year=target_year,
            catalog=DatabaseCatalogResolver(cast(Session, db.session)),
        )
        raw_batch = persist_raw_collection(cast(Session, db.session), collection)
        metadata = _validated_upload_metadata(
            source_code=adapter.source_code,
            source_dataset_version=f"{result_year}-{collection.collection_digest[:12]}",
            source_reference=(
                f"전문대학포털 공개 입시결과 · raw_batch:{raw_batch.id} · "
                "https://www.procollege.kr/web/entrance/webEntrancePreResult.do"
            ),
            result_academic_year=result_year,
            target_academic_year=target_year,
            suffix=".csv",
        )
        store = _upload_store()
        store.purge_expired_sessions()
        temporary_session_id = store.create_session()
        store.write_artifact(temporary_session_id, source, kind="original", suffix=".csv")
        store.write_artifact(
            temporary_session_id,
            json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
            kind="derived",
            suffix=".json",
        )
        db.session.commit()
        return _render_mapping_preview(temporary_session_id, preview)
    except (
        AdmissionResultCollectionError,
        AdmissionResultUploadError,
        AdmissionResultImportError,
        OSError,
        ValueError,
    ) as error:
        db.session.rollback()
        if temporary_session_id is not None:
            _upload_store().purge_session(temporary_session_id)
        datasets = tuple(
            cast(Session, db.session).scalars(
                select(AdmissionResultImportDataset).order_by(
                    AdmissionResultImportDataset.created_at.desc()
                )
            )
        )
        return _render_index(datasets=datasets, error=str(error), status=400)
    except IntegrityError:
        db.session.rollback()
        if temporary_session_id is not None:
            _upload_store().purge_session(temporary_session_id)
        return _render_index(error="동일한 포털 raw 수집본이 이미 등록되어 있습니다.", status=409)


@bp.post("/preview")
@admin_required
def confirm_mapping() -> Response:
    require_csrf()
    temporary_session_id = request.form.get("temporary_session_id", "")
    try:
        store = _upload_store()
        source, metadata = _temporary_import_payload(store, temporary_session_id)
        overrides = {
            canonical: value.strip()
            for canonical in COLUMN_LABELS
            if (value := request.form.get(f"mapping__{canonical}", "")).strip()
        }
        database_session = cast(Session, db.session)
        preview = parse_admission_result_upload(
            source,
            filename=f"upload{metadata['suffix']}",
            result_academic_year=int(metadata["result_academic_year"]),
            target_academic_year=int(metadata["target_academic_year"]),
            catalog=DatabaseCatalogResolver(database_session),
            column_overrides=overrides,
        )
        dataset = persist_admission_result_preview(
            database_session,
            preview,
            source_code=metadata["source_code"],
            source_dataset_version=metadata["source_dataset_version"],
            source_reference=metadata["source_reference"],
            collected_at=datetime.now(UTC),
            column_mapping_overrides=overrides,
        )
        database_session.commit()
    except DuplicateAdmissionResultDataset as error:
        db.session.rollback()
        _upload_store().purge_session(temporary_session_id)
        return make_response(
            redirect(url_for("admission_result_imports.detail", dataset_id=error.dataset_id))
        )
    except (OSError, ValueError, AdmissionResultUploadError, AdmissionResultImportError) as error:
        db.session.rollback()
        try:
            source, metadata = _temporary_import_payload(_upload_store(), temporary_session_id)
            auto_preview = parse_admission_result_upload(
                source,
                filename=f"upload{metadata['suffix']}",
                result_academic_year=int(metadata["result_academic_year"]),
                target_academic_year=int(metadata["target_academic_year"]),
                catalog=DatabaseCatalogResolver(cast(Session, db.session)),
            )
        except (OSError, ValueError, AdmissionResultUploadError):
            return _render_index(error="임시 import 검수 세션이 만료되었습니다.", status=410)
        return _render_mapping_preview(
            temporary_session_id,
            auto_preview,
            selected_overrides={
                canonical: request.form.get(f"mapping__{canonical}", "")
                for canonical in COLUMN_LABELS
            },
            error=str(error),
            status=400,
        )
    except IntegrityError:
        db.session.rollback()
        _upload_store().purge_session(temporary_session_id)
        return _render_index(
            error="같은 데이터셋 또는 업무키가 이미 등록되어 있습니다.", status=409
        )
    _upload_store().purge_session(temporary_session_id)
    return make_response(
        redirect(url_for("admission_result_imports.detail", dataset_id=dataset.id))
    )


@bp.get("/<dataset_id>")
@admin_required
def detail(dataset_id: str) -> Response:
    database_session = cast(Session, db.session)
    dataset = database_session.get(AdmissionResultImportDataset, dataset_id)
    if dataset is None:
        abort(404)
    status_filter, page, page_count, rows = _paginated_rows(database_session, dataset.id)
    return _private(
        render_template(
            "admin_admission_result_import_detail.html",
            dataset=dataset,
            rows=rows,
            status_filter=status_filter,
            page=page,
            page_count=page_count,
            published_result_years=list_published_result_years(
                database_session, dataset.target_academic_year
            ),
            csrf_token=csrf_token(),
        )
    )


@bp.post("/<dataset_id>/publish")
@admin_required
def publish(dataset_id: str) -> Response:
    require_csrf()
    try:
        publish_admission_result_dataset(
            cast(Session, db.session),
            dataset_id,
            published_by=actor_ref(),
            published_at=datetime.now(UTC),
            allow_partial=request.form.get("partial_policy") == "CONFIRM_PARTIAL",
        )
        db.session.commit()
    except AdmissionResultImportError as error:
        db.session.rollback()
        database_session = cast(Session, db.session)
        dataset = database_session.get(AdmissionResultImportDataset, dataset_id)
        if dataset is None:
            abort(404)
        status_filter, page, page_count, rows = _paginated_rows(database_session, dataset.id)
        return _private(
            render_template(
                "admin_admission_result_import_detail.html",
                dataset=dataset,
                rows=rows,
                status_filter=status_filter,
                page=page,
                page_count=page_count,
                published_result_years=list_published_result_years(
                    database_session, dataset.target_academic_year
                ),
                csrf_token=csrf_token(),
                error=str(error),
            ),
            400,
        )
    except IntegrityError:
        db.session.rollback()
        return _private("동일 업무키의 다른 게시 버전과 충돌했습니다.", 409)
    return make_response(
        redirect(url_for("admission_result_imports.detail", dataset_id=dataset_id))
    )


@bp.post("/<dataset_id>/target-year")
@admin_required
def retarget(dataset_id: str) -> Response:
    require_csrf()
    try:
        target_year = int(request.form.get("target_academic_year", ""))
        retarget_admission_result_dataset(
            cast(Session, db.session),
            dataset_id,
            target_academic_year=target_year,
        )
        db.session.commit()
    except (ValueError, AdmissionResultImportError) as error:
        db.session.rollback()
        return _private(str(error), 400)
    return make_response(
        redirect(url_for("admission_result_imports.detail", dataset_id=dataset_id))
    )


def _paginated_rows(
    session: Session, dataset_id: str
) -> tuple[str, int, int, tuple[AdmissionResultImportRow, ...]]:
    status_filter = request.args.get("status", "ALL").upper()
    if status_filter not in ROW_STATUS_FILTERS:
        abort(400)
    try:
        page = int(request.args.get("page", "1"))
    except ValueError:
        abort(400)
    if page <= 0:
        abort(400)
    filters = [AdmissionResultImportRow.dataset_id == dataset_id]
    if status_filter != "ALL":
        filters.append(AdmissionResultImportRow.validation_status == status_filter)
    row_count = int(
        session.scalar(select(func.count()).select_from(AdmissionResultImportRow).where(*filters))
        or 0
    )
    page_count = max(1, (row_count + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > page_count:
        abort(404)
    rows = tuple(
        session.scalars(
            select(AdmissionResultImportRow)
            .where(*filters)
            .order_by(
                AdmissionResultImportRow.source_sheet,
                AdmissionResultImportRow.source_row_number,
            )
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )
    )
    return status_filter, page, page_count, rows


def _render_index(
    *,
    datasets: tuple[AdmissionResultImportDataset, ...] = (),
    error: str | None = None,
    status: int = 200,
) -> Response:
    return _private(
        render_template(
            "admin_admission_result_import.html",
            datasets=datasets,
            error=error,
            csrf_token=csrf_token(),
        ),
        status,
    )


def _upload_store() -> TemporaryUploadStore:
    return TemporaryUploadStore(str(current_app.config["TEMP_UPLOAD_ROOT"]))


def _validated_upload_metadata(
    *,
    source_code: str,
    source_dataset_version: str,
    source_reference: str,
    result_academic_year: int,
    target_academic_year: int,
    suffix: str,
) -> dict[str, str]:
    values = {
        "source_code": source_code.strip(),
        "source_dataset_version": source_dataset_version.strip(),
        "source_reference": source_reference.strip(),
        "result_academic_year": str(result_academic_year),
        "target_academic_year": str(target_academic_year),
        "suffix": suffix,
    }
    required = ("source_code", "source_dataset_version", "source_reference")
    if not all(values[key] for key in required):
        raise AdmissionResultImportError("출처 코드·데이터셋 버전·출처 설명이 필요합니다.")
    if suffix not in {".csv", ".xlsx"}:
        raise AdmissionResultUploadError("입시결과 파일은 CSV 또는 XLSX만 지원합니다.")
    return values


def _temporary_import_payload(
    store: TemporaryUploadStore, temporary_session_id: str
) -> tuple[bytes, dict[str, str]]:
    session_path = store.session_path(temporary_session_id)
    originals = tuple((session_path / "original").glob("*"))
    metadata_files = tuple((session_path / "derived").glob("*.json"))
    if len(originals) != 1 or len(metadata_files) != 1:
        raise AdmissionResultUploadError("임시 import 검수 세션이 유효하지 않습니다.")
    payload: object = json.loads(metadata_files[0].read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in payload.items()
    ):
        raise AdmissionResultUploadError("임시 import 검수 정보가 유효하지 않습니다.")
    metadata = cast(dict[str, str], payload)
    validated = _validated_upload_metadata(
        source_code=metadata.get("source_code", ""),
        source_dataset_version=metadata.get("source_dataset_version", ""),
        source_reference=metadata.get("source_reference", ""),
        result_academic_year=int(metadata.get("result_academic_year", "")),
        target_academic_year=int(metadata.get("target_academic_year", "")),
        suffix=metadata.get("suffix", ""),
    )
    return originals[0].read_bytes(), validated


def _render_mapping_preview(
    temporary_session_id: str,
    preview: AdmissionResultUploadPreview,
    *,
    selected_overrides: dict[str, str] | None = None,
    error: str | None = None,
    status: int = 200,
) -> Response:
    return _private(
        render_template(
            "admin_admission_result_mapping.html",
            temporary_session_id=temporary_session_id,
            preview=preview,
            automatic_mapping=dict(preview.column_mapping),
            available_source_columns=preview.available_source_columns,
            column_labels=COLUMN_LABELS,
            selected_overrides=selected_overrides or {},
            csrf_token=csrf_token(),
            error=error,
        ),
        status,
    )


__all__ = ["bp"]
