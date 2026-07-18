from __future__ import annotations

import hashlib
import json
from decimal import Decimal

import pytest

from app.services.admission_result_analysis import AdmissionResultAnalysisInput
from app.services.admission_results import AdmissionResultKey, HistoricalRuleReference
from app.services.ai_payloads import build_anonymous_consultation_payload
from app.services.ai_providers import (
    NarrativeDraft,
    NarrativeProviderError,
    generate_narrative_draft,
)
from app.services.consultations import (
    AdmissionResultComparison,
    AdmissionResultComparisonStatus,
    ConsultationResult,
    ConsultationStatus,
    ConsultationTarget,
)
from app.services.eligibility import (
    EligibilityDecision,
    EligibilityStatus,
    EligibilityTrace,
)
from app.services.score_calculation import (
    ReflectedGradeResult,
    ReflectedGradeTrace,
    ScoreCalculationResult,
    ScoreCalculationTrace,
)


def _result(
    *,
    average_score: Decimal | None = Decimal("0"),
    score_basis: str = "RANK_GRADE",
    comparison_status: AdmissionResultComparisonStatus = AdmissionResultComparisonStatus.COMPARABLE,
) -> ConsultationResult:
    target = ConsultationTarget(
        admission_track_id="track-internal-id",
        academic_year=2027,
        institution_name="합성전문대",
        campus_name="본교",
        program_name="합성학과",
        program_code="SYNTHETIC_PROGRAM",
        admission_round_name="수시 1차",
        admission_round_code="EARLY_1",
        admission_track_name="일반고 전형",
        admission_track_code="GENERAL",
    )
    eligibility = EligibilityDecision(
        status=EligibilityStatus.ELIGIBLE,
        reason_code="GENERAL_ALLOWED",
        matched_case_id="general",
        missing_facts=(),
        trace=EligibilityTrace(
            rule_id="eligibility-rule-id",
            rule_version="eligibility-v1",
            conditions=(),
        ),
    )
    score = ScoreCalculationResult(
        pre_round_score=Decimal("380.20"),
        final_score=Decimal("380.20"),
        display_score=Decimal("380.2"),
        maximum_score=Decimal("400"),
        trace=ScoreCalculationTrace(
            rule_id="score-rule-id",
            rule_version="score-v2",
            weighting_mode="EQUAL",
            grade_rounding_mode=None,
            grade_rounding_scale=None,
            components=(),
            aggregate_value=Decimal("2.00"),
            score_transform_mode="LINEAR",
            score_base=Decimal("400"),
            score_multiplier=Decimal("10"),
            rounding_mode="ROUND_HALF_UP",
            rounding_stage="FINAL",
            rounding_scale=2,
            display_scale=1,
            academic_score=Decimal("380.20"),
            attendance_score=None,
            attendance_maximum_score=None,
            attendance_table_code=None,
            attendance_table_version=None,
            non_predictive_components=(("interview_ratio", Decimal("0.2")),),
        ),
    )
    reflected_grade = ReflectedGradeResult(
        unrounded_average_grade=Decimal("2.00"),
        final_average_grade=Decimal("2.00"),
        display_average_grade=Decimal("2.0"),
        grade_scale="RANK_GRADE",
        trace=ReflectedGradeTrace(
            rule_id="score-rule-id",
            rule_version="score-v2",
            grade_scale="RANK_GRADE",
            weighting_mode="EQUAL",
            components=(),
            selected_semesters=(),
            selected_courses=(),
            semester_rounding_mode=None,
            semester_rounding_scale=None,
            grade_rounding_mode=None,
            grade_rounding_scale=None,
            rounding_mode="ROUND_HALF_UP",
            rounding_stage="DISPLAY_ONLY",
            rounding_scale=1,
            display_scale=1,
        ),
    )
    historical = HistoricalRuleReference(
        rule_id="score-rule-id",
        version="score-v2",
        academic_year=2027,
    )
    admission_result = AdmissionResultAnalysisInput(
        key=AdmissionResultKey(
            academic_year=2027,
            university_code="SYNTHETIC_U",
            campus_code="MAIN",
            admission_round="EARLY_1",
            admission_track_code="GENERAL",
            program_code="SYNTHETIC_PROGRAM",
        ),
        publication_version="published-v1",
        applicant_count=0,
        admitted_count=None,
        competition_rate=None,
        highest_score=None,
        average_score=average_score,
        lowest_score=None,
        score_basis=score_basis,
        historical_rule=historical,
    )
    return ConsultationResult(
        status=ConsultationStatus.READY,
        target=target,
        eligibility=eligibility,
        score_input=None,
        score_selection=None,
        score=score,
        evidence=(),
        admission_result=AdmissionResultComparison(
            status=comparison_status,
            result=admission_result,
            warning=None,
        ),
        warnings=(),
        reflected_grade=reflected_grade,
    )


