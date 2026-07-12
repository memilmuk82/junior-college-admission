from __future__ import annotations

import csv
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import cast

SCORE_RULE_CSV_HEADERS = (
    "schema_version",
    "admission_year",
    "university_code",
    "university_name",
    "campus_code",
    "admission_round",
    "admission_track_code",
    "admission_track_name",
    "rule_version",
    "home_grade_1_included",
    "home_grade_2_included",
    "home_grade_3_semester_1_included",
    "home_grade_3_semester_2_included",
    "vocational_grade_included",
    "vocational_semester_1_included",
    "vocational_semester_2_included",
    "value_direction",
    "semester_selection_method",
    "semester_selection_scope",
    "best_semester_count",
    "subject_selection_method",
    "best_subject_count",
    "subject_scope",
    "credit_weighted",
    "minimum_semester_credits",
    "semester_rounding_mode",
    "semester_rounding_scale",
    "grade_rounding_mode",
    "grade_rounding_scale",
    "weighting_mode",
    "grade_weight_1",
    "grade_weight_2",
    "grade_weight_3",
    "semester_weight_1_1",
    "semester_weight_1_2",
    "semester_weight_2_1",
    "semester_weight_2_2",
    "semester_weight_3_1",
    "semester_weight_3_2",
    "achievement_handling",
    "achievement_table_code",
    "achievement_source",
    "achievement_formula_version",
    "achievement_distribution_scale",
    "career_subject_included",
    "z_score_policy",
    "z_score_source",
    "z_score_table_code",
    "z_score_formula_version",
    "z_score_rounding_mode",
    "z_score_rounding_scale",
    "z_score_clip_min",
    "z_score_clip_max",
    "attendance_included",
    "attendance_table_code",
    "attendance_source",
    "attendance_minor_event_conversion_unit",
    "interview_ratio",
    "practical_ratio",
    "rounding_mode",
    "rounding_stage",
    "rounding_scale",
    "display_scale",
    "score_transform_mode",
    "score_base",
    "score_multiplier",
    "maximum_score",
    "evidence_document_id",
    "evidence_page",
    "evidence_location",
    "evidence_level",
    "source_status",
    "change_reason",
    "administrator_note",
)

Z_SCORE_TABLE_CSV_HEADERS = (
    "schema_version",
    "table_code",
    "z_min",
    "z_min_inclusive",
    "z_max",
    "z_max_inclusive",
    "converted_value",
    "evidence_document_id",
    "evidence_page",
    "evidence_location",
    "source_status",
    "change_reason",
)

BUSINESS_KEY_FIELDS = (
    "admission_year",
    "university_code",
    "campus_code",
    "admission_round",
    "admission_track_code",
)
BOOLEAN_FIELDS = (
    "home_grade_1_included",
    "home_grade_2_included",
    "home_grade_3_semester_1_included",
    "home_grade_3_semester_2_included",
    "vocational_grade_included",
    "vocational_semester_1_included",
    "vocational_semester_2_included",
    "credit_weighted",
    "career_subject_included",
    "attendance_included",
)
SEMESTER_SELECTION_METHODS = {"ALL", "FIRST_N", "RECENT_N", "BEST_N", "MANUAL_REVIEW"}
VALUE_DIRECTIONS = {"HIGHER_IS_BETTER", "LOWER_IS_BETTER"}
SEMESTER_SELECTION_SCOPES = {"GLOBAL", "PER_GRADE"}
SUBJECT_SELECTION_METHODS = {"ALL", "BEST_N", "SCOPE", "MANUAL_REVIEW"}
SUBJECT_SCOPES = {
    "ALL",
    "GENERAL_SUBJECTS",
    "CAREER_SUBJECTS",
    "SPECIFIED",
    "MANUAL_REVIEW",
}
ACHIEVEMENT_HANDLING_CODES = {"EXCLUDE", "GRADE_TABLE", "DISTRIBUTION", "MANUAL_REVIEW"}
ACHIEVEMENT_DISTRIBUTION_SCALES = {"RATIO", "PERCENT"}
ACHIEVEMENT_FORMULA_VERSIONS = {
    "TABLE_LOOKUP_V1",
    "CUMULATIVE_DISTRIBUTION_GRADE_V1",
}
Z_SCORE_POLICIES = {"NOT_USED", "INTERNAL_CALCULATION", "TABLE_LOOKUP", "MANUAL_REVIEW"}
Z_SCORE_FORMULA_VERSIONS = {"STANDARD_Z_V1", "MANUAL_REVIEW"}
Z_SCORE_SOURCES = {
    "UNIVERSITY_OFFICIAL",
    "VERIFIED_REFERENCE",
    "INTERNAL_CALCULATION",
    "MANUAL_REVIEW",
}
ROUNDING_MODES = {
    "ROUND_HALF_UP",
    "ROUND_HALF_EVEN",
    "ROUND_DOWN",
    "ROUND_UP",
    "TRUNCATE",
    "MANUAL_REVIEW",
}
WEIGHTING_MODES = {
    "EQUAL",
    "GRADE_ONLY",
    "GLOBAL_SEMESTER",
    "GRADE_WITHIN_SEMESTER",
}
ROUNDING_STAGES = {"FINAL", "DISPLAY_ONLY", "MANUAL_REVIEW"}
SCORE_TRANSFORM_MODES = {"IDENTITY", "LINEAR", "MANUAL_REVIEW"}
SOURCE_STATUSES = {
    "AMENDED_FINAL_GUIDE",
    "FINAL_GUIDE",
    "AMENDED_IMPLEMENTATION_PLAN",
    "IMPLEMENTATION_PLAN",
    "COMMON_STANDARD",
    "VERIFIED_REFERENCE",
    "REFERENCE_ONLY",
    "AI_EXTRACTED_DRAFT",
    "MANUAL_REVIEW",
}
EVIDENCE_LEVELS = {
    "UNIVERSITY_OFFICIAL",
    "COMMON_OFFICIAL",
    "VERIFIED_REFERENCE",
    "INTERNAL_CALCULATION",
    "MANUAL_REVIEW",
}
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_CSV_ROWS = 10_000
MAX_CELL_LENGTH = 10_000


@dataclass(frozen=True)
class CsvValidationIssue:
    row_number: int
    column: str | None
    code: str
    message: str


@dataclass(frozen=True)
class RuleIdentity:
    admission_year: int
    university_code: str
    campus_code: str
    admission_round: str
    admission_track_code: str

    @property
    def key(self) -> tuple[int, str, str, str, str]:
        return (
            self.admission_year,
            self.university_code,
            self.campus_code,
            self.admission_round,
            self.admission_track_code,
        )


@dataclass(frozen=True)
class ScoreRuleDefinition:
    home_grade_1_included: bool | None
    home_grade_2_included: bool | None
    home_grade_3_semester_1_included: bool | None
    home_grade_3_semester_2_included: bool | None
    vocational_grade_included: bool | None
    vocational_semester_1_included: bool | None
    vocational_semester_2_included: bool | None
    value_direction: str
    semester_selection_method: str
    semester_selection_scope: str
    best_semester_count: int | None
    subject_selection_method: str
    best_subject_count: int | None
    subject_scope: str
    credit_weighted: bool | None
    minimum_semester_credits: Decimal | None
    semester_rounding_mode: str | None
    semester_rounding_scale: int | None
    grade_rounding_mode: str | None
    grade_rounding_scale: int | None
    grade_weight_1: Decimal | None
    grade_weight_2: Decimal | None
    grade_weight_3: Decimal | None
    semester_weight_1_1: Decimal | None
    semester_weight_1_2: Decimal | None
    semester_weight_2_1: Decimal | None
    semester_weight_2_2: Decimal | None
    semester_weight_3_1: Decimal | None
    semester_weight_3_2: Decimal | None
    weighting_mode: str
    achievement_handling: str
    achievement_table_code: str | None
    achievement_source: str | None
    achievement_formula_version: str | None
    achievement_distribution_scale: str | None
    career_subject_included: bool | None
    z_score_policy: str
    z_score_source: str | None
    z_score_table_code: str | None
    z_score_formula_version: str | None
    z_score_rounding_mode: str | None
    z_score_rounding_scale: int | None
    z_score_clip_min: Decimal | None
    z_score_clip_max: Decimal | None
    attendance_included: bool | None
    attendance_table_code: str | None
    attendance_source: str | None
    attendance_minor_event_conversion_unit: int | None
    interview_ratio: Decimal | None
    practical_ratio: Decimal | None
    rounding_mode: str
    rounding_stage: str
    rounding_scale: int | None
    display_scale: int | None
    score_transform_mode: str
    score_base: Decimal | None
    score_multiplier: Decimal | None
    maximum_score: Decimal | None


@dataclass(frozen=True)
class ManagedScoreRule:
    identity: RuleIdentity
    university_name: str
    admission_track_name: str
    rule_version: str
    definition: ScoreRuleDefinition
    evidence_document_id: str | None
    evidence_page: int | None
    evidence_location: str | None
    evidence_level: str
    source_status: str
    change_reason: str
    administrator_note: str | None


@dataclass(frozen=True)
class ScoreRuleCsvResult:
    rows: tuple[ManagedScoreRule, ...]
    issues: tuple[CsvValidationIssue, ...]


@dataclass(frozen=True)
class ZScoreTableRow:
    table_code: str
    z_min: Decimal | None
    z_min_inclusive: bool
    z_max: Decimal | None
    z_max_inclusive: bool
    converted_value: Decimal
    evidence_document_id: str
    evidence_page: int
    evidence_location: str
    source_status: str
    change_reason: str


