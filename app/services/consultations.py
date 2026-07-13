from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AdmissionEligibilityRule,
    AdmissionRound,
    AdmissionTrack,
    Campus,
    GradeSourceScopeRule,
    Institution,
    Program,
    ScoreRule,
    SourceCitation,
    SourceDocument,
)
from app.services.admission_result_analysis import (
    AdmissionResultAnalysisInput,
    PublishedAdmissionResultConflict,
    PublishedAdmissionResultNotFound,
    load_published_admission_result_for_analysis,
)
from app.services.admission_results import AdmissionResultKey
from app.services.eligibility import EligibilityDecision, StudentFacts, evaluate_eligibility
from app.services.published_rules import (
    load_published_eligibility_rule,
    load_published_grade_source_scope_rule,
    load_published_score_rule,
    to_eligibility_rule,
)
from app.services.score_calculation import ScoreCalculationResult, calculate_selected_score
from app.services.score_inputs import (
    ScoreInputSelection,
    ScoreInputStatus,
    load_academic_record_inputs,
    select_score_inputs,
)
from app.services.score_rule_schema import score_rule_definition_from_payload
from app.services.score_selection import (
    ComparableCourseValue,
    ScoreSelectionResult,
    select_terms_and_subjects,
)


class ConsultationError(ValueError):
    pass


class ConsultationStatus(StrEnum):
    READY = "READY"
    ELIGIBILITY_BLOCKED = "ELIGIBILITY_BLOCKED"
    SCORE_NEEDS_REVIEW = "SCORE_NEEDS_REVIEW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class AdmissionResultComparisonStatus(StrEnum):
    COMPARABLE = "COMPARABLE"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    NOT_AVAILABLE = "NOT_AVAILABLE"


@dataclass(frozen=True)
class ConsultationRequest:
    student_id: str
    admission_track_id: str
    facts: StudentFacts
    admission_result_year: int | None = None

    def __post_init__(self) -> None:
        if not self.student_id.strip():
            raise ConsultationError("내부 학생 식별자가 필요합니다.")
        if not self.admission_track_id.strip():
            raise ConsultationError("대상 전형이 필요합니다.")
        if self.admission_result_year is not None and self.admission_result_year < 2000:
            raise ConsultationError("입시결과 기준연도가 유효하지 않습니다.")


@dataclass(frozen=True)
class ConsultationTarget:
    admission_track_id: str
    academic_year: int
    institution_name: str
    campus_name: str
    program_name: str
    program_code: str | None
    admission_round_name: str
    admission_round_code: str
    admission_track_name: str
    admission_track_code: str


@dataclass(frozen=True)
class ConsultationEvidence:
    rule_kind: str
    rule_id: str
    rule_version: str
    source_document_id: str
    document_type: str
    document_status: str
    page_number: int
    locator: str | None


@dataclass(frozen=True)
class AdmissionResultComparison:
    status: AdmissionResultComparisonStatus
    result: AdmissionResultAnalysisInput | None
    warning: str | None


@dataclass(frozen=True)
class ConsultationResult:
    status: ConsultationStatus
    target: ConsultationTarget
    eligibility: EligibilityDecision
    score_input: ScoreInputSelection | None
    score_selection: ScoreSelectionResult | None
    score: ScoreCalculationResult | None
    evidence: tuple[ConsultationEvidence, ...]
    admission_result: AdmissionResultComparison
    warnings: tuple[str, ...]