def test_anonymous_payload_has_a_fixed_allowlist_and_preserves_zero() -> None:
    payload = build_anonymous_consultation_payload(_result())

    assert payload.schema_version == 2
    assert payload.data["results"][0]["target"] == {
        "academic_year": 2027,
        "institution_name": "합성전문대",
        "campus_name": "본교",
        "program_name": "합성학과",
        "admission_round_name": "수시 1차",
        "admission_track_name": "일반고 전형",
    }
    assert payload.data["results"][0]["average_grade"]["display_average_grade"] == "2.0"
    assert "track-internal-id" not in payload.canonical_json
    assert "student" not in payload.canonical_json.lower()
    assert len(payload.digest) == 64


def test_anonymous_payload_digest_distinguishes_zero_from_missing() -> None:
    zero = build_anonymous_consultation_payload(_result(average_score=Decimal("0")))
    missing = build_anonymous_consultation_payload(_result(average_score=None))

    assert zero.data["results"][0]["admission_result"]["average_grade"] == "0"
    assert missing.data["results"][0]["admission_result"]["average_grade"] is None
    assert zero.digest != missing.digest


def test_anonymous_payload_hides_average_from_incompatible_score_scale() -> None:
    payload = build_anonymous_consultation_payload(
        _result(
            average_score=Decimal("387.5"),
            score_basis="POINT_SCORE",
            comparison_status=AdmissionResultComparisonStatus.INCOMPATIBLE_SCALE,
        )
    )

    admission = payload.data["results"][0]["admission_result"]
    assert admission["status"] == "INCOMPATIBLE_SCALE"
    assert admission["average_grade"] is None
    assert "387.5" not in payload.canonical_json

    inconsistent_status = build_anonymous_consultation_payload(
        _result(average_score=Decimal("387.5"), score_basis="POINT_SCORE")
    )
    assert inconsistent_status.data["results"][0]["admission_result"]["average_grade"] is None
    assert "387.5" not in inconsistent_status.canonical_json


class _SyntheticProvider:
    provider_code = "SYNTHETIC"

    def __init__(self) -> None:
        self.received: dict[str, object] | None = None

    def generate(self, payload: dict[str, object], api_key: str) -> NarrativeDraft:
        assert api_key == "synthetic-secret"
        self.received = payload
        return NarrativeDraft(
            text="검증된 반영 평균등급과 자료 기준연도를 함께 확인했습니다.",
            check_items=("최종 모집요강의 변경 여부를 확인하세요.",),
        )


def test_provider_receives_only_the_anonymous_payload() -> None:
    payload = build_anonymous_consultation_payload(_result())
    provider = _SyntheticProvider()

    draft = generate_narrative_draft(provider, payload, "synthetic-secret")

    assert provider.received == payload.data
    assert draft.check_items == ("최종 모집요강의 변경 여부를 확인하세요.",)


def test_provider_rejects_tampered_or_extra_payload_fields() -> None:
    payload = build_anonymous_consultation_payload(_result())
    payload.data["student_id"] = "must-not-leave-server"

    with pytest.raises(NarrativeProviderError):
        generate_narrative_draft(_SyntheticProvider(), payload, "synthetic-secret")

    data = dict(build_anonymous_consultation_payload(_result()).data)
    data["student_id"] = "must-not-leave-server"
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    injected = type(payload)(
        schema_version=2,
        data=data,
        canonical_json=canonical,
        digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
    with pytest.raises(NarrativeProviderError):
        generate_narrative_draft(_SyntheticProvider(), injected, "synthetic-secret")


@pytest.mark.parametrize(
    "term",
    ["합격 확률", "합격\u200b 가능", "안정 지원", "적정권", "소신 지원", "위험", "추천"],
)
def test_provider_response_rejects_predictive_or_recommendation_terms(term: str) -> None:
    class UnsafeProvider:
        provider_code = "SYNTHETIC"

        def generate(self, payload: dict[str, object], api_key: str) -> NarrativeDraft:
            return NarrativeDraft(text=f"이 전형은 {term}입니다.", check_items=())

    with pytest.raises(NarrativeProviderError):
        generate_narrative_draft(
            UnsafeProvider(),
            build_anonymous_consultation_payload(_result()),
            "synthetic-secret",
        )


def test_provider_response_rejects_ungrounded_numbers_but_allows_payload_numbers() -> None:
    class NumberProvider:
        provider_code = "SYNTHETIC"

        def __init__(self, text: str) -> None:
            self.text = text

        def generate(self, payload: dict[str, object], api_key: str) -> NarrativeDraft:
            return NarrativeDraft(text=self.text, check_items=())

    payload = build_anonymous_consultation_payload(_result())
    grounded = generate_narrative_draft(
        NumberProvider("검증된 반영 평균등급은 2.00이며 기준연도는 2027년입니다."),
        payload,
        "synthetic-secret",
    )
    assert "2.00" in grounded.text

    with pytest.raises(NarrativeProviderError):
        generate_narrative_draft(
            NumberProvider("입력 근거에 없는 999점입니다."),
            payload,
            "synthetic-secret",
        )