@dataclass(frozen=True)
class ZScoreTableCsvResult:
    rows: tuple[ZScoreTableRow, ...]
    issues: tuple[CsvValidationIssue, ...]


def parse_score_rule_csv(data: bytes) -> ScoreRuleCsvResult:
    raw_rows, header_issues = _read_csv(data, SCORE_RULE_CSV_HEADERS)
    if header_issues:
        return ScoreRuleCsvResult((), header_issues)

    parsed: list[tuple[int, ManagedScoreRule]] = []
    issues: list[CsvValidationIssue] = []
    for row_number, raw in raw_rows:
        row, row_issues = _parse_score_rule_row(row_number, raw)
        issues.extend(row_issues)
        if row is not None and not row_issues:
            parsed.append((row_number, row))

    key_rows: dict[tuple[int, str, str, str, str], list[int]] = {}
    for row_number, row in parsed:
        key_rows.setdefault(row.identity.key, []).append(row_number)
    duplicate_keys = {key for key, numbers in key_rows.items() if len(numbers) > 1}
    for key in duplicate_keys:
        for row_number in key_rows[key]:
            issues.append(
                CsvValidationIssue(
                    row_number,
                    None,
                    "DUPLICATE_KEY",
                    "동일한 대학·캠퍼스·모집시기·전형 키가 중복되었습니다.",
                )
            )
    valid_rows = tuple(row for _, row in parsed if row.identity.key not in duplicate_keys)
    return ScoreRuleCsvResult(valid_rows, tuple(issues))


def write_score_rule_csv(rows: Sequence[ManagedScoreRule], *, include_bom: bool = True) -> bytes:
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=SCORE_RULE_CSV_HEADERS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        values = _score_rule_to_csv_values(row)
        _reject_formula_like_export(
            {
                key: value
                for key, value in values.items()
                if key
                not in {
                    "z_score_clip_min",
                    "z_score_clip_max",
                    "score_base",
                    "score_multiplier",
                }
            }
        )
        writer.writerow(values)
    return output.getvalue().encode("utf-8-sig" if include_bom else "utf-8")


def score_rule_to_payload(row: ManagedScoreRule) -> dict[str, object]:
    definition = row.definition
    return {
        "schema_version": 1,
        "evidence_level": row.evidence_level,
        "source_inclusion": {
            "home_grade_1": definition.home_grade_1_included,
            "home_grade_2": definition.home_grade_2_included,
            "home_grade_3_semester_1": definition.home_grade_3_semester_1_included,
            "home_grade_3_semester_2": definition.home_grade_3_semester_2_included,
            "vocational_grade": definition.vocational_grade_included,
            "vocational_semester_1": definition.vocational_semester_1_included,
            "vocational_semester_2": definition.vocational_semester_2_included,
        },
        "value_direction": definition.value_direction,
        "semester_selection": {
            "method": definition.semester_selection_method,
            "scope": definition.semester_selection_scope,
            "best_count": definition.best_semester_count,
        },
        "subject_selection": {
            "method": definition.subject_selection_method,
            "best_count": definition.best_subject_count,
            "scope": definition.subject_scope,
            "credit_weighted": definition.credit_weighted,
            "minimum_semester_credits": _decimal_text(definition.minimum_semester_credits),
        },
        "semester_rounding": {
            "mode": definition.semester_rounding_mode,
            "scale": definition.semester_rounding_scale,
        },
        "grade_rounding": {
            "mode": definition.grade_rounding_mode,
            "scale": definition.grade_rounding_scale,
        },
        "grade_weights": {
            "grade_1": _decimal_text(definition.grade_weight_1),
            "grade_2": _decimal_text(definition.grade_weight_2),
            "grade_3": _decimal_text(definition.grade_weight_3),
        },
        "semester_weights": {
            "grade_1_semester_1": _decimal_text(definition.semester_weight_1_1),
            "grade_1_semester_2": _decimal_text(definition.semester_weight_1_2),
            "grade_2_semester_1": _decimal_text(definition.semester_weight_2_1),
            "grade_2_semester_2": _decimal_text(definition.semester_weight_2_2),
            "grade_3_semester_1": _decimal_text(definition.semester_weight_3_1),
            "grade_3_semester_2": _decimal_text(definition.semester_weight_3_2),
        },
        "weighting_mode": definition.weighting_mode,
        "achievement": {
            "handling": definition.achievement_handling,
            "table_code": definition.achievement_table_code,
            "source": definition.achievement_source,
            "formula_version": definition.achievement_formula_version,
            "distribution_scale": definition.achievement_distribution_scale,
            "career_subject_included": definition.career_subject_included,
        },
        "z_score": {
            "policy": definition.z_score_policy,
            "source": definition.z_score_source,
            "table_code": definition.z_score_table_code,
            "formula_version": definition.z_score_formula_version,
            "rounding_mode": definition.z_score_rounding_mode,
            "rounding_scale": definition.z_score_rounding_scale,
            "clip_min": _decimal_text(definition.z_score_clip_min),
            "clip_max": _decimal_text(definition.z_score_clip_max),
        },
        "attendance": {
            "attendance_included": definition.attendance_included,
            "table_code": definition.attendance_table_code,
            "source": definition.attendance_source,
            "minor_event_conversion_unit": definition.attendance_minor_event_conversion_unit,
        },
        "non_predictive_components": {
            "interview_ratio": _decimal_text(definition.interview_ratio),
            "practical_ratio": _decimal_text(definition.practical_ratio),
        },
        "rounding": {
            "mode": definition.rounding_mode,
            "stage": definition.rounding_stage,
            "scale": definition.rounding_scale,
            "display_scale": definition.display_scale,
        },
        "score_transform": {
            "mode": definition.score_transform_mode,
            "base": _decimal_text(definition.score_base),
            "multiplier": _decimal_text(definition.score_multiplier),
        },
        "maximum_score": _decimal_text(definition.maximum_score),
    }