def run_consultation(session: Session, request: ConsultationRequest) -> ConsultationResult:
    target = load_consultation_target(session, request.admission_track_id)
    eligibility_rule = load_published_eligibility_rule(session, request.admission_track_id)
    eligibility = evaluate_eligibility(request.facts, to_eligibility_rule(eligibility_rule))
    evidence = [_load_evidence(session, "ELIGIBILITY", eligibility_rule)]
    unavailable = AdmissionResultComparison(
        AdmissionResultComparisonStatus.NOT_AVAILABLE,
        None,
        "비교할 게시 입시결과를 선택하지 않았습니다.",
    )
    if not eligibility.allows_score_calculation:
        return ConsultationResult(
            status=ConsultationStatus.ELIGIBILITY_BLOCKED,
            target=target,
            eligibility=eligibility,
            score_input=None,
            score_selection=None,
            score=None,
            evidence=tuple(evidence),
            admission_result=unavailable,
            warnings=("지원자격이 허용되지 않아 성적 규칙과 성적 자료를 조회하지 않았습니다.",),
        )

    scope_rule = load_published_grade_source_scope_rule(session, request.admission_track_id)
    score_rule = load_published_score_rule(session, request.admission_track_id)
    stored_score_rule = session.get(ScoreRule, score_rule.rule_id)
    if stored_score_rule is None:
        raise ConsultationError("게시 성적 규칙 레코드를 찾을 수 없습니다.")
    _validate_score_rule_identity(target, stored_score_rule)
    evidence.extend(
        (
            _load_evidence(session, "GRADE_SOURCE_SCOPE", scope_rule),
            _load_evidence(session, "SCORE", score_rule),
        )
    )
    records = load_academic_record_inputs(session, request.student_id)
    score_input = select_score_inputs(
        records=records,
        rule=scope_rule,
        eligibility=eligibility,
    )
    if score_input.status is not ScoreInputStatus.READY:
        return _score_unready_result(
            target,
            eligibility,
            score_input,
            evidence,
            unavailable,
            "성적 출처 선택 결과가 계산 가능한 상태가 아닙니다.",
        )

    definition = score_rule_definition_from_payload(score_rule.payload)
    course_values, missing_course_ids = _rank_grade_course_values(score_input)
    if missing_course_ids:
        return ConsultationResult(
            status=ConsultationStatus.SCORE_NEEDS_REVIEW,
            target=target,
            eligibility=eligibility,
            score_input=score_input,
            score_selection=None,
            score=None,
            evidence=tuple(evidence),
            admission_result=unavailable,
            warnings=(
                "석차등급이 없는 과목은 버전 고정 변환표가 연결될 때까지 임의 계산하지 않습니다.",
            ),
        )
    score_selection = select_terms_and_subjects(score_input, definition, course_values)
    if score_selection.status is not ScoreInputStatus.READY:
        status = (
            ConsultationStatus.INSUFFICIENT_DATA
            if score_selection.status is ScoreInputStatus.INSUFFICIENT_DATA
            else ConsultationStatus.SCORE_NEEDS_REVIEW
        )
        return ConsultationResult(
            status=status,
            target=target,
            eligibility=eligibility,
            score_input=score_input,
            score_selection=score_selection,
            score=None,
            evidence=tuple(evidence),
            admission_result=unavailable,
            warnings=("학기·과목 선택 결과를 검토해야 합니다.",),
        )
    if definition.attendance_included is True:
        return ConsultationResult(
            status=ConsultationStatus.SCORE_NEEDS_REVIEW,
            target=target,
            eligibility=eligibility,
            score_input=score_input,
            score_selection=score_selection,
            score=None,
            evidence=tuple(evidence),
            admission_result=unavailable,
            warnings=("출결 반영 규칙에는 별도로 검증된 출결 입력과 변환표가 필요합니다.",),
        )
    score = calculate_selected_score(
        score_selection,
        definition,
        rule_id=score_rule.rule_id,
        rule_version=score_rule.version,
    )
    admission_result = _load_admission_result_comparison(
        session,
        target=target,
        score_rule=stored_score_rule,
        result_year=request.admission_result_year,
    )
    return ConsultationResult(
        status=ConsultationStatus.READY,
        target=target,
        eligibility=eligibility,
        score_input=score_input,
        score_selection=score_selection,
        score=score,
        evidence=tuple(evidence),
        admission_result=admission_result,
        warnings=(),
    )


