from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from unicodedata import normalize

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    AdmissionResultImportDataset,
    AdmissionResultImportRow,
    AdmissionRound,
    AdmissionTrack,
    Campus,
    Institution,
    Program,
)
from app.services.admission_result_file_imports import (
    AdmissionResultUploadPreview,
    CatalogMatch,
)


class AdmissionResultImportError(ValueError):
    pass


class DuplicateAdmissionResultDataset(AdmissionResultImportError):
    def __init__(self, dataset_id: str) -> None:
        super().__init__("같은 SHA-256의 입시결과 데이터셋이 이미 등록되어 있습니다.")
        self.dataset_id = dataset_id


@dataclass(frozen=True)
class PublishedImportedAdmissionResult:
    dataset_id: str
    publication_version: str
    result_academic_year: int
    target_academic_year: int
    institution_code: str
    campus_code: str
    program_code: str
    admission_round_code: str
    admission_track_code: str
    capacity: int | None
    applicant_count: int | None
    admitted_count: int | None
    competition_rate: Decimal | None
    best_score: Decimal | None
    average_score: Decimal | None
    cutoff_score: Decimal | None
    score_basis: str
    score_direction: str
    historical_score_rule_id: str | None
    historical_score_rule_version: str | None
    historical_score_rule_year: int | None
    source_reference: str


class DatabaseCatalogResolver:
    """현재 DB의 명시적 기준정보만 exact-normalized 방식으로 연결한다."""

    def __init__(self, session: Session) -> None:
        institutions = tuple(session.scalars(select(Institution)))
        campuses = tuple(session.scalars(select(Campus)))
        programs = tuple(session.scalars(select(Program)))
        rounds = tuple(session.scalars(select(AdmissionRound)))
        tracks = tuple(session.scalars(select(AdmissionTrack)))
        self._institutions = {_key(row.name): row for row in institutions}
        self._campuses_by_institution: dict[str, list[Campus]] = {}
        for campus_row in campuses:
            self._campuses_by_institution.setdefault(campus_row.institution_id, []).append(
                campus_row
            )
        self._programs_by_campus: dict[str, list[Program]] = {}
        for program_row in programs:
            self._programs_by_campus.setdefault(program_row.campus_id, []).append(program_row)
        self._rounds_by_institution: dict[str, list[AdmissionRound]] = {}
        for round_row in rounds:
            self._rounds_by_institution.setdefault(round_row.institution_id, []).append(round_row)
        self._tracks_by_round_program: dict[tuple[str, str], list[AdmissionTrack]] = {}
        for track_row in tracks:
            self._tracks_by_round_program.setdefault(
                (track_row.admission_round_id, track_row.program_id), []
            ).append(track_row)

    def resolve(
        self,
        *,
        institution_name: str,
        campus_name: str | None,
        program_name: str,
        admission_round_name: str,
        admission_track_name: str,
        target_academic_year: int,
    ) -> CatalogMatch | None:
        institution = self._institutions.get(_key(institution_name))
        if institution is None or not institution.code:
            return None
        campuses = self._campuses_by_institution.get(institution.id, [])
        campus_matches = (
            [row for row in campuses if _key(row.name) == _key(campus_name)]
            if campus_name
            else campuses
        )
        campus = campus_matches[0] if len(campus_matches) == 1 else None
        if campus is None or not campus.code:
            return None
        program_matches = [
            row
            for row in self._programs_by_campus.get(campus.id, [])
            if _key(row.name) == _key(program_name)
        ]
        program = program_matches[0] if len(program_matches) == 1 else None
        if program is None or not program.code:
            return None
        rounds = [
            row
            for row in self._rounds_by_institution.get(institution.id, [])
            if row.academic_year == target_academic_year
            and _key(row.name) == _key(admission_round_name)
        ]
        admission_round = rounds[0] if len(rounds) == 1 else None
        if admission_round is None:
            return None
        tracks = [
            row
            for row in self._tracks_by_round_program.get((admission_round.id, program.id), [])
            if _key(row.name) == _key(admission_track_name)
        ]
        track = tracks[0] if len(tracks) == 1 else None
        if track is None:
            return None
        return CatalogMatch(
            institution_code=institution.code,
            campus_code=campus.code,
            program_code=program.code,
            admission_round_code=admission_round.code,
            admission_track_code=track.code,
            campus_name=campus.name,
        )