def validate_score_rule_payload(payload: Mapping[str, object]) -> None:
    _payload_exact_keys(
        payload,
        {
            "schema_version",
            "evidence_level",
            "source_inclusion",
            "value_direction",
            "semester_selection",
            "subject_selection",
            "semester_rounding",
            "grade_rounding",
            "grade_weights",
            "semester_weights",
            "weighting_mode",
            "achievement",
            "z_score",
            "attendance",
            "non_predictive_components",
            "rounding",
            "score_transform",
            "maximum_score",
        },
        "payload",
    )
    if payload.get("schema_version") != 1:
        raise ValueError("SCORE_RULE schema_version은 1이어야 합니다.")
    if payload.get("evidence_level") not in EVIDENCE_LEVELS:
        raise ValueError("허용되지 않은 evidence_level입니다.")

    inclusion = _payload_mapping(payload, "source_inclusion")
    _payload_exact_keys(
        inclusion,
        {
            "home_grade_1",
            "home_grade_2",
            "home_grade_3_semester_1",
            "home_grade_3_semester_2",
            "vocational_grade",
            "vocational_semester_1",
            "vocational_semester_2",
        },
        "source_inclusion",
    )
    if not all(value is None or isinstance(value, bool) for value in inclusion.values()):
        raise ValueError("source_inclusion 값은 bool 또는 null이어야 합니다.")
    if payload.get("value_direction") not in VALUE_DIRECTIONS:
        raise ValueError("허용되지 않은 value_direction입니다.")

    semester = _payload_mapping(payload, "semester_selection")
    _payload_exact_keys(semester, {"method", "scope", "best_count"}, "semester_selection")
    if semester.get("method") not in SEMESTER_SELECTION_METHODS:
        raise ValueError("허용되지 않은 semester_selection.method입니다.")
    if semester.get("scope") not in SEMESTER_SELECTION_SCOPES:
        raise ValueError("허용되지 않은 semester_selection.scope입니다.")
    if semester.get("scope") == "PER_GRADE" and semester.get("method") != "BEST_N":
        raise ValueError("PER_GRADE 학기 선택 범위는 BEST_N에만 사용할 수 있습니다.")
    _payload_count(semester.get("best_count"), semester.get("method"), "학기")

    subject = _payload_mapping(payload, "subject_selection")
    _payload_exact_keys(
        subject,
        {"method", "best_count", "scope", "credit_weighted", "minimum_semester_credits"},
        "subject_selection",
    )
    if subject.get("method") not in SUBJECT_SELECTION_METHODS:
        raise ValueError("허용되지 않은 subject_selection.method입니다.")
    if subject.get("scope") not in SUBJECT_SCOPES:
        raise ValueError("허용되지 않은 subject_selection.scope입니다.")
    if subject.get("credit_weighted") is not None and not isinstance(
        subject.get("credit_weighted"), bool
    ):
        raise ValueError("credit_weighted는 bool 또는 null이어야 합니다.")
    _payload_count(subject.get("best_count"), subject.get("method"), "과목")
    minimum_semester_credits = _payload_decimal(subject.get("minimum_semester_credits"))
    if minimum_semester_credits is not None and minimum_semester_credits <= 0:
        raise ValueError("minimum_semester_credits는 양수여야 합니다.")
    semester_rounding = _payload_mapping(payload, "semester_rounding")
    _payload_exact_keys(semester_rounding, {"mode", "scale"}, "semester_rounding")
    _validate_optional_rounding(
        semester_rounding.get("mode"),
        semester_rounding.get("scale"),
        "학기 평균",
    )
    grade_rounding = _payload_mapping(payload, "grade_rounding")
    _payload_exact_keys(grade_rounding, {"mode", "scale"}, "grade_rounding")
    _validate_optional_rounding(
        grade_rounding.get("mode"),
        grade_rounding.get("scale"),
        "학년 평균",
    )

    weights_payload = _payload_mapping(payload, "grade_weights")
    _payload_exact_keys(weights_payload, {"grade_1", "grade_2", "grade_3"}, "grade_weights")
    weights = tuple(_payload_decimal(value) for value in weights_payload.values())
    if any(value is not None for value in weights):
        if not all(value is not None for value in weights):
            raise ValueError("학년 가중치는 모두 입력하거나 모두 비워야 합니다.")
        if sum(value for value in weights if value is not None) != Decimal(1):
            raise ValueError("학년 가중치 합계는 1이어야 합니다.")
        if any(value is not None and not Decimal(0) <= value <= Decimal(1) for value in weights):
            raise ValueError("학년 가중치는 0 이상 1 이하여야 합니다.")

    semester_weights_payload = _payload_mapping(payload, "semester_weights")
    _payload_exact_keys(
        semester_weights_payload,
        {
            "grade_1_semester_1",
            "grade_1_semester_2",
            "grade_2_semester_1",
            "grade_2_semester_2",
            "grade_3_semester_1",
            "grade_3_semester_2",
        },
        "semester_weights",
    )
    semester_weights = tuple(_payload_decimal(value) for value in semester_weights_payload.values())
    weighting_mode = payload.get("weighting_mode")
    if weighting_mode not in WEIGHTING_MODES:
        raise ValueError("허용되지 않은 weighting_mode입니다.")
    _validate_weighting_mode(weighting_mode, weights, semester_weights)
    if grade_rounding.get("mode") is not None and weighting_mode != "GRADE_ONLY":
        raise ValueError("학년 평균 반올림은 GRADE_ONLY 가중치에서만 사용할 수 있습니다.")

    achievement = _payload_mapping(payload, "achievement")
    _payload_exact_keys(
        achievement,
        {
            "handling",
            "table_code",
            "source",
            "formula_version",
            "distribution_scale",
            "career_subject_included",
        },
        "achievement",
    )
    if achievement.get("handling") not in ACHIEVEMENT_HANDLING_CODES:
        raise ValueError("허용되지 않은 achievement.handling입니다.")
    if achievement.get("career_subject_included") is not None and not isinstance(
        achievement.get("career_subject_included"), bool
    ):
        raise ValueError("career_subject_included는 bool 또는 null이어야 합니다.")
    _validate_achievement_settings(
        achievement.get("handling"),
        achievement.get("table_code"),
        achievement.get("source"),
        achievement.get("formula_version"),
        achievement.get("distribution_scale"),
    )

    z_score = _payload_mapping(payload, "z_score")
    _payload_exact_keys(
        z_score,
        {
            "policy",
            "source",
            "table_code",
            "formula_version",
            "rounding_mode",
            "rounding_scale",
            "clip_min",
            "clip_max",
        },
        "z_score",
    )
    if z_score.get("policy") not in Z_SCORE_POLICIES:
        raise ValueError("허용되지 않은 z_score.policy입니다.")
    if z_score.get("source") is not None and z_score.get("source") not in Z_SCORE_SOURCES:
        raise ValueError("허용되지 않은 z_score.source입니다.")
    if z_score.get("policy") == "TABLE_LOOKUP" and not z_score.get("table_code"):
        raise ValueError("TABLE_LOOKUP에는 z_score.table_code가 필요합니다.")
    _validate_z_score_settings(
        z_score.get("policy"),
        z_score.get("formula_version"),
        z_score.get("rounding_mode"),
        z_score.get("rounding_scale"),
        _payload_decimal(z_score.get("clip_min")),
        _payload_decimal(z_score.get("clip_max")),
    )

    attendance = _payload_mapping(payload, "attendance")
    _payload_exact_keys(
        attendance,
        {"attendance_included", "table_code", "source", "minor_event_conversion_unit"},
        "attendance",
    )
    if attendance.get("attendance_included") is not None and not isinstance(
        attendance.get("attendance_included"), bool
    ):
        raise ValueError("attendance_included는 bool 또는 null이어야 합니다.")
    _validate_attendance_settings(
        attendance.get("attendance_included"),
        attendance.get("table_code"),
        attendance.get("source"),
        attendance.get("minor_event_conversion_unit"),
    )

    components = _payload_mapping(payload, "non_predictive_components")
    _payload_exact_keys(
        components,
        {"interview_ratio", "practical_ratio"},
        "non_predictive_components",
    )
    ratios = (
        _payload_decimal(components.get("interview_ratio")),
        _payload_decimal(components.get("practical_ratio")),
    )
    if any(value is not None and not Decimal(0) <= value <= Decimal(1) for value in ratios):
        raise ValueError("면접·실기 비율은 0 이상 1 이하여야 합니다.")
    if sum(value or Decimal(0) for value in ratios) > Decimal(1):
        raise ValueError("면접·실기 비율 합계는 1을 넘을 수 없습니다.")

    rounding = _payload_mapping(payload, "rounding")
    _payload_exact_keys(rounding, {"mode", "stage", "scale", "display_scale"}, "rounding")
    if rounding.get("mode") not in ROUNDING_MODES:
        raise ValueError("허용되지 않은 rounding.mode입니다.")
    if rounding.get("stage") not in ROUNDING_STAGES:
        raise ValueError("허용되지 않은 rounding.stage입니다.")
    scale = rounding.get("scale")
    if scale is not None and (
        not isinstance(scale, int) or isinstance(scale, bool) or not 0 <= scale <= 12
    ):
        raise ValueError("rounding.scale은 0~12 정수 또는 null이어야 합니다.")
    display_scale = rounding.get("display_scale")
    if display_scale is not None and (
        not isinstance(display_scale, int)
        or isinstance(display_scale, bool)
        or not 0 <= display_scale <= 12
    ):
        raise ValueError("rounding.display_scale은 0~12 정수 또는 null이어야 합니다.")
    if rounding.get("stage") == "FINAL" and scale is None:
        raise ValueError("FINAL 반올림에는 rounding.scale이 필요합니다.")
    if rounding.get("stage") == "DISPLAY_ONLY" and display_scale is None:
        raise ValueError("DISPLAY_ONLY에는 rounding.display_scale이 필요합니다.")
    transform = _payload_mapping(payload, "score_transform")
    _payload_exact_keys(transform, {"mode", "base", "multiplier"}, "score_transform")
    _validate_score_transform(
        transform.get("mode"),
        _payload_decimal(transform.get("base")),
        _payload_decimal(transform.get("multiplier")),
    )
    maximum_score = _payload_decimal(payload.get("maximum_score"))
    if maximum_score is not None and maximum_score <= 0:
        raise ValueError("maximum_score는 양수여야 합니다.")


def score_rule_definition_from_payload(
    payload: Mapping[str, object],
) -> ScoreRuleDefinition:
    validate_score_rule_payload(payload)
    inclusion = _payload_mapping(payload, "source_inclusion")
    semester = _payload_mapping(payload, "semester_selection")
    subject = _payload_mapping(payload, "subject_selection")
    semester_rounding = _payload_mapping(payload, "semester_rounding")
    grade_rounding = _payload_mapping(payload, "grade_rounding")
    grade_weights = _payload_mapping(payload, "grade_weights")
    semester_weights = _payload_mapping(payload, "semester_weights")
    achievement = _payload_mapping(payload, "achievement")
    z_score = _payload_mapping(payload, "z_score")
    attendance = _payload_mapping(payload, "attendance")
    components = _payload_mapping(payload, "non_predictive_components")
    rounding = _payload_mapping(payload, "rounding")
    transform = _payload_mapping(payload, "score_transform")
    return ScoreRuleDefinition(
        home_grade_1_included=cast(bool | None, inclusion["home_grade_1"]),
        home_grade_2_included=cast(bool | None, inclusion["home_grade_2"]),
        home_grade_3_semester_1_included=cast(bool | None, inclusion["home_grade_3_semester_1"]),
        home_grade_3_semester_2_included=cast(bool | None, inclusion["home_grade_3_semester_2"]),
        vocational_grade_included=cast(bool | None, inclusion["vocational_grade"]),
        vocational_semester_1_included=cast(bool | None, inclusion["vocational_semester_1"]),
        vocational_semester_2_included=cast(bool | None, inclusion["vocational_semester_2"]),
        value_direction=cast(str, payload["value_direction"]),
        semester_selection_method=cast(str, semester["method"]),
        semester_selection_scope=cast(str, semester["scope"]),
        best_semester_count=cast(int | None, semester["best_count"]),
        subject_selection_method=cast(str, subject["method"]),
        best_subject_count=cast(int | None, subject["best_count"]),
        subject_scope=cast(str, subject["scope"]),
        credit_weighted=cast(bool | None, subject["credit_weighted"]),
        minimum_semester_credits=_payload_decimal(subject["minimum_semester_credits"]),
        semester_rounding_mode=cast(str | None, semester_rounding["mode"]),
        semester_rounding_scale=cast(int | None, semester_rounding["scale"]),
        grade_rounding_mode=cast(str | None, grade_rounding["mode"]),
        grade_rounding_scale=cast(int | None, grade_rounding["scale"]),
        grade_weight_1=_payload_decimal(grade_weights["grade_1"]),
        grade_weight_2=_payload_decimal(grade_weights["grade_2"]),
        grade_weight_3=_payload_decimal(grade_weights["grade_3"]),
        semester_weight_1_1=_payload_decimal(semester_weights["grade_1_semester_1"]),
        semester_weight_1_2=_payload_decimal(semester_weights["grade_1_semester_2"]),
        semester_weight_2_1=_payload_decimal(semester_weights["grade_2_semester_1"]),
        semester_weight_2_2=_payload_decimal(semester_weights["grade_2_semester_2"]),
        semester_weight_3_1=_payload_decimal(semester_weights["grade_3_semester_1"]),
        semester_weight_3_2=_payload_decimal(semester_weights["grade_3_semester_2"]),
        weighting_mode=cast(str, payload["weighting_mode"]),
        achievement_handling=cast(str, achievement["handling"]),
        achievement_table_code=cast(str | None, achievement["table_code"]),
        achievement_source=cast(str | None, achievement["source"]),
        achievement_formula_version=cast(str | None, achievement["formula_version"]),
        achievement_distribution_scale=cast(str | None, achievement["distribution_scale"]),
        career_subject_included=cast(bool | None, achievement["career_subject_included"]),
        z_score_policy=cast(str, z_score["policy"]),
        z_score_source=cast(str | None, z_score["source"]),
        z_score_table_code=cast(str | None, z_score["table_code"]),
        z_score_formula_version=cast(str | None, z_score["formula_version"]),
        z_score_rounding_mode=cast(str | None, z_score["rounding_mode"]),
        z_score_rounding_scale=cast(int | None, z_score["rounding_scale"]),
        z_score_clip_min=_payload_decimal(z_score["clip_min"]),
        z_score_clip_max=_payload_decimal(z_score["clip_max"]),
        attendance_included=cast(bool | None, attendance["attendance_included"]),
        attendance_table_code=cast(str | None, attendance["table_code"]),
        attendance_source=cast(str | None, attendance["source"]),
        attendance_minor_event_conversion_unit=cast(
            int | None, attendance["minor_event_conversion_unit"]
        ),
        interview_ratio=_payload_decimal(components["interview_ratio"]),
        practical_ratio=_payload_decimal(components["practical_ratio"]),
        rounding_mode=cast(str, rounding["mode"]),
        rounding_stage=cast(str, rounding["stage"]),
        rounding_scale=cast(int | None, rounding["scale"]),
        display_scale=cast(int | None, rounding["display_scale"]),
        score_transform_mode=cast(str, transform["mode"]),
        score_base=_payload_decimal(transform["base"]),
        score_multiplier=_payload_decimal(transform["multiplier"]),
        maximum_score=_payload_decimal(payload["maximum_score"]),
    )


