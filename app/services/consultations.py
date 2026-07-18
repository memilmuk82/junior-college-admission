from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
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
from app.services.admission_result_imports import (
    PublishedImportedAdmissionResult,
    list_published_imported_results_for_program,
    load_published_imported_result,
)
from app.services.admission_results import AdmissionResultKey, HistoricalRuleReference
from app.services.eligibility import (
    EligibilityDecision,
    EligibilityRule,
    StudentFacts,
    evaluate_eligibility,
    evaluate_eligibility_for_verification,
)
from app.services.published_rules import (
    load_published_eligibility_rule,
    load_published_grade_source_scope_rule,
    load_published_score_rule,
    to_eligibility_rule,
)
from app.services.score_calculation import (
    ReflectedGradeResult,
    ScoreCalculationResult,
    calculate_reflected_grade,
)
from app.services.score_conversion import (
    ScoreConversionError,
    ZScoreConversionTrace,
    convert_z_score_for_rule,
)
from app.services.score_inputs import (
    ScoreInputSelection,
    ScoreInputStatus,
    load_academic_record_inputs,
    select_score_inputs,
    select_score_inputs_for_verification,
)
from app.services.score_rule_schema import ScoreRuleDefinition, score_rule_definition_from_payload
from app.services.score_selection import (
    ComparableCourseValue,
    ScoreSelectionResult,
    select_terms_and_subjects,
)
from app.services.verified_source_rules import (
    VerifiedSourceRule,
    confirmed_verified_source_rule,
    find_verified_source_rule,
)


class ConsultationError(ValueError):
    pass


PUBLIC_AVERAGE_GRADE_SCALES = frozenset({"RANK_GRADE", "DEMO_SYNTHETIC_RANK_GRADE"})


class ConsultationStatus(StrEnum):
    READY = "READY"
    ELIGIBILITY_BLOCKED = "ELIGIBILITY_BLOCKED"
    SCORE_NEEDS_REVIEW = "SCORE_NEEDS_REVIEW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class AdmissionResultComparisonStatus(StrEnum):
    COMPARABLE = "COMPARABLE"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    INCOMPATIBLE_SCALE = "INCOMPATIBLE_SCALE"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class ConsultationItemStatus(StrEnum):
    EVALUATED = "EVALUATED"
    PREPARING = "PREPARING"
    ERROR = "ERROR"


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
class BatchConsultationRequest:
    student_id: str
    program_ids: tuple[str, ...]
    academic_year: int
    facts: StudentFacts
    admission_result_year: int | None = None

    def __post_init__(self) -> None:
        if not self.student_id.strip():
            raise ConsultationError("내부 학생 식별자가 필요합니다.")
        normalized = tuple(dict.fromkeys(item.strip() for item in self.program_ids if item.strip()))
        if not normalized:
            raise ConsultationError("희망 대학·학과를 하나 이상 선택해야 합니다.")
        if normalized != self.program_ids:
            object.__setattr__(self, "program_ids", normalized)
        if not 2000 <= self.academic_year <= 2100:
            raise ConsultationError("모집학년도가 유효하지 않습니다.")
        if (
            self.admission_result_year is not None
            and not 2000 <= self.admission_result_year <= 2100
        ):
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
    institution_code: str = ""
    campus_code: str = ""


@dataclass(frozen=True)
class ConsultationProgram:
    program_id: str
    academic_year: int
    institution_name: str
    campus_name: str
    program_name: str
    program_code: str | None


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
    academic_year: int | None = None


@dataclass(frozen=True)
class AdmissionResultComparison:
    status: AdmissionResultComparisonStatus
    result: AdmissionResultAnalysisInput | None
    warning: str | None

    @property
    def display_average_grade(self) -> Decimal | None:
        if (
            self.status is AdmissionResultComparisonStatus.INCOMPATIBLE_SCALE
            or self.result is None
            or self.result.score_basis not in PUBLIC_AVERAGE_GRADE_SCALES
        ):
            return None
        return self.result.average_score


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
    reflected_grade: ReflectedGradeResult | None = None
    multiple_application_status: str = "NOT_EVALUATED"
    z_score_traces: tuple[ZScoreConversionTrace, ...] = ()


@dataclass(frozen=True)
class BatchConsultationItem:
    program: ConsultationProgram
    target: ConsultationTarget | None
    status: ConsultationItemStatus
    result: ConsultationResult | None
    message: str | None = None
    reference_results: tuple[PublishedImportedAdmissionResult, ...] = ()


