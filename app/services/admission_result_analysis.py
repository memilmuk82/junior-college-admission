from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AdmissionResultPublished
from app.services.admission_results import AdmissionResultKey, HistoricalRuleReference


class PublishedAdmissionResultNotFound(LookupError):
    pass


class PublishedAdmissionResultConflict(LookupError):
    pass


@dataclass(frozen=True)
class AdmissionResultAnalysisInput:
    key: AdmissionResultKey
    publication_version: str
    applicant_count: int | None
    admitted_count: int | None
    competition_rate: Decimal | None
    highest_score: Decimal | None
    average_score: Decimal | None
    lowest_score: Decimal | None
    score_basis: str | None
    historical_rule: HistoricalRuleReference | None
    capacity: int | None = None


def load_published_admission_result_for_analysis(
    session: Session, key: AdmissionResultKey
) -> AdmissionResultAnalysisInput:
    rows = tuple(
        session.scalars(
            select(AdmissionResultPublished).where(
                AdmissionResultPublished.lifecycle_status == "PUBLISHED",
                AdmissionResultPublished.academic_year == key.academic_year,
                AdmissionResultPublished.university_code == key.university_code,
                AdmissionResultPublished.campus_code == key.campus_code,
                AdmissionResultPublished.admission_round == key.admission_round,
                AdmissionResultPublished.admission_track_code == key.admission_track_code,
                AdmissionResultPublished.program_code == key.program_code,
            )
        )
    )
    if not rows:
        raise PublishedAdmissionResultNotFound("게시 승인된 과거 입시결과가 없습니다.")
    if len(rows) != 1:
        raise PublishedAdmissionResultConflict("동일 업무키의 게시 입시결과가 둘 이상입니다.")
    row = rows[0]
    historical_rule = _historical_rule_reference(row)
    return AdmissionResultAnalysisInput(
        key=key,
        publication_version=row.publication_version,
        applicant_count=row.applicant_count,
        admitted_count=row.admitted_count,
        competition_rate=row.competition_rate,
        highest_score=row.highest_score,
        average_score=row.average_score,
        lowest_score=row.lowest_score,
        score_basis=row.score_basis,
        historical_rule=historical_rule,
    )


def _historical_rule_reference(
    row: AdmissionResultPublished,
) -> HistoricalRuleReference | None:
    values = (row.score_rule_id, row.score_rule_version, row.score_rule_academic_year)
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise PublishedAdmissionResultConflict("게시 결과의 과거 규칙 참조가 불완전합니다.")
    if row.score_rule_academic_year != row.academic_year:
        raise PublishedAdmissionResultConflict("게시 결과와 과거 규칙의 모집학년도가 다릅니다.")
    return HistoricalRuleReference(
        rule_id=str(row.score_rule_id),
        version=str(row.score_rule_version),
        academic_year=int(row.score_rule_academic_year),
    )


__all__ = [
    "AdmissionResultAnalysisInput",
    "PublishedAdmissionResultConflict",
    "PublishedAdmissionResultNotFound",
    "load_published_admission_result_for_analysis",
]