def retarget_admission_result_dataset(
    session: Session,
    dataset_id: str,
    *,
    target_academic_year: int,
) -> AdmissionResultImportDataset:
    dataset = session.get(AdmissionResultImportDataset, dataset_id)
    if dataset is None:
        raise AdmissionResultImportError("입시결과 데이터셋을 찾을 수 없습니다.")
    if dataset.lifecycle_status in {"PUBLISHED", "SUPERSEDED"}:
        raise AdmissionResultImportError("게시된 데이터셋의 상담 대상연도는 변경할 수 없습니다.")
    if not 2000 <= target_academic_year <= 2100:
        raise AdmissionResultImportError("상담 대상 학년도가 유효하지 않습니다.")
    resolver = DatabaseCatalogResolver(session)
    rows = tuple(
        session.scalars(
            select(AdmissionResultImportRow).where(
                AdmissionResultImportRow.dataset_id == dataset.id
            )
        )
    )
    for row in rows:
        issues = [
            issue
            for issue in row.validation_issues
            if issue.get("code") not in {"CATALOG_MAPPING_REQUIRED", "DUPLICATE_BUSINESS_KEY"}
        ]
        match = resolver.resolve(
            institution_name=row.institution_name,
            campus_name=row.campus_name,
            program_name=row.program_name,
            admission_round_name=row.admission_round_name,
            admission_track_name=row.admission_track_name,
            target_academic_year=target_academic_year,
        )
        row.target_academic_year = target_academic_year
        if match is None:
            row.institution_code = None
            row.campus_code = None
            row.program_code = None
            row.admission_round_code = None
            row.admission_track_code = None
            issues.append(
                {
                    "code": "CATALOG_MAPPING_REQUIRED",
                    "message": (
                        "대학·캠퍼스·학과·모집시기·전형 업무키를 관리자 검수로 연결해야 합니다."
                    ),
                }
            )
        else:
            row.institution_code = match.institution_code
            row.campus_code = match.campus_code
            row.campus_name = match.campus_name
            row.program_code = match.program_code
            row.admission_round_code = match.admission_round_code
            row.admission_track_code = match.admission_track_code
        row.validation_issues = issues
        row.validation_status = _status_for_issue_payloads(issues)

    duplicate_groups: dict[tuple[object, ...], list[AdmissionResultImportRow]] = {}
    for row in rows:
        key = _row_business_key(row)
        if key is not None:
            duplicate_groups.setdefault(key, []).append(row)
    for duplicate_rows in duplicate_groups.values():
        if len(duplicate_rows) <= 1:
            continue
        for row in duplicate_rows:
            row.validation_issues = row.validation_issues + [
                {
                    "code": "DUPLICATE_BUSINESS_KEY",
                    "message": "같은 canonical 업무키가 파일 안에서 중복되었습니다.",
                }
            ]
            if row.validation_status == "VALID":
                row.validation_status = "REVIEW"

    dataset.target_academic_year = target_academic_year
    dataset.valid_row_count = sum(row.validation_status == "VALID" for row in rows)
    dataset.review_row_count = sum(row.validation_status == "REVIEW" for row in rows)
    dataset.error_row_count = sum(row.validation_status == "ERROR" for row in rows)
    dataset.lifecycle_status = (
        "BLOCKED"
        if dataset.error_row_count
        else ("STAGED" if dataset.review_row_count else "READY")
    )
    return dataset