def parse_z_score_table_csv(data: bytes) -> ZScoreTableCsvResult:
    raw_rows, header_issues = _read_csv(data, Z_SCORE_TABLE_CSV_HEADERS)
    if header_issues:
        return ZScoreTableCsvResult((), header_issues)
    parsed: list[tuple[int, ZScoreTableRow]] = []
    issues: list[CsvValidationIssue] = []
    for row_number, raw in raw_rows:
        row, row_issues = _parse_z_score_row(row_number, raw)
        issues.extend(row_issues)
        if row is not None and not row_issues:
            parsed.append((row_number, row))

    by_table: dict[str, list[tuple[int, ZScoreTableRow]]] = {}
    for item in parsed:
        by_table.setdefault(item[1].table_code, []).append(item)
    overlap_found = False
    for table_rows in by_table.values():
        ordered = sorted(
            table_rows,
            key=lambda item: (
                item[1].z_min is not None,
                item[1].z_min or Decimal(0),
            ),
        )
        previous_max: Decimal | None = None
        previous_max_inclusive = False
        previous_open_ended = False
        for index, (row_number, row) in enumerate(ordered):
            if index > 0 and (
                previous_open_ended
                or row.z_min is None
                or (previous_max is not None and row.z_min < previous_max)
                or (
                    previous_max is not None
                    and row.z_min == previous_max
                    and previous_max_inclusive
                    and row.z_min_inclusive
                )
            ):
                overlap_found = True
                issues.append(
                    CsvValidationIssue(
                        row_number,
                        "z_min",
                        "OVERLAPPING_Z_RANGE",
                        "같은 table_code의 Z점수 구간이 겹칩니다.",
                    )
                )
            previous_max = row.z_max
            previous_max_inclusive = row.z_max_inclusive
            previous_open_ended = row.z_max is None
    if overlap_found:
        return ZScoreTableCsvResult((), tuple(issues))
    return ZScoreTableCsvResult(tuple(row for _, row in parsed), tuple(issues))


def write_z_score_table_csv(rows: Sequence[ZScoreTableRow], *, include_bom: bool = True) -> bytes:
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=Z_SCORE_TABLE_CSV_HEADERS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        values = {
            "schema_version": "1",
            "table_code": row.table_code,
            "z_min": _decimal_text(row.z_min) or "",
            "z_min_inclusive": _boolean_text(row.z_min_inclusive),
            "z_max": _decimal_text(row.z_max) or "",
            "z_max_inclusive": _boolean_text(row.z_max_inclusive),
            "converted_value": str(row.converted_value),
            "evidence_document_id": row.evidence_document_id,
            "evidence_page": str(row.evidence_page),
            "evidence_location": row.evidence_location,
            "source_status": row.source_status,
            "change_reason": row.change_reason,
        }
        _reject_formula_like_export(
            {
                key: value
                for key, value in values.items()
                if key
                not in {
                    "z_min",
                    "z_min_inclusive",
                    "z_max",
                    "z_max_inclusive",
                    "converted_value",
                }
            }
        )
        writer.writerow(values)
    return output.getvalue().encode("utf-8-sig" if include_bom else "utf-8")


def _read_csv(
    data: bytes, expected_headers: tuple[str, ...]
) -> tuple[list[tuple[int, dict[str, str]]], tuple[CsvValidationIssue, ...]]:
    if len(data) > MAX_CSV_BYTES:
        return [], (
            CsvValidationIssue(1, None, "CSV_TOO_LARGE", "CSV는 5 MiB를 넘을 수 없습니다."),
        )
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], (CsvValidationIssue(1, None, "INVALID_ENCODING", "CSV는 UTF-8이어야 합니다."),)
    if "\x00" in text:
        return [], (CsvValidationIssue(1, None, "NUL_BYTE", "NUL 바이트는 허용하지 않습니다."),)
    try:
        rows = list(csv.reader(StringIO(text, newline=""), strict=True))
    except csv.Error as error:
        return [], (CsvValidationIssue(1, None, "MALFORMED_CSV", str(error)),)
    if not rows:
        return [], (CsvValidationIssue(1, None, "EMPTY_CSV", "CSV가 비어 있습니다."),)
    if len(rows) - 1 > MAX_CSV_ROWS:
        return [], (
            CsvValidationIssue(
                1,
                None,
                "TOO_MANY_ROWS",
                f"CSV 데이터 행은 {MAX_CSV_ROWS}개를 넘을 수 없습니다.",
            ),
        )
    header = tuple(rows[0])
    if header != expected_headers or len(set(header)) != len(header):
        return [], (
            CsvValidationIssue(
                1,
                None,
                "HEADER_MISMATCH",
                "헤더가 고정 CSV 양식과 일치하지 않습니다.",
            ),
        )
    output: list[tuple[int, dict[str, str]]] = []
    issues: list[CsvValidationIssue] = []
    for row_number, values in enumerate(rows[1:], start=2):
        if not values or all(not value.strip() for value in values):
            continue
        if len(values) != len(expected_headers):
            issues.append(
                CsvValidationIssue(
                    row_number,
                    None,
                    "COLUMN_COUNT",
                    "행의 열 개수가 고정 양식과 다릅니다.",
                )
            )
            continue
        if any(len(value) > MAX_CELL_LENGTH for value in values):
            issues.append(
                CsvValidationIssue(
                    row_number,
                    None,
                    "CELL_TOO_LONG",
                    f"셀 값은 {MAX_CELL_LENGTH}자를 넘을 수 없습니다.",
                )
            )
            continue
        output.append(
            (
                row_number,
                dict(
                    zip(
                        expected_headers,
                        (value.strip() for value in values),
                        strict=True,
                    )
                ),
            )
        )
    return output, tuple(issues)