@dataclass(frozen=True)
class BatchConsultationResult:
    academic_year: int
    selected_programs: tuple[ConsultationProgram, ...]
    items: tuple[BatchConsultationItem, ...]
    warnings: tuple[str, ...] = ()


def run_consultation(
    session: Session,
    request: ConsultationRequest,
    *,
    records_loader: Callable[[], tuple] | None = None,
) -> ConsultationResult:
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
    records = (
        load_academic_record_inputs(session, request.student_id)
        if records_loader is None
        else records_loader()
    )
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
    reflected_grade = calculate_reflected_grade(
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
        score=None,
        evidence=tuple(evidence),
        admission_result=admission_result,
        warnings=(
            ("출결 배점은 평균등급과 분리되며 별도 검증 입력이 필요합니다.",)
            if definition.attendance_included is True
            else ()
        ),
        reflected_grade=reflected_grade,
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
        institution_code=institution.code or "",
        campus_code=campus.code or "",
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


def list_consultation_programs(
    session: Session, academic_year: int = 2027
) -> tuple[ConsultationProgram, ...]:
    """List every program with a track in the year, including rule-preparation states."""

    rows = tuple(
        session.execute(
            select(Program, Campus, Institution)
            .join(Campus, Program.campus_id == Campus.id)
            .join(Institution, Campus.institution_id == Institution.id)
            .join(AdmissionTrack, AdmissionTrack.program_id == Program.id)
            .join(AdmissionRound, AdmissionTrack.admission_round_id == AdmissionRound.id)
            .where(AdmissionRound.academic_year == academic_year)
            .distinct()
            .order_by(Institution.name, Campus.name, Program.name, Program.id)
        )
    )
    return tuple(
        ConsultationProgram(
            program_id=program.id,
            academic_year=academic_year,
            institution_name=institution.name,
            campus_name=campus.name,
            program_name=program.name,
            program_code=program.code,
        )
        for program, campus, institution in rows
    )


def _verified_source_evidence(
    rule: VerifiedSourceRule, rule_kind: str, *, administrator_confirmed: bool
) -> ConsultationEvidence:
    evidence = rule.evidence[
        {
            "ELIGIBILITY": "eligibility",
            "GRADE_SOURCE_SCOPE": "grade_source",
            "SCORE": "score",
        }[rule_kind]
    ]
    return ConsultationEvidence(
        rule_kind=rule_kind,
        rule_id=rule.rule_id,
        rule_version=rule.version,
        source_document_id=evidence.document_name,
        document_type=evidence.document_name,
        document_status=(
            f"VERIFIED_SOURCE ({evidence.source_status}) · "
            + ("관리자 최종 확인 완료" if administrator_confirmed else "관리자 최종 확인 필요")
        ),
        page_number=evidence.page_number,
        locator=evidence.locator,
        academic_year=evidence.academic_year,
    )


def _run_verified_source_consultation(
    *,
    session: Session,
    target: ConsultationTarget,
    facts: StudentFacts,
    result_year: int | None,
    records_loader: Callable[[], tuple],
) -> ConsultationResult:
    rule = find_verified_source_rule(
        academic_year=target.academic_year,
        institution_code=target.institution_code,
        campus_code=target.campus_code,
        admission_round_code=target.admission_round_code,
        admission_track_code=target.admission_track_code,
    )
    if rule is None:
        raise LookupError("공식 성적 계산 규칙이 아직 준비되지 않았습니다.")
    if rule.execution_status != "VERIFIED_SOURCE":
        raise LookupError("공식 문서의 성적 범위가 확인되지 않아 검수 대기 중입니다.")
    administrator_confirmed = confirmed_verified_source_rule(session, rule) is not None
    eligibility = evaluate_eligibility_for_verification(
        facts,
        EligibilityRule(
            rule_id=f"{rule.rule_id}:eligibility",
            version=rule.version,
            lifecycle_status="VERIFIED",
            payload=rule.eligibility_payload,
            source_citation_id=rule.evidence["eligibility"].document_name,
            independent_verified=True,
            golden_test_ref=None,
            human_approved_at=None,
        ),
    )
    eligibility_evidence = _verified_source_evidence(
        rule, "ELIGIBILITY", administrator_confirmed=administrator_confirmed
    )
    unavailable = AdmissionResultComparison(
        AdmissionResultComparisonStatus.NOT_AVAILABLE,
        None,
        "동일 업무키의 공개 입시결과 연결을 확인하고 있습니다.",
    )
    verified_warning = "VERIFIED_SOURCE 공식 문서 대조 규칙입니다. " + (
        "관리자 최종 확인 완료 상태입니다."
        if administrator_confirmed
        else "관리자 최종 확인 전 상태입니다."
    )
    if not eligibility.allows_score_calculation:
        return ConsultationResult(
            status=ConsultationStatus.ELIGIBILITY_BLOCKED,
            target=target,
            eligibility=eligibility,
            score_input=None,
            score_selection=None,
            score=None,
            evidence=(eligibility_evidence,),
            admission_result=unavailable,
            warnings=(
                "지원자격이 허용되지 않아 성적 범위와 성적 계산을 실행하지 않았습니다.",
                verified_warning,
            ),
        )
    score_input = select_score_inputs_for_verification(
        records=records_loader(),
        payload=rule.grade_source_payload,
        eligibility=eligibility,
        rule_id=f"{rule.rule_id}:scope",
        rule_version=rule.version,
    )
    evidence = (
        eligibility_evidence,
        _verified_source_evidence(
            rule, "GRADE_SOURCE_SCOPE", administrator_confirmed=administrator_confirmed
        ),
        _verified_source_evidence(rule, "SCORE", administrator_confirmed=administrator_confirmed),
    )
    if score_input.status is not ScoreInputStatus.READY:
        return _score_unready_result(
            target,
            eligibility,
            score_input,
            list(evidence),
            unavailable,
            verified_warning,
        )
    definition = score_rule_definition_from_payload(rule.score_rule_payload)
    course_values, missing_course_ids, z_score_traces = _verified_course_values(
        score_input, definition=definition, rule=rule
    )
    if missing_course_ids:
        return ConsultationResult(
            status=ConsultationStatus.SCORE_NEEDS_REVIEW,
            target=target,
            eligibility=eligibility,
            score_input=score_input,
            score_selection=None,
            score=None,
            evidence=evidence,
            admission_result=unavailable,
            warnings=(
                "석차등급이 없고 해당 대학의 완전한 공식 Z점수 변환표를 적용할 수 없는 "
                "과목은 검수해야 합니다.",
                verified_warning,
            ),
            z_score_traces=z_score_traces,
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
            evidence=evidence,
            admission_result=unavailable,
            warnings=("학기·과목 선택 결과를 검토해야 합니다.", verified_warning),
        )
    reflected_grade = calculate_reflected_grade(
        score_selection,
        definition,
        rule_id=rule.rule_id,
        rule_version=rule.version,
    )
    admission_result = _load_imported_result_comparison(
        session,
        target=target,
        result_year=result_year,
        current_rule_id=rule.rule_id,
        current_rule_version=rule.version,
    )
    return ConsultationResult(
        status=ConsultationStatus.READY,
        target=target,
        eligibility=eligibility,
        score_input=score_input,
        score_selection=score_selection,
        score=None,
        evidence=evidence,
        admission_result=admission_result,
        warnings=(verified_warning,),
        reflected_grade=reflected_grade,
        z_score_traces=z_score_traces,
    )


def _verified_course_values(
    selection: ScoreInputSelection,
    *,
    definition: ScoreRuleDefinition,
    rule: VerifiedSourceRule,
) -> tuple[
    dict[str, ComparableCourseValue],
    tuple[str, ...],
    tuple[ZScoreConversionTrace, ...],
]:
    values, missing = _rank_grade_course_values(selection)
    if not missing or definition.z_score_policy != "TABLE_LOOKUP":
        return values, missing, ()
    if rule.z_score_table_version is None or not rule.z_score_table_rows:
        return values, missing, ()
    unresolved: list[str] = []
    traces: list[ZScoreConversionTrace] = []
    missing_set = set(missing)
    for record in selection.records:
        for course in record.courses:
            if course.course_record_id not in missing_set:
                continue
            try:
                converted = convert_z_score_for_rule(
                    raw_score=course.raw_score,
                    course_mean=course.course_mean,
                    standard_deviation=course.standard_deviation,
                    definition=definition,
                    table_rows=rule.z_score_table_rows,
                    table_version=rule.z_score_table_version,
                )
            except ScoreConversionError:
                unresolved.append(course.course_record_id)
                continue
            scope_codes = frozenset({course.subject_group} if course.subject_group else ())
            values[course.course_record_id] = ComparableCourseValue(
                course_record_id=course.course_record_id,
                normalized_value=converted.converted_value,
                value_scale="RANK_GRADE",
                scope_codes=scope_codes,
            )
            traces.append(converted.trace)
    return values, tuple(unresolved), tuple(traces)


def run_batch_consultation(
    session: Session,
    request: BatchConsultationRequest,
    *,
    records_loader: Callable[[], tuple] | None = None,
) -> BatchConsultationResult:
    available = {
        item.program_id: item for item in list_consultation_programs(session, request.academic_year)
    }
    invalid = tuple(program_id for program_id in request.program_ids if program_id not in available)
    if invalid:
        raise ConsultationError("선택한 학과에 허용되지 않은 ID가 포함되어 있습니다.")
    selected = tuple(available[program_id] for program_id in request.program_ids)
    cached_records: tuple | None = None

    def records_loader_from_database() -> tuple:
        nonlocal cached_records
        if cached_records is None:
            cached_records = load_academic_record_inputs(session, request.student_id)
        return cached_records

    resolved_records_loader = records_loader or records_loader_from_database

    items: list[BatchConsultationItem] = []
    for program in selected:
        track_ids = tuple(
            session.scalars(
                select(AdmissionTrack.id)
                .join(AdmissionRound, AdmissionTrack.admission_round_id == AdmissionRound.id)
                .where(
                    AdmissionTrack.program_id == program.program_id,
                    AdmissionRound.academic_year == request.academic_year,
                )
                .order_by(AdmissionRound.code, AdmissionTrack.code, AdmissionTrack.id)
            )
        )
        for track_id in track_ids:
            target: ConsultationTarget | None = None
            try:
                with session.begin_nested():
                    target = load_consultation_target(session, track_id)
                    result = run_consultation(
                        session,
                        ConsultationRequest(
                            student_id=request.student_id,
                            admission_track_id=track_id,
                            facts=request.facts,
                            admission_result_year=request.admission_result_year,
                        ),
                        records_loader=resolved_records_loader,
                    )
            except LookupError as error:
                if target is not None:
                    try:
                        result = _run_verified_source_consultation(
                            session=session,
                            target=target,
                            facts=request.facts,
                            result_year=request.admission_result_year,
                            records_loader=resolved_records_loader,
                        )
                    except (LookupError, ValueError) as verified_error:
                        reference_results = _preparing_reference_results(
                            session,
                            program=program,
                            target=target,
                            target_year=request.academic_year,
                            result_year=request.admission_result_year,
                        )
                        items.append(
                            BatchConsultationItem(
                                program,
                                target,
                                ConsultationItemStatus.PREPARING,
                                None,
                                f"계산 기준 준비 중: {verified_error}",
                                reference_results,
                            )
                        )
                    else:
                        items.append(
                            BatchConsultationItem(
                                program,
                                result.target,
                                ConsultationItemStatus.EVALUATED,
                                result,
                            )
                        )
                else:
                    items.append(
                        BatchConsultationItem(
                            program,
                            target,
                            ConsultationItemStatus.PREPARING,
                            None,
                            f"계산 기준 준비 중: {error}",
                        )
                    )
            except ValueError as error:
                items.append(
                    BatchConsultationItem(
                        program,
                        target,
                        ConsultationItemStatus.ERROR,
                        None,
                        f"항목을 계산하지 못했습니다: {error}",
                    )
                )
            except SQLAlchemyError:
                items.append(
                    BatchConsultationItem(
                        program,
                        target,
                        ConsultationItemStatus.ERROR,
                        None,
                        "항목을 계산하지 못했습니다: 데이터 조회 오류가 발생했습니다.",
                    )
                )
            else:
                items.append(
                    BatchConsultationItem(
                        program,
                        result.target,
                        ConsultationItemStatus.EVALUATED,
                        result,
                    )
                )
    return BatchConsultationResult(
        request.academic_year,
        selected,
        tuple(items),
        ("복수지원 가능 여부는 전형별 지원자격과 별도이며 대학별 모집요강 확인이 필요합니다.",),
    )


def _preparing_reference_results(
    session: Session,
    *,
    program: ConsultationProgram,
    target: ConsultationTarget,
    target_year: int,
    result_year: int | None,
) -> tuple[PublishedImportedAdmissionResult, ...]:
    if result_year is None or program.program_code is None:
        return ()
    return list_published_imported_results_for_program(
        session,
        target_academic_year=target_year,
        result_academic_year=result_year,
        institution_code=target.institution_code,
        campus_code=target.campus_code,
        program_code=program.program_code,
    )


def classify_admission_result(
    result: AdmissionResultAnalysisInput,
    *,
    current_rule_id: str,
    current_rule_version: str,
    current_academic_year: int,
    expected_grade_scale: str = "RANK_GRADE",
) -> AdmissionResultComparison:
    if result.score_basis != expected_grade_scale:
        return AdmissionResultComparison(
            AdmissionResultComparisonStatus.INCOMPATIBLE_SCALE,
            result,
            "공개 자료의 성적 척도가 학생 반영 평균등급과 달라 "
            "숫자를 표시하거나 직접 비교하지 않습니다.",
        )
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
        "모집학년도 또는 성적 규칙 버전이 달라 참고용으로만 표시합니다.",
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
        return _load_imported_result_comparison(
            session,
            target=target,
            result_year=result_year,
            current_rule_id=score_rule.id,
            current_rule_version=score_rule.version,
        )
    except PublishedAdmissionResultConflict as error:
        raise ConsultationError(str(error)) from error
    return classify_admission_result(
        result,
        current_rule_id=score_rule.id,
        current_rule_version=score_rule.version,
        current_academic_year=target.academic_year,
    )


def _load_imported_result_comparison(
    session: Session,
    *,
    target: ConsultationTarget,
    result_year: int | None,
    current_rule_id: str,
    current_rule_version: str,
) -> AdmissionResultComparison:
    if result_year is None or target.program_code is None:
        return AdmissionResultComparison(
            AdmissionResultComparisonStatus.NOT_AVAILABLE,
            None,
            "비교할 결과연도 또는 학과 업무키가 없습니다.",
        )
    imported = load_published_imported_result(
        session,
        target_academic_year=target.academic_year,
        result_academic_year=result_year,
        institution_code=target.institution_code,
        campus_code=target.campus_code,
        program_code=target.program_code,
        admission_round_code=target.admission_round_code,
        admission_track_code=target.admission_track_code,
    )
    if imported is None:
        return AdmissionResultComparison(
            AdmissionResultComparisonStatus.NOT_AVAILABLE,
            None,
            f"{result_year}학년도에 게시 승인된 동일 업무키 입시결과가 없습니다.",
        )
    if imported.score_basis != "RANK_GRADE" or imported.score_direction != "LOWER_IS_BETTER":
        return AdmissionResultComparison(
            AdmissionResultComparisonStatus.INCOMPATIBLE_SCALE,
            None,
            "공개 자료의 성적 척도 또는 점수 방향이 학생 반영 평균등급과 달라 "
            "숫자를 표시하거나 직접 비교하지 않습니다.",
        )
    historical = None
    historical_values = (
        imported.historical_score_rule_id,
        imported.historical_score_rule_version,
        imported.historical_score_rule_year,
    )
    if all(value is not None for value in historical_values):
        historical = HistoricalRuleReference(
            rule_id=str(imported.historical_score_rule_id),
            version=str(imported.historical_score_rule_version),
            academic_year=int(str(imported.historical_score_rule_year)),
        )
    result = AdmissionResultAnalysisInput(
        key=AdmissionResultKey(
            academic_year=imported.result_academic_year,
            university_code=imported.institution_code,
            campus_code=imported.campus_code,
            admission_round=imported.admission_round_code,
            admission_track_code=imported.admission_track_code,
            program_code=imported.program_code,
        ),
        publication_version=imported.publication_version,
        applicant_count=imported.applicant_count,
        admitted_count=imported.admitted_count,
        competition_rate=imported.competition_rate,
        highest_score=imported.best_score,
        average_score=imported.average_score,
        lowest_score=imported.cutoff_score,
        score_basis=imported.score_basis,
        historical_rule=historical,
        capacity=imported.capacity,
    )
    return classify_admission_result(
        result,
        current_rule_id=current_rule_id,
        current_rule_version=current_rule_version,
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
        academic_year=document.academic_year,
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
    "BatchConsultationItem",
    "BatchConsultationRequest",
    "BatchConsultationResult",
    "ConsultationError",
    "ConsultationEvidence",
    "ConsultationItemStatus",
    "ConsultationProgram",
    "ConsultationRequest",
    "ConsultationResult",
    "ConsultationStatus",
    "ConsultationTarget",
    "classify_admission_result",
    "list_consultation_programs",
    "list_consultation_targets",
    "load_consultation_target",
    "run_batch_consultation",
    "run_consultation",
]