def persist_admission_result_preview(
    session: Session,
    preview: AdmissionResultUploadPreview,
    *,
    source_code: str,
    source_dataset_version: str,
    source_reference: str,
    collected_at: datetime,
    column_mapping_overrides: dict[str, str] | None = None,
) -> AdmissionResultImportDataset:
    existing = session.scalar(
        select(AdmissionResultImportDataset).where(
            AdmissionResultImportDataset.source_hash == preview.source_hash
        )
    )
    if existing is not None:
        raise DuplicateAdmissionResultDataset(existing.id)
    if (
        not source_code.strip()
        or not source_dataset_version.strip()
        or not source_reference.strip()
    ):
        raise AdmissionResultImportError("출처 코드·데이터셋 버전·출처 설명이 필요합니다.")
    if collected_at.tzinfo is None:
        raise AdmissionResultImportError("수집 시각에는 timezone이 필요합니다.")

    status = (
        "BLOCKED"
        if preview.error_row_count
        else ("STAGED" if preview.review_row_count else "READY")
    )
    dataset = AdmissionResultImportDataset(
        source_code=source_code.strip(),
        source_dataset_version=source_dataset_version.strip(),
        source_hash=preview.source_hash,
        source_format=preview.source_format,
        result_academic_year=preview.result_academic_year,
        target_academic_year=preview.target_academic_year,
        lifecycle_status=status,
        original_row_count=preview.total_row_count,
        valid_row_count=preview.valid_row_count,
        review_row_count=preview.review_row_count,
        error_row_count=preview.error_row_count,
        published_row_count=0,
        detected_sheets=list(preview.detected_sheets),
        column_mapping=dict(preview.column_mapping),
        column_mapping_overrides=dict(column_mapping_overrides or {}),
        source_reference=source_reference.strip(),
        collected_at=collected_at,
    )
    session.add(dataset)
    session.flush()
    session.add_all(
        [
            AdmissionResultImportRow(
                dataset_id=dataset.id,
                source_row_number=row.source_row_number,
                source_sheet=row.source_sheet,
                result_academic_year=row.result_academic_year,
                target_academic_year=row.target_academic_year,
                region=row.region,
                institution_code=row.institution_code,
                institution_name=row.institution_name,
                campus_code=row.campus_code,
                campus_name=row.campus_name,
                program_code=row.program_code,
                program_name=row.program_name,
                admission_round_code=row.admission_round_code,
                admission_round_name=row.admission_round_name,
                day_night=row.day_night,
                admission_category=row.admission_category,
                admission_track_code=row.admission_track_code,
                admission_track_name=row.admission_track_name,
                capacity=row.capacity,
                applicant_count=row.applicant_count,
                admitted_count=row.admitted_count,
                competition_rate=row.competition_rate,
                best_score=row.best_score,
                average_score=row.average_score,
                cutoff_score=row.cutoff_score,
                score_basis=row.score_basis,
                score_direction=row.score_direction,
                historical_score_rule_id=row.historical_score_rule_id,
                historical_score_rule_version=row.historical_score_rule_version,
                historical_score_rule_year=row.historical_score_rule_year,
                source_reference=row.source_reference,
                validation_status=row.validation_status,
                validation_issues=[
                    {"code": issue.code, "message": issue.message} for issue in row.issues
                ],
                publication_status="STAGED",
            )
            for row in preview.rows
        ]
    )
    return dataset