def _parse_score_rule_row(
    row_number: int, raw: dict[str, str]
) -> tuple[ManagedScoreRule | None, tuple[CsvValidationIssue, ...]]:
    issues: list[CsvValidationIssue] = []

    def issue(column: str, code: str, message: str) -> None:
        issues.append(CsvValidationIssue(row_number, column, code, message))

    _check_formula_like_values(
        raw,
        row_number,
        issues,
        excluded_columns={
            "z_score_clip_min",
            "z_score_clip_max",
            "score_base",
            "score_multiplier",
        },
    )
    schema_version = _integer(raw["schema_version"], "schema_version", issue)
    if schema_version != 1:
        issue("schema_version", "SCHEMA_VERSION", "schema_version은 1이어야 합니다.")
    admission_year = _integer(raw["admission_year"], "admission_year", issue)
    if admission_year is not None and admission_year < 2000:
        issue("admission_year", "YEAR_RANGE", "admission_year가 허용 범위를 벗어났습니다.")
    required_text = (
        "university_code",
        "university_name",
        "campus_code",
        "admission_round",
        "admission_track_code",
        "admission_track_name",
        "rule_version",
        "change_reason",
    )
    for column in required_text:
        if not raw[column]:
            issue(column, "REQUIRED_VALUE_MISSING", "필수 값이 비어 있습니다.")

    source_status = _choice(raw["source_status"], SOURCE_STATUSES, "source_status", issue)
    evidence_level = _choice(raw["evidence_level"], EVIDENCE_LEVELS, "evidence_level", issue)
    booleans = {column: _boolean(raw[column], column, issue) for column in BOOLEAN_FIELDS}
    if evidence_level != "MANUAL_REVIEW":
        for column, boolean_value in booleans.items():
            if boolean_value is None:
                issue(column, "REQUIRED_VALUE_MISSING", "확정 출처 규칙의 boolean은 필수입니다.")

    semester_method = _choice(
        raw["semester_selection_method"],
        SEMESTER_SELECTION_METHODS,
        "semester_selection_method",
        issue,
    )
    value_direction = _choice(raw["value_direction"], VALUE_DIRECTIONS, "value_direction", issue)
    semester_scope = _choice(
        raw["semester_selection_scope"],
        SEMESTER_SELECTION_SCOPES,
        "semester_selection_scope",
        issue,
    )
    if semester_scope == "PER_GRADE" and semester_method != "BEST_N":
        issue(
            "semester_selection_scope",
            "SELECTION_SCOPE_METHOD",
            "PER_GRADE 학기 선택 범위는 BEST_N에만 사용할 수 있습니다.",
        )
    subject_method = _choice(
        raw["subject_selection_method"],
        SUBJECT_SELECTION_METHODS,
        "subject_selection_method",
        issue,
    )
    subject_scope = _choice(raw["subject_scope"], SUBJECT_SCOPES, "subject_scope", issue)
    achievement = _choice(
        raw["achievement_handling"],
        ACHIEVEMENT_HANDLING_CODES,
        "achievement_handling",
        issue,
    )
    achievement_source = (
        _choice(raw["achievement_source"], Z_SCORE_SOURCES, "achievement_source", issue)
        if raw["achievement_source"]
        else None
    )
    achievement_formula_version = (
        _choice(
            raw["achievement_formula_version"],
            ACHIEVEMENT_FORMULA_VERSIONS,
            "achievement_formula_version",
            issue,
        )
        if raw["achievement_formula_version"]
        else None
    )
    achievement_distribution_scale = (
        _choice(
            raw["achievement_distribution_scale"],
            ACHIEVEMENT_DISTRIBUTION_SCALES,
            "achievement_distribution_scale",
            issue,
        )
        if raw["achievement_distribution_scale"]
        else None
    )
    z_policy = _choice(raw["z_score_policy"], Z_SCORE_POLICIES, "z_score_policy", issue)
    z_source = (
        _choice(raw["z_score_source"], Z_SCORE_SOURCES, "z_score_source", issue)
        if raw["z_score_source"]
        else None
    )
    z_formula_version = (
        _choice(
            raw["z_score_formula_version"],
            Z_SCORE_FORMULA_VERSIONS,
            "z_score_formula_version",
            issue,
        )
        if raw["z_score_formula_version"]
        else None
    )
    z_rounding_mode = (
        _choice(
            raw["z_score_rounding_mode"],
            ROUNDING_MODES,
            "z_score_rounding_mode",
            issue,
        )
        if raw["z_score_rounding_mode"]
        else None
    )
    rounding_mode = _choice(raw["rounding_mode"], ROUNDING_MODES, "rounding_mode", issue)
    semester_rounding_mode = (
        _choice(
            raw["semester_rounding_mode"],
            ROUNDING_MODES,
            "semester_rounding_mode",
            issue,
        )
        if raw["semester_rounding_mode"]
        else None
    )
    grade_rounding_mode = (
        _choice(
            raw["grade_rounding_mode"],
            ROUNDING_MODES,
            "grade_rounding_mode",
            issue,
        )
        if raw["grade_rounding_mode"]
        else None
    )
    weighting_mode = _choice(raw["weighting_mode"], WEIGHTING_MODES, "weighting_mode", issue)
    rounding_stage = _choice(raw["rounding_stage"], ROUNDING_STAGES, "rounding_stage", issue)
    score_transform_mode = _choice(
        raw["score_transform_mode"],
        SCORE_TRANSFORM_MODES,
        "score_transform_mode",
        issue,
    )
    attendance_source = (
        _choice(raw["attendance_source"], Z_SCORE_SOURCES, "attendance_source", issue)
        if raw["attendance_source"]
        else None
    )

    best_semester_count = _optional_integer(
        raw["best_semester_count"], "best_semester_count", issue
    )
    best_subject_count = _optional_integer(raw["best_subject_count"], "best_subject_count", issue)
    minimum_semester_credits = _optional_decimal(
        raw["minimum_semester_credits"], "minimum_semester_credits", issue
    )
    if minimum_semester_credits is not None and minimum_semester_credits <= 0:
        issue(
            "minimum_semester_credits",
            "POSITIVE_DECIMAL_REQUIRED",
            "minimum_semester_credits는 양수여야 합니다.",
        )
    semester_rounding_scale = _optional_integer(
        raw["semester_rounding_scale"], "semester_rounding_scale", issue
    )
    try:
        _validate_optional_rounding(
            semester_rounding_mode,
            semester_rounding_scale,
            "학기 평균",
        )
    except ValueError as error:
        issue("semester_rounding_mode", "SEMESTER_ROUNDING", str(error))
    grade_rounding_scale = _optional_integer(
        raw["grade_rounding_scale"], "grade_rounding_scale", issue
    )
    try:
        _validate_optional_rounding(
            grade_rounding_mode,
            grade_rounding_scale,
            "학년 평균",
        )
    except ValueError as error:
        issue("grade_rounding_mode", "GRADE_ROUNDING", str(error))
    z_rounding_scale = _optional_integer(
        raw["z_score_rounding_scale"], "z_score_rounding_scale", issue
    )
    z_clip_min = _optional_decimal(raw["z_score_clip_min"], "z_score_clip_min", issue)
    z_clip_max = _optional_decimal(raw["z_score_clip_max"], "z_score_clip_max", issue)
    attendance_conversion_unit = _optional_integer(
        raw["attendance_minor_event_conversion_unit"],
        "attendance_minor_event_conversion_unit",
        issue,
    )
    score_base = _optional_decimal(raw["score_base"], "score_base", issue)
    score_multiplier = _optional_decimal(raw["score_multiplier"], "score_multiplier", issue)
    try:
        _validate_score_transform(score_transform_mode, score_base, score_multiplier)
    except ValueError as error:
        issue("score_transform_mode", "SCORE_TRANSFORM", str(error))
    try:
        _validate_z_score_settings(
            z_policy,
            z_formula_version,
            z_rounding_mode,
            z_rounding_scale,
            z_clip_min,
            z_clip_max,
        )
    except ValueError as error:
        issue("z_score_policy", "Z_SCORE_SETTINGS", str(error))
    try:
        _validate_achievement_settings(
            achievement,
            raw["achievement_table_code"] or None,
            achievement_source,
            achievement_formula_version,
            achievement_distribution_scale,
        )
    except ValueError as error:
        issue("achievement_handling", "ACHIEVEMENT_SETTINGS", str(error))
    try:
        _validate_attendance_settings(
            booleans["attendance_included"],
            raw["attendance_table_code"] or None,
            attendance_source,
            attendance_conversion_unit,
        )
    except ValueError as error:
        issue("attendance_included", "ATTENDANCE_SETTINGS", str(error))
    if semester_method in {"FIRST_N", "RECENT_N", "BEST_N"} and (
        best_semester_count is None or best_semester_count <= 0
    ):
        issue(
            "best_semester_count",
            "POSITIVE_INTEGER_REQUIRED",
            "FIRST_N, RECENT_N, BEST_N 학기 선택에는 양의 개수가 필요합니다.",
        )
    if subject_method == "BEST_N" and (best_subject_count is None or best_subject_count <= 0):
        issue(
            "best_subject_count",
            "POSITIVE_INTEGER_REQUIRED",
            "BEST_N 과목 선택에는 양의 개수가 필요합니다.",
        )

    grade_weights = tuple(
        _optional_decimal(raw[column], column, issue)
        for column in ("grade_weight_1", "grade_weight_2", "grade_weight_3")
    )
    if any(value is not None for value in grade_weights):
        if not all(value is not None for value in grade_weights):
            issue(
                "grade_weight_1",
                "GRADE_WEIGHT_COMPLETENESS",
                "학년 가중치는 모두 입력해야 합니다.",
            )
        elif sum(value for value in grade_weights if value is not None) != Decimal("1"):
            issue("grade_weight_1", "GRADE_WEIGHT_SUM", "학년 가중치 합계는 1이어야 합니다.")
    for column, weight_value in zip(
        ("grade_weight_1", "grade_weight_2", "grade_weight_3"),
        grade_weights,
        strict=True,
    ):
        _decimal_range(weight_value, column, issue)

    semester_weight_columns = (
        "semester_weight_1_1",
        "semester_weight_1_2",
        "semester_weight_2_1",
        "semester_weight_2_2",
        "semester_weight_3_1",
        "semester_weight_3_2",
    )
    semester_weights = tuple(
        _optional_decimal(raw[column], column, issue) for column in semester_weight_columns
    )
    for column, weight_value in zip(semester_weight_columns, semester_weights, strict=True):
        _decimal_range(weight_value, column, issue)
    try:
        _validate_weighting_mode(weighting_mode, grade_weights, semester_weights)
    except ValueError as error:
        issue("weighting_mode", "WEIGHT_MODE_CONFLICT", str(error))
    if grade_rounding_mode is not None and weighting_mode != "GRADE_ONLY":
        issue(
            "grade_rounding_mode",
            "GRADE_ROUNDING_WEIGHT_MODE",
            "학년 평균 반올림은 GRADE_ONLY 가중치에서만 사용할 수 있습니다.",
        )

    interview_ratio = _optional_decimal(raw["interview_ratio"], "interview_ratio", issue)
    practical_ratio = _optional_decimal(raw["practical_ratio"], "practical_ratio", issue)
    _decimal_range(interview_ratio, "interview_ratio", issue)
    _decimal_range(practical_ratio, "practical_ratio", issue)
    if (interview_ratio or Decimal(0)) + (practical_ratio or Decimal(0)) > Decimal(1):
        issue("interview_ratio", "RATIO_SUM", "면접·실기 비율 합계는 1을 넘을 수 없습니다.")

    rounding_scale = _optional_integer(raw["rounding_scale"], "rounding_scale", issue)
    if rounding_scale is not None and not 0 <= rounding_scale <= 12:
        issue("rounding_scale", "ROUNDING_SCALE_RANGE", "rounding_scale은 0~12여야 합니다.")
    display_scale = _optional_integer(raw["display_scale"], "display_scale", issue)
    if display_scale is not None and not 0 <= display_scale <= 12:
        issue("display_scale", "DISPLAY_SCALE_RANGE", "display_scale은 0~12여야 합니다.")
    if rounding_stage == "FINAL" and rounding_scale is None:
        issue("rounding_scale", "ROUNDING_SCALE_REQUIRED", "FINAL에는 rounding_scale이 필요합니다.")
    if rounding_stage == "DISPLAY_ONLY" and display_scale is None:
        issue(
            "display_scale",
            "DISPLAY_SCALE_REQUIRED",
            "DISPLAY_ONLY에는 display_scale이 필요합니다.",
        )
    maximum_score = _optional_decimal(raw["maximum_score"], "maximum_score", issue)
    if maximum_score is not None and maximum_score <= 0:
        issue("maximum_score", "POSITIVE_DECIMAL_REQUIRED", "maximum_score는 양수여야 합니다.")

    evidence_page = _optional_integer(raw["evidence_page"], "evidence_page", issue)
    if evidence_page is not None and evidence_page <= 0:
        issue("evidence_page", "POSITIVE_INTEGER_REQUIRED", "근거 페이지는 양수여야 합니다.")
    if evidence_level != "MANUAL_REVIEW":
        for column in ("evidence_document_id", "evidence_page", "evidence_location"):
            if not raw[column]:
                issue(column, "EVIDENCE_REQUIRED", "확정 출처 규칙에는 근거가 필요합니다.")
    if z_policy != "NOT_USED" and z_source is None:
        issue("z_score_source", "Z_SOURCE_REQUIRED", "Z점수 정책에는 출처 코드가 필요합니다.")
    if z_policy == "TABLE_LOOKUP" and not raw["z_score_table_code"]:
        issue("z_score_table_code", "Z_TABLE_REQUIRED", "표 조회 정책에는 table_code가 필요합니다.")
    if z_source == "UNIVERSITY_OFFICIAL" and (
        source_status
        not in {
            "AMENDED_FINAL_GUIDE",
            "FINAL_GUIDE",
            "AMENDED_IMPLEMENTATION_PLAN",
            "IMPLEMENTATION_PLAN",
        }
        or evidence_level != "UNIVERSITY_OFFICIAL"
    ):
        issue(
            "z_score_source",
            "OFFICIAL_SOURCE_REQUIRED",
            "UNIVERSITY_OFFICIAL은 해당 대학의 공식 문서 근거가 필요합니다.",
        )
    for column, component_source in (
        ("achievement_source", achievement_source),
        ("attendance_source", attendance_source),
    ):
        if component_source == "UNIVERSITY_OFFICIAL" and (
            source_status
            not in {
                "AMENDED_FINAL_GUIDE",
                "FINAL_GUIDE",
                "AMENDED_IMPLEMENTATION_PLAN",
                "IMPLEMENTATION_PLAN",
            }
            or evidence_level != "UNIVERSITY_OFFICIAL"
        ):
            issue(
                column,
                "OFFICIAL_SOURCE_REQUIRED",
                "UNIVERSITY_OFFICIAL은 해당 대학의 공식 문서 근거가 필요합니다.",
            )
    if evidence_level == "UNIVERSITY_OFFICIAL" and source_status not in {
        "AMENDED_FINAL_GUIDE",
        "FINAL_GUIDE",
        "AMENDED_IMPLEMENTATION_PLAN",
        "IMPLEMENTATION_PLAN",
    }:
        issue(
            "evidence_level",
            "OFFICIAL_SOURCE_REQUIRED",
            "UNIVERSITY_OFFICIAL 근거 수준은 해당 대학의 공식 문서가 필요합니다.",
        )
    if evidence_level == "COMMON_OFFICIAL" and source_status != "COMMON_STANDARD":
        issue(
            "evidence_level",
            "COMMON_SOURCE_REQUIRED",
            "COMMON_OFFICIAL 근거 수준은 공통 공식 자료가 필요합니다.",
        )

    if issues or admission_year is None:
        return None, tuple(issues)
    definition = ScoreRuleDefinition(
        home_grade_1_included=booleans["home_grade_1_included"],
        home_grade_2_included=booleans["home_grade_2_included"],
        home_grade_3_semester_1_included=booleans["home_grade_3_semester_1_included"],
        home_grade_3_semester_2_included=booleans["home_grade_3_semester_2_included"],
        vocational_grade_included=booleans["vocational_grade_included"],
        vocational_semester_1_included=booleans["vocational_semester_1_included"],
        vocational_semester_2_included=booleans["vocational_semester_2_included"],
        value_direction=value_direction,
        semester_selection_method=semester_method,
        semester_selection_scope=semester_scope,
        best_semester_count=best_semester_count,
        subject_selection_method=subject_method,
        best_subject_count=best_subject_count,
        subject_scope=subject_scope,
        credit_weighted=booleans["credit_weighted"],
        minimum_semester_credits=minimum_semester_credits,
        semester_rounding_mode=semester_rounding_mode,
        semester_rounding_scale=semester_rounding_scale,
        grade_rounding_mode=grade_rounding_mode,
        grade_rounding_scale=grade_rounding_scale,
        grade_weight_1=grade_weights[0],
        grade_weight_2=grade_weights[1],
        grade_weight_3=grade_weights[2],
        semester_weight_1_1=semester_weights[0],
        semester_weight_1_2=semester_weights[1],
        semester_weight_2_1=semester_weights[2],
        semester_weight_2_2=semester_weights[3],
        semester_weight_3_1=semester_weights[4],
        semester_weight_3_2=semester_weights[5],
        weighting_mode=weighting_mode,
        achievement_handling=achievement,
        achievement_table_code=raw["achievement_table_code"] or None,
        achievement_source=achievement_source,
        achievement_formula_version=achievement_formula_version,
        achievement_distribution_scale=achievement_distribution_scale,
        career_subject_included=booleans["career_subject_included"],
        z_score_policy=z_policy,
        z_score_source=z_source,
        z_score_table_code=raw["z_score_table_code"] or None,
        z_score_formula_version=z_formula_version,
        z_score_rounding_mode=z_rounding_mode,
        z_score_rounding_scale=z_rounding_scale,
        z_score_clip_min=z_clip_min,
        z_score_clip_max=z_clip_max,
        attendance_included=booleans["attendance_included"],
        attendance_table_code=raw["attendance_table_code"] or None,
        attendance_source=attendance_source,
        attendance_minor_event_conversion_unit=attendance_conversion_unit,
        interview_ratio=interview_ratio,
        practical_ratio=practical_ratio,
        rounding_mode=rounding_mode,
        rounding_stage=rounding_stage,
        rounding_scale=rounding_scale,
        display_scale=display_scale,
        score_transform_mode=score_transform_mode,
        score_base=score_base,
        score_multiplier=score_multiplier,
        maximum_score=maximum_score,
    )
    return (
        ManagedScoreRule(
            identity=RuleIdentity(
                admission_year=admission_year,
                university_code=raw["university_code"],
                campus_code=raw["campus_code"],
                admission_round=raw["admission_round"],
                admission_track_code=raw["admission_track_code"],
            ),
            university_name=raw["university_name"],
            admission_track_name=raw["admission_track_name"],
            rule_version=raw["rule_version"],
            definition=definition,
            evidence_document_id=raw["evidence_document_id"] or None,
            evidence_page=evidence_page,
            evidence_location=raw["evidence_location"] or None,
            evidence_level=evidence_level,
            source_status=source_status,
            change_reason=raw["change_reason"],
            administrator_note=raw["administrator_note"] or None,
        ),
        (),
    )