def load_consultation_target(session: Session, admission_track_id: str) -> ConsultationTarget:
    track = session.get(AdmissionTrack, admission_track_id)
    if track is None:
        raise ConsultationError("대상 전형을 찾을 수 없습니다.")
    admission_round = session.get(AdmissionRound, track.admission_round_id)
    program = session.get(Program, track.program_id)
    if admission_round is None or program is None:
        raise ConsultationError("전형의 모집시기 또는 학과 연결이 유효하지 않습니다.")
    campus = session.get(Campus, program.campus_id)
    institution = session.get(Institution, admission_round.institution_id)
    if campus is None or institution is None or campus.institution_id != institution.id:
        raise ConsultationError("전형의 대학·캠퍼스 연결이 유효하지 않습니다.")
    return ConsultationTarget(
        admission_track_id=track.id,
        academic_year=admission_round.academic_year,
        institution_name=institution.name,
        campus_name=campus.name,
        program_name=program.name,
        program_code=program.code,
        admission_round_name=admission_round.name,
        admission_round_code=admission_round.code,
        admission_track_name=track.name,
        admission_track_code=track.code,
    )


def list_consultation_targets(session: Session) -> tuple[ConsultationTarget, ...]:
    track_ids = tuple(
        session.scalars(
            select(AdmissionTrack.id)
            .join(
                AdmissionEligibilityRule,
                AdmissionEligibilityRule.admission_track_id == AdmissionTrack.id,
            )
            .join(
                GradeSourceScopeRule,
                GradeSourceScopeRule.admission_track_id == AdmissionTrack.id,
            )
            .join(ScoreRule, ScoreRule.admission_track_id == AdmissionTrack.id)
            .where(
                AdmissionEligibilityRule.lifecycle_status == "PUBLISHED",
                GradeSourceScopeRule.lifecycle_status == "PUBLISHED",
                ScoreRule.lifecycle_status == "PUBLISHED",
            )
            .order_by(AdmissionTrack.id)
        )
    )
    return tuple(load_consultation_target(session, track_id) for track_id in track_ids)


def classify_admission_result(
    result: AdmissionResultAnalysisInput,
    *,
    current_rule_id: str,
    current_rule_version: str,
    current_academic_year: int,
) -> AdmissionResultComparison:
    historical = result.historical_rule
    comparable = (
        result.key.academic_year == current_academic_year
        and historical is not None
        and historical.academic_year == current_academic_year
        and historical.rule_id == current_rule_id
        and historical.version == current_rule_version
    )
    if comparable:
        return AdmissionResultComparison(AdmissionResultComparisonStatus.COMPARABLE, result, None)
    return AdmissionResultComparison(
        AdmissionResultComparisonStatus.REFERENCE_ONLY,
        result,
        "모집학년도 또는 성적 규칙 버전이 달라 직접적인 점수 비교에는 사용하지 않습니다.",
    )


def _load_admission_result_comparison(
    session: Session,
    *,
    target: ConsultationTarget,
    score_rule: ScoreRule,
    result_year: int | None,
) -> AdmissionResultComparison:
    if result_year is None:
        return AdmissionResultComparison(
            AdmissionResultComparisonStatus.NOT_AVAILABLE,
            None,
            "비교할 입시결과 기준연도를 선택하지 않았습니다.",
        )
    if target.program_code is None:
        return AdmissionResultComparison(
            AdmissionResultComparisonStatus.NOT_AVAILABLE,
            None,
            "학과의 입시결과 코드가 등록되지 않아 결과를 추정하지 않습니다.",
        )
    values = (
        score_rule.university_code,
        score_rule.campus_code,
        score_rule.admission_round,
        score_rule.admission_track_code,
    )
    if any(value is None for value in values):
        raise ConsultationError("게시 성적 규칙의 입시결과 업무키가 불완전합니다.")
    key = AdmissionResultKey(
        academic_year=result_year,
        university_code=str(score_rule.university_code),
        campus_code=str(score_rule.campus_code),
        admission_round=str(score_rule.admission_round),
        admission_track_code=str(score_rule.admission_track_code),
        program_code=target.program_code,
    )
    try:
        result = load_published_admission_result_for_analysis(session, key)
    except PublishedAdmissionResultNotFound:
        return AdmissionResultComparison(
            AdmissionResultComparisonStatus.NOT_AVAILABLE,
            None,
            f"{result_year}학년도에 게시 승인된 동일 업무키 입시결과가 없습니다.",
        )
    except PublishedAdmissionResultConflict as error:
        raise ConsultationError(str(error)) from error
    return classify_admission_result(
        result,
        current_rule_id=score_rule.id,
        current_rule_version=score_rule.version,
        current_academic_year=target.academic_year,
    )