def publish_admission_result_dataset(
    session: Session,
    dataset_id: str,
    *,
    published_by: str,
    published_at: datetime,
    allow_partial: bool,
) -> AdmissionResultImportDataset:
    dataset = session.get(AdmissionResultImportDataset, dataset_id)
    if dataset is None:
        raise AdmissionResultImportError("입시결과 데이터셋을 찾을 수 없습니다.")
    if dataset.lifecycle_status in {"PUBLISHED", "SUPERSEDED"}:
        raise AdmissionResultImportError("이미 게시 처리된 데이터셋입니다.")
    if not published_by.strip() or published_at.tzinfo is None:
        raise AdmissionResultImportError("게시 관리자와 timezone 포함 게시 시각이 필요합니다.")
    if dataset.valid_row_count <= 0:
        raise AdmissionResultImportError("게시 가능한 유효 행이 없습니다.")
    if (dataset.review_row_count or dataset.error_row_count) and not allow_partial:
        raise AdmissionResultImportError(
            "검토·오류 행을 제외하는 부분 게시 정책을 명시적으로 확인해야 합니다."
        )

    previous = tuple(
        session.scalars(
            select(AdmissionResultImportDataset).where(
                AdmissionResultImportDataset.id != dataset.id,
                AdmissionResultImportDataset.source_code == dataset.source_code,
                AdmissionResultImportDataset.result_academic_year == dataset.result_academic_year,
                AdmissionResultImportDataset.target_academic_year == dataset.target_academic_year,
                AdmissionResultImportDataset.lifecycle_status == "PUBLISHED",
            )
        )
    )
    if len(previous) > 1:
        raise AdmissionResultImportError("같은 연도·출처의 활성 게시 데이터셋이 둘 이상입니다.")
    if previous:
        old = previous[0]
        old.lifecycle_status = "SUPERSEDED"
        dataset.supersedes_id = old.id
        session.execute(
            update(AdmissionResultImportRow)
            .where(
                AdmissionResultImportRow.dataset_id == old.id,
                AdmissionResultImportRow.publication_status == "PUBLISHED",
            )
            .values(publication_status="SUPERSEDED")
        )
        session.flush()

    session.execute(
        update(AdmissionResultImportRow)
        .where(
            AdmissionResultImportRow.dataset_id == dataset.id,
            AdmissionResultImportRow.validation_status == "VALID",
        )
        .values(publication_status="PUBLISHED")
    )
    session.execute(
        update(AdmissionResultImportRow)
        .where(
            AdmissionResultImportRow.dataset_id == dataset.id,
            AdmissionResultImportRow.validation_status != "VALID",
        )
        .values(publication_status="EXCLUDED")
    )
    dataset.lifecycle_status = "PUBLISHED"
    dataset.published_row_count = dataset.valid_row_count
    dataset.published_by = published_by.strip()
    dataset.published_at = published_at
    return dataset


def load_published_imported_result(
    session: Session,
    *,
    target_academic_year: int,
    result_academic_year: int,
    institution_code: str,
    campus_code: str,
    program_code: str,
    admission_round_code: str,
    admission_track_code: str,
    score_basis: str = "RANK_GRADE",
) -> PublishedImportedAdmissionResult | None:
    row = session.scalar(
        select(AdmissionResultImportRow).where(
            AdmissionResultImportRow.publication_status == "PUBLISHED",
            AdmissionResultImportRow.target_academic_year == target_academic_year,
            AdmissionResultImportRow.result_academic_year == result_academic_year,
            AdmissionResultImportRow.institution_code == institution_code,
            AdmissionResultImportRow.campus_code == campus_code,
            AdmissionResultImportRow.program_code == program_code,
            AdmissionResultImportRow.admission_round_code == admission_round_code,
            AdmissionResultImportRow.admission_track_code == admission_track_code,
            AdmissionResultImportRow.score_basis == score_basis,
        )
    )
    if row is None:
        return None
    dataset = session.get(AdmissionResultImportDataset, row.dataset_id)
    if dataset is None or dataset.lifecycle_status != "PUBLISHED":
        return None
    return _published_result(dataset, row)