def _parse_z_score_row(
    row_number: int, raw: dict[str, str]
) -> tuple[ZScoreTableRow | None, tuple[CsvValidationIssue, ...]]:
    issues: list[CsvValidationIssue] = []

    def issue(column: str, code: str, message: str) -> None:
        issues.append(CsvValidationIssue(row_number, column, code, message))

    _check_formula_like_values(
        raw,
        row_number,
        issues,
        excluded_columns={
            "z_min",
            "z_min_inclusive",
            "z_max",
            "z_max_inclusive",
            "converted_value",
        },
    )
    if _integer(raw["schema_version"], "schema_version", issue) != 1:
        issue("schema_version", "SCHEMA_VERSION", "schema_version은 1이어야 합니다.")
    for column in (
        "table_code",
        "evidence_document_id",
        "evidence_page",
        "evidence_location",
        "source_status",
        "change_reason",
    ):
        if not raw[column]:
            issue(column, "REQUIRED_VALUE_MISSING", "필수 값이 비어 있습니다.")
    z_min = _optional_decimal(raw["z_min"], "z_min", issue)
    z_min_inclusive = _boolean(raw["z_min_inclusive"], "z_min_inclusive", issue)
    z_max = _optional_decimal(raw["z_max"], "z_max", issue)
    z_max_inclusive = _boolean(raw["z_max_inclusive"], "z_max_inclusive", issue)
    converted = _decimal(raw["converted_value"], "converted_value", issue)
    evidence_page = _integer(raw["evidence_page"], "evidence_page", issue)
    source_status = _choice(raw["source_status"], SOURCE_STATUSES, "source_status", issue)
    if z_min is not None and z_max is not None and z_min >= z_max:
        issue("z_min", "Z_RANGE_ORDER", "Z점수 하한은 상한보다 작아야 합니다.")
    if z_min_inclusive is None or z_max_inclusive is None:
        issue("z_min_inclusive", "BOOLEAN_REQUIRED", "Z점수 경계 포함 여부가 필요합니다.")
    if evidence_page is not None and evidence_page <= 0:
        issue("evidence_page", "POSITIVE_INTEGER_REQUIRED", "근거 페이지는 양수여야 합니다.")
    if (
        issues
        or converted is None
        or evidence_page is None
        or z_min_inclusive is None
        or z_max_inclusive is None
    ):
        return None, tuple(issues)
    return (
        ZScoreTableRow(
            table_code=raw["table_code"],
            z_min=z_min,
            z_min_inclusive=z_min_inclusive,
            z_max=z_max,
            z_max_inclusive=z_max_inclusive,
            converted_value=converted,
            evidence_document_id=raw["evidence_document_id"],
            evidence_page=evidence_page,
            evidence_location=raw["evidence_location"],
            source_status=source_status,
            change_reason=raw["change_reason"],
        ),
        (),
    )