def _validate_score_rule_identity(target: ConsultationTarget, score_rule: ScoreRule) -> None:
    if (
        score_rule.admission_year != target.academic_year
        or score_rule.admission_round != target.admission_round_code
        or score_rule.admission_track_code != target.admission_track_code
    ):
        raise ConsultationError("게시 성적 규칙과 대상 전형의 학년도·모집시기·전형이 다릅니다.")


def _rank_grade_course_values(
    selection: ScoreInputSelection,
) -> tuple[dict[str, ComparableCourseValue], tuple[str, ...]]:
    values: dict[str, ComparableCourseValue] = {}
    missing: list[str] = []
    for record in selection.records:
        for course in record.courses:
            if course.rank_grade is None:
                missing.append(course.course_record_id)
                continue
            scope_codes = frozenset({course.subject_group} if course.subject_group else ())
            values[course.course_record_id] = ComparableCourseValue(
                course_record_id=course.course_record_id,
                normalized_value=course.rank_grade,
                value_scale="RANK_GRADE",
                scope_codes=scope_codes,
            )
    return values, tuple(missing)


def _load_evidence(session: Session, rule_kind: str, rule) -> ConsultationEvidence:  # type: ignore[no-untyped-def]
    citation = session.get(SourceCitation, rule.source_citation_id)
    if citation is None:
        raise ConsultationError("게시 규칙의 근거 인용을 찾을 수 없습니다.")
    document = session.get(SourceDocument, citation.source_document_id)
    if document is None:
        raise ConsultationError("게시 규칙의 근거 문서를 찾을 수 없습니다.")
    return ConsultationEvidence(
        rule_kind=rule_kind,
        rule_id=rule.rule_id,
        rule_version=rule.version,
        source_document_id=document.id,
        document_type=document.document_type,
        document_status=document.document_status,
        page_number=citation.page_number,
        locator=citation.locator,
    )


def _score_unready_result(
    target: ConsultationTarget,
    eligibility: EligibilityDecision,
    score_input: ScoreInputSelection,
    evidence: list[ConsultationEvidence],
    admission_result: AdmissionResultComparison,
    warning: str,
) -> ConsultationResult:
    status = (
        ConsultationStatus.INSUFFICIENT_DATA
        if score_input.status is ScoreInputStatus.INSUFFICIENT_DATA
        else ConsultationStatus.SCORE_NEEDS_REVIEW
    )
    return ConsultationResult(
        status=status,
        target=target,
        eligibility=eligibility,
        score_input=score_input,
        score_selection=None,
        score=None,
        evidence=tuple(evidence),
        admission_result=admission_result,
        warnings=(warning,),
    )


__all__ = [
    "AdmissionResultComparison",
    "AdmissionResultComparisonStatus",
    "ConsultationError",
    "ConsultationEvidence",
    "ConsultationRequest",
    "ConsultationResult",
    "ConsultationStatus",
    "ConsultationTarget",
    "classify_admission_result",
    "list_consultation_targets",
    "load_consultation_target",
    "run_consultation",
]