def list_published_imported_results_for_program(
    session: Session,
    *,
    target_academic_year: int,
    result_academic_year: int,
    institution_code: str,
    campus_code: str,
    program_code: str,
    score_basis: str = "RANK_GRADE",
) -> tuple[PublishedImportedAdmissionResult, ...]:
    pairs = tuple(
        session.execute(
            select(AdmissionResultImportDataset, AdmissionResultImportRow)
            .join(
                AdmissionResultImportRow,
                AdmissionResultImportRow.dataset_id == AdmissionResultImportDataset.id,
            )
            .where(
                AdmissionResultImportDataset.lifecycle_status == "PUBLISHED",
                AdmissionResultImportRow.publication_status == "PUBLISHED",
                AdmissionResultImportRow.target_academic_year == target_academic_year,
                AdmissionResultImportRow.result_academic_year == result_academic_year,
                AdmissionResultImportRow.institution_code == institution_code,
                AdmissionResultImportRow.campus_code == campus_code,
                AdmissionResultImportRow.program_code == program_code,
                AdmissionResultImportRow.score_basis == score_basis,
            )
            .order_by(
                AdmissionResultImportRow.admission_round_code,
                AdmissionResultImportRow.admission_track_code,
            )
        )
    )
    return tuple(_published_result(dataset, row) for dataset, row in pairs)


def _published_result(
    dataset: AdmissionResultImportDataset,
    row: AdmissionResultImportRow,
) -> PublishedImportedAdmissionResult:
    return PublishedImportedAdmissionResult(
        dataset_id=dataset.id,
        publication_version=dataset.source_dataset_version,
        result_academic_year=row.result_academic_year,
        target_academic_year=row.target_academic_year,
        institution_code=str(row.institution_code),
        campus_code=str(row.campus_code),
        program_code=str(row.program_code),
        admission_round_code=str(row.admission_round_code),
        admission_track_code=str(row.admission_track_code),
        capacity=row.capacity,
        applicant_count=row.applicant_count,
        admitted_count=row.admitted_count,
        competition_rate=row.competition_rate,
        best_score=row.best_score,
        average_score=row.average_score,
        cutoff_score=row.cutoff_score,
        score_basis=row.score_basis,
        score_direction=row.score_direction,
        historical_score_rule_id=row.historical_score_rule_id,
        historical_score_rule_version=row.historical_score_rule_version,
        historical_score_rule_year=row.historical_score_rule_year,
        source_reference=row.source_reference,
    )


def list_published_result_years(session: Session, target_academic_year: int) -> tuple[int, ...]:
    return tuple(
        session.scalars(
            select(AdmissionResultImportDataset.result_academic_year)
            .where(
                AdmissionResultImportDataset.target_academic_year == target_academic_year,
                AdmissionResultImportDataset.lifecycle_status == "PUBLISHED",
            )
            .distinct()
            .order_by(AdmissionResultImportDataset.result_academic_year.desc())
        )
    )


_ERROR_ISSUE_CODES = frozenset(
    {
        "FORMULA_NOT_ALLOWED",
        "INVALID_SCORE_BASIS",
        "INVALID_VALUE",
        "RESULT_METRIC_MISSING",
        "RESULT_YEAR_MISMATCH",
        "SCORE_DIRECTION_MISMATCH",
        "SCORE_OUT_OF_RANGE",
    }
)


def _status_for_issue_payloads(issues: list[dict[str, object]]) -> str:
    if any(issue.get("code") in _ERROR_ISSUE_CODES for issue in issues):
        return "ERROR"
    return "REVIEW" if issues else "VALID"


def _row_business_key(row: AdmissionResultImportRow) -> tuple[object, ...] | None:
    values = (
        row.target_academic_year,
        row.result_academic_year,
        row.institution_code,
        row.campus_code,
        row.program_code,
        row.admission_round_code,
        row.admission_track_code,
        row.score_basis,
    )
    return values if all(value is not None and value != "" for value in values) else None


def _key(value: str) -> str:
    return re.sub(r"\s+", "", normalize("NFKC", value)).casefold()


__all__ = [
    "AdmissionResultImportError",
    "DatabaseCatalogResolver",
    "DuplicateAdmissionResultDataset",
    "PublishedImportedAdmissionResult",
    "list_published_imported_results_for_program",
    "list_published_result_years",
    "load_published_imported_result",
    "persist_admission_result_preview",
    "publish_admission_result_dataset",
    "retarget_admission_result_dataset",
]