def _boolean(value: str, column: str, issue: Callable[[str, str, str], None]) -> bool | None:
    if not value:
        return None
    if value not in {"TRUE", "FALSE"}:
        issue(column, "BOOLEAN_CODE", "boolean은 TRUE 또는 FALSE만 허용합니다.")
        return None
    return value == "TRUE"


def _choice(
    value: str,
    allowed: set[str],
    column: str,
    issue: Callable[[str, str, str], None],
) -> str:
    if value not in allowed:
        issue(column, "CHOICE_CODE", f"허용되지 않은 코드입니다: {value}")
    return value


def _integer(value: str, column: str, issue: Callable[[str, str, str], None]) -> int | None:
    if not value:
        issue(column, "REQUIRED_VALUE_MISSING", "정수 값이 비어 있습니다.")
        return None
    try:
        return int(value)
    except ValueError:
        issue(column, "INTEGER_FORMAT", "정수 형식이 아닙니다.")
        return None


def _optional_integer(
    value: str, column: str, issue: Callable[[str, str, str], None]
) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        issue(column, "INTEGER_FORMAT", "정수 형식이 아닙니다.")
        return None


def _decimal(value: str, column: str, issue: Callable[[str, str, str], None]) -> Decimal | None:
    if not value:
        issue(column, "REQUIRED_VALUE_MISSING", "Decimal 값이 비어 있습니다.")
        return None
    return _decimal_value(value, column, issue)


def _optional_decimal(
    value: str, column: str, issue: Callable[[str, str, str], None]
) -> Decimal | None:
    if not value:
        return None
    return _decimal_value(value, column, issue)


def _decimal_value(
    value: str, column: str, issue: Callable[[str, str, str], None]
) -> Decimal | None:
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        issue(column, "DECIMAL_FORMAT", "Decimal 형식이 아닙니다.")
        return None
    if not parsed.is_finite():
        issue(column, "DECIMAL_FORMAT", "유한한 Decimal만 허용합니다.")
        return None
    return parsed


def _decimal_range(
    value: Decimal | None,
    column: str,
    issue: Callable[[str, str, str], None],
) -> None:
    if value is not None and not Decimal(0) <= value <= Decimal(1):
        issue(column, "DECIMAL_RANGE", "비율은 0 이상 1 이하여야 합니다.")


def _check_formula_like_values(
    raw: dict[str, str],
    row_number: int,
    issues: list[CsvValidationIssue],
    *,
    excluded_columns: set[str],
) -> None:
    for column, value in raw.items():
        if column not in excluded_columns and value.startswith(("=", "+", "-", "@")):
            issues.append(
                CsvValidationIssue(
                    row_number,
                    column,
                    "FORMULA_LIKE_VALUE",
                    "실행 가능한 수식처럼 보이는 값은 허용하지 않습니다.",
                )
            )


def _score_rule_to_csv_values(row: ManagedScoreRule) -> dict[str, str]:
    definition = row.definition
    values = {
        "schema_version": "1",
        "admission_year": str(row.identity.admission_year),
        "university_code": row.identity.university_code,
        "university_name": row.university_name,
        "campus_code": row.identity.campus_code,
        "admission_round": row.identity.admission_round,
        "admission_track_code": row.identity.admission_track_code,
        "admission_track_name": row.admission_track_name,
        "rule_version": row.rule_version,
        "value_direction": definition.value_direction,
        "semester_selection_method": definition.semester_selection_method,
        "semester_selection_scope": definition.semester_selection_scope,
        "best_semester_count": _optional_text(definition.best_semester_count),
        "subject_selection_method": definition.subject_selection_method,
        "best_subject_count": _optional_text(definition.best_subject_count),
        "subject_scope": definition.subject_scope,
        "minimum_semester_credits": _decimal_text(definition.minimum_semester_credits) or "",
        "semester_rounding_mode": definition.semester_rounding_mode or "",
        "semester_rounding_scale": _optional_text(definition.semester_rounding_scale),
        "grade_rounding_mode": definition.grade_rounding_mode or "",
        "grade_rounding_scale": _optional_text(definition.grade_rounding_scale),
        "weighting_mode": definition.weighting_mode,
        "grade_weight_1": _decimal_text(definition.grade_weight_1) or "",
        "grade_weight_2": _decimal_text(definition.grade_weight_2) or "",
        "grade_weight_3": _decimal_text(definition.grade_weight_3) or "",
        "semester_weight_1_1": _decimal_text(definition.semester_weight_1_1) or "",
        "semester_weight_1_2": _decimal_text(definition.semester_weight_1_2) or "",
        "semester_weight_2_1": _decimal_text(definition.semester_weight_2_1) or "",
        "semester_weight_2_2": _decimal_text(definition.semester_weight_2_2) or "",
        "semester_weight_3_1": _decimal_text(definition.semester_weight_3_1) or "",
        "semester_weight_3_2": _decimal_text(definition.semester_weight_3_2) or "",
        "achievement_handling": definition.achievement_handling,
        "achievement_table_code": definition.achievement_table_code or "",
        "achievement_source": definition.achievement_source or "",
        "achievement_formula_version": definition.achievement_formula_version or "",
        "achievement_distribution_scale": definition.achievement_distribution_scale or "",
        "z_score_policy": definition.z_score_policy,
        "z_score_source": definition.z_score_source or "",
        "z_score_table_code": definition.z_score_table_code or "",
        "z_score_formula_version": definition.z_score_formula_version or "",
        "z_score_rounding_mode": definition.z_score_rounding_mode or "",
        "z_score_rounding_scale": _optional_text(definition.z_score_rounding_scale),
        "z_score_clip_min": _decimal_text(definition.z_score_clip_min) or "",
        "z_score_clip_max": _decimal_text(definition.z_score_clip_max) or "",
        "attendance_table_code": definition.attendance_table_code or "",
        "attendance_source": definition.attendance_source or "",
        "attendance_minor_event_conversion_unit": _optional_text(
            definition.attendance_minor_event_conversion_unit
        ),
        "interview_ratio": _decimal_text(definition.interview_ratio) or "",
        "practical_ratio": _decimal_text(definition.practical_ratio) or "",
        "rounding_mode": definition.rounding_mode,
        "rounding_stage": definition.rounding_stage,
        "rounding_scale": _optional_text(definition.rounding_scale),
        "display_scale": _optional_text(definition.display_scale),
        "score_transform_mode": definition.score_transform_mode,
        "score_base": _decimal_text(definition.score_base) or "",
        "score_multiplier": _decimal_text(definition.score_multiplier) or "",
        "maximum_score": _decimal_text(definition.maximum_score) or "",
        "evidence_document_id": row.evidence_document_id or "",
        "evidence_page": _optional_text(row.evidence_page),
        "evidence_location": row.evidence_location or "",
        "evidence_level": row.evidence_level,
        "source_status": row.source_status,
        "change_reason": row.change_reason,
        "administrator_note": row.administrator_note or "",
    }
    boolean_values = {
        "home_grade_1_included": definition.home_grade_1_included,
        "home_grade_2_included": definition.home_grade_2_included,
        "home_grade_3_semester_1_included": definition.home_grade_3_semester_1_included,
        "home_grade_3_semester_2_included": definition.home_grade_3_semester_2_included,
        "vocational_grade_included": definition.vocational_grade_included,
        "vocational_semester_1_included": definition.vocational_semester_1_included,
        "vocational_semester_2_included": definition.vocational_semester_2_included,
        "credit_weighted": definition.credit_weighted,
        "career_subject_included": definition.career_subject_included,
        "attendance_included": definition.attendance_included,
    }
    values.update({key: _boolean_text(value) for key, value in boolean_values.items()})
    return {header: values[header] for header in SCORE_RULE_CSV_HEADERS}


def _reject_formula_like_export(values: dict[str, str]) -> None:
    for column, value in values.items():
        if value.startswith(("=", "+", "-", "@")):
            raise ValueError(f"{column}에 수식처럼 보이는 값을 내보낼 수 없습니다.")


def _boolean_text(value: bool | None) -> str:
    if value is None:
        return ""
    return "TRUE" if value else "FALSE"


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _optional_text(value: int | None) -> str:
    return "" if value is None else str(value)


def _payload_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key}는 객체여야 합니다.")
    return value


def _payload_exact_keys(payload: Mapping[str, object], expected: set[str], path: str) -> None:
    if set(payload) != expected:
        raise ValueError(f"{path} 필드가 canonical SCORE_RULE 계약과 다릅니다.")


def _payload_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Decimal payload 값은 문자열 또는 null이어야 합니다.")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("Decimal payload 형식이 잘못되었습니다.") from error
    if not parsed.is_finite():
        raise ValueError("Decimal payload는 유한값이어야 합니다.")
    return parsed


def _payload_count(value: object, method: object, label: str) -> None:
    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
        raise ValueError(f"{label} 선택 개수는 양의 정수 또는 null이어야 합니다.")
    count_methods = {"BEST_N"}
    if label == "학기":
        count_methods.update({"FIRST_N", "RECENT_N"})
    if method in count_methods and value is None:
        raise ValueError(f"{method} {label} 선택에는 개수가 필요합니다.")


def _validate_achievement_settings(
    handling: object,
    table_code: object,
    source: object,
    formula_version: object,
    distribution_scale: object,
) -> None:
    if source is not None and source not in Z_SCORE_SOURCES:
        raise ValueError("허용되지 않은 achievement.source입니다.")
    if distribution_scale is not None and distribution_scale not in ACHIEVEMENT_DISTRIBUTION_SCALES:
        raise ValueError("허용되지 않은 achievement.distribution_scale입니다.")
    if formula_version is not None and formula_version not in ACHIEVEMENT_FORMULA_VERSIONS:
        raise ValueError("허용되지 않은 achievement.formula_version입니다.")
    if handling == "EXCLUDE" and any(
        value is not None for value in (table_code, source, formula_version, distribution_scale)
    ):
        raise ValueError("EXCLUDE 성취도 규칙에는 표·출처·분포 척도를 지정할 수 없습니다.")
    if handling == "GRADE_TABLE" and (
        not table_code
        or source is None
        or formula_version != "TABLE_LOOKUP_V1"
        or distribution_scale is not None
    ):
        raise ValueError("GRADE_TABLE에는 표 코드와 출처가 필요하며 분포 척도는 비워야 합니다.")
    if handling == "DISTRIBUTION" and (
        not table_code or source is None or formula_version is None or distribution_scale is None
    ):
        raise ValueError("DISTRIBUTION에는 표 코드·출처·분포 척도가 필요합니다.")
    if formula_version == "CUMULATIVE_DISTRIBUTION_GRADE_V1" and distribution_scale != "PERCENT":
        raise ValueError("누적분포 등급 공식은 PERCENT 척도를 사용해야 합니다.")


def _validate_attendance_settings(
    included: object,
    table_code: object,
    source: object,
    conversion_unit: object,
) -> None:
    if source is not None and source not in Z_SCORE_SOURCES:
        raise ValueError("허용되지 않은 attendance.source입니다.")
    if conversion_unit is not None and (
        not isinstance(conversion_unit, int)
        or isinstance(conversion_unit, bool)
        or conversion_unit <= 0
    ):
        raise ValueError("attendance.minor_event_conversion_unit은 양의 정수여야 합니다.")
    if included is False and any(
        value is not None for value in (table_code, source, conversion_unit)
    ):
        raise ValueError("출결 미반영 규칙에는 표·출처·환산 단위를 지정할 수 없습니다.")
    if included is True and (not table_code or source is None or conversion_unit is None):
        raise ValueError("출결 반영 규칙에는 표 코드·출처·환산 단위가 필요합니다.")


def _validate_z_score_settings(
    policy: object,
    formula_version: object,
    rounding_mode: object,
    rounding_scale: object,
    clip_min: Decimal | None,
    clip_max: Decimal | None,
) -> None:
    if policy == "NOT_USED":
        if any(
            value is not None
            for value in (formula_version, rounding_mode, rounding_scale, clip_min, clip_max)
        ):
            raise ValueError("NOT_USED에는 Z점수 계산 설정을 입력할 수 없습니다.")
        return
    if policy == "MANUAL_REVIEW":
        return
    if formula_version != "STANDARD_Z_V1":
        raise ValueError("자동 Z점수 계산에는 STANDARD_Z_V1 공식 버전이 필요합니다.")
    if rounding_mode not in ROUNDING_MODES or rounding_mode == "MANUAL_REVIEW":
        raise ValueError("자동 Z점수 계산에는 확정 반올림 방식이 필요합니다.")
    if (
        not isinstance(rounding_scale, int)
        or isinstance(rounding_scale, bool)
        or not 0 <= rounding_scale <= 12
    ):
        raise ValueError("Z점수 반올림 자릿수는 0~12 정수여야 합니다.")
    if (clip_min is None) != (clip_max is None):
        raise ValueError("Z점수 절단 하한과 상한은 함께 입력해야 합니다.")
    if clip_min is not None and clip_max is not None and clip_min >= clip_max:
        raise ValueError("Z점수 절단 하한은 상한보다 작아야 합니다.")


def _validate_optional_rounding(mode: object, scale: object, label: str) -> None:
    if mode is None and scale is None:
        return
    if mode not in ROUNDING_MODES or mode == "MANUAL_REVIEW":
        raise ValueError(f"{label}에는 확정 반올림 방식이 필요합니다.")
    if not isinstance(scale, int) or isinstance(scale, bool) or not 0 <= scale <= 12:
        raise ValueError(f"{label} 반올림 자릿수는 0~12 정수여야 합니다.")


def _validate_score_transform(
    mode: object, base: Decimal | None, multiplier: Decimal | None
) -> None:
    if mode == "IDENTITY":
        if base is not None or multiplier is not None:
            raise ValueError("IDENTITY에는 base와 multiplier를 입력할 수 없습니다.")
        return
    if mode == "LINEAR":
        if base is None or multiplier is None:
            raise ValueError("LINEAR에는 base와 multiplier가 모두 필요합니다.")
        return
    if mode == "MANUAL_REVIEW":
        return
    raise ValueError("허용되지 않은 score_transform.mode입니다.")


def _validate_weighting_mode(
    mode: object,
    grade_weights: tuple[Decimal | None, ...],
    semester_weights: tuple[Decimal | None, ...],
) -> None:
    _validate_weight_range(grade_weights, "학년")
    _validate_weight_range(semester_weights, "학기")
    has_grade = any(value is not None for value in grade_weights)
    has_semester = any(value is not None for value in semester_weights)
    if mode == "EQUAL":
        if has_grade or has_semester:
            raise ValueError("EQUAL은 학년·학기 가중치를 입력할 수 없습니다.")
        return
    if mode == "GRADE_ONLY":
        _require_complete_sum(grade_weights, "학년")
        if has_semester:
            raise ValueError("GRADE_ONLY는 학기 가중치를 입력할 수 없습니다.")
        return
    if mode == "GLOBAL_SEMESTER":
        if has_grade:
            raise ValueError("GLOBAL_SEMESTER는 학년 가중치를 입력할 수 없습니다.")
        if not has_semester or sum(
            (value for value in semester_weights if value is not None), Decimal(0)
        ) != Decimal(1):
            raise ValueError("GLOBAL_SEMESTER 학기 가중치 합계는 1이어야 합니다.")
        return
    if mode == "GRADE_WITHIN_SEMESTER":
        _require_complete_sum(grade_weights, "학년")
        if not has_semester:
            raise ValueError("GRADE_WITHIN_SEMESTER에는 학년 내부 학기 가중치가 필요합니다.")
        for index in range(0, len(semester_weights), 2):
            pair = semester_weights[index : index + 2]
            if any(value is not None for value in pair):
                _require_complete_sum(pair, f"{index // 2 + 1}학년 내부 학기")
        return
    raise ValueError("허용되지 않은 weighting_mode입니다.")


def _validate_weight_range(values: tuple[Decimal | None, ...], label: str) -> None:
    if any(value is not None and not Decimal(0) <= value <= Decimal(1) for value in values):
        raise ValueError(f"{label} 가중치는 0 이상 1 이하여야 합니다.")


def _require_complete_sum(values: tuple[Decimal | None, ...], label: str) -> None:
    if not all(value is not None for value in values):
        raise ValueError(f"{label} 가중치는 모두 입력해야 합니다.")
    if sum((value for value in values if value is not None), Decimal(0)) != Decimal(1):
        raise ValueError(f"{label} 가중치 합계는 1이어야 합니다.")


__all__ = [
    "CsvValidationIssue",
    "ManagedScoreRule",
    "RuleIdentity",
    "SCORE_RULE_CSV_HEADERS",
    "ScoreRuleCsvResult",
    "ScoreRuleDefinition",
    "Z_SCORE_TABLE_CSV_HEADERS",
    "ZScoreTableCsvResult",
    "ZScoreTableRow",
    "parse_score_rule_csv",
    "parse_z_score_table_csv",
    "score_rule_definition_from_payload",
    "score_rule_to_payload",
    "validate_score_rule_payload",
    "write_score_rule_csv",
    "write_z_score_table_csv",
]
