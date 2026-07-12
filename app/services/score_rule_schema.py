from __future__ import annotations

import csv
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import StringIO

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
    "semester_selection_method",
    "best_semester_count",
    "subject_selection_method",
    "best_subject_count",
    "subject_scope",
    "credit_weighted",
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
    "career_subject_included",
    "z_score_policy",
    "z_score_source",
    "z_score_table_code",
    "attendance_included",
    "interview_ratio",
    "practical_ratio",
    "rounding_mode",
    "rounding_scale",
    "maximum_score",
    "evidence_document_id",
    "evidence_page",
    "evidence_location",
    "source_status",
    "change_reason",
    "administrator_note",
)

Z_SCORE_TABLE_CSV_HEADERS = (
    "schema_version",
    "table_code",
    "z_min_exclusive",
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
SUBJECT_SELECTION_METHODS = {"ALL", "BEST_N", "SCOPE", "MANUAL_REVIEW"}
SUBJECT_SCOPES = {
    "ALL",
    "GENERAL_SUBJECTS",
    "CAREER_SUBJECTS",
    "SPECIFIED",
    "MANUAL_REVIEW",
}
ACHIEVEMENT_HANDLING_CODES = {"EXCLUDE", "GRADE_TABLE", "DISTRIBUTION", "MANUAL_REVIEW"}
Z_SCORE_POLICIES = {"NOT_USED", "INTERNAL_CALCULATION", "TABLE_LOOKUP", "MANUAL_REVIEW"}
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
    semester_selection_method: str
    best_semester_count: int | None
    subject_selection_method: str
    best_subject_count: int | None
    subject_scope: str
    credit_weighted: bool | None
    grade_weight_1: Decimal | None
    grade_weight_2: Decimal | None
    grade_weight_3: Decimal | None
    semester_weight_1_1: Decimal | None
    semester_weight_1_2: Decimal | None
    semester_weight_2_1: Decimal | None
    semester_weight_2_2: Decimal | None
    semester_weight_3_1: Decimal | None
    semester_weight_3_2: Decimal | None
    achievement_handling: str
    career_subject_included: bool | None
    z_score_policy: str
    z_score_source: str | None
    z_score_table_code: str | None
    attendance_included: bool | None
    interview_ratio: Decimal | None
    practical_ratio: Decimal | None
    rounding_mode: str
    rounding_scale: int | None
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
    z_min_exclusive: Decimal | None
    z_max_inclusive: Decimal | None
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
        _reject_formula_like_export(values)
        writer.writerow(values)
    return output.getvalue().encode("utf-8-sig" if include_bom else "utf-8")


def score_rule_to_payload(row: ManagedScoreRule) -> dict[str, object]:
    definition = row.definition
    return {
        "schema_version": 1,
        "source_inclusion": {
            "home_grade_1": definition.home_grade_1_included,
            "home_grade_2": definition.home_grade_2_included,
            "home_grade_3_semester_1": definition.home_grade_3_semester_1_included,
            "home_grade_3_semester_2": definition.home_grade_3_semester_2_included,
            "vocational_grade": definition.vocational_grade_included,
            "vocational_semester_1": definition.vocational_semester_1_included,
            "vocational_semester_2": definition.vocational_semester_2_included,
        },
        "semester_selection": {
            "method": definition.semester_selection_method,
            "best_count": definition.best_semester_count,
        },
        "subject_selection": {
            "method": definition.subject_selection_method,
            "best_count": definition.best_subject_count,
            "scope": definition.subject_scope,
            "credit_weighted": definition.credit_weighted,
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
        "achievement": {
            "handling": definition.achievement_handling,
            "career_subject_included": definition.career_subject_included,
        },
        "z_score": {
            "policy": definition.z_score_policy,
            "source": definition.z_score_source,
            "table_code": definition.z_score_table_code,
        },
        "non_predictive_components": {
            "attendance_included": definition.attendance_included,
            "interview_ratio": _decimal_text(definition.interview_ratio),
            "practical_ratio": _decimal_text(definition.practical_ratio),
        },
        "rounding": {
            "mode": definition.rounding_mode,
            "scale": definition.rounding_scale,
        },
        "maximum_score": _decimal_text(definition.maximum_score),
    }


def validate_score_rule_payload(payload: Mapping[str, object]) -> None:
    _payload_exact_keys(
        payload,
        {
            "schema_version",
            "source_inclusion",
            "semester_selection",
            "subject_selection",
            "grade_weights",
            "semester_weights",
            "achievement",
            "z_score",
            "non_predictive_components",
            "rounding",
            "maximum_score",
        },
        "payload",
    )
    if payload.get("schema_version") != 1:
        raise ValueError("SCORE_RULE schema_version은 1이어야 합니다.")

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

    semester = _payload_mapping(payload, "semester_selection")
    _payload_exact_keys(semester, {"method", "best_count"}, "semester_selection")
    if semester.get("method") not in SEMESTER_SELECTION_METHODS:
        raise ValueError("허용되지 않은 semester_selection.method입니다.")
    _payload_count(semester.get("best_count"), semester.get("method"), "학기")

    subject = _payload_mapping(payload, "subject_selection")
    _payload_exact_keys(
        subject,
        {"method", "best_count", "scope", "credit_weighted"},
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
    _validate_weight_set(semester_weights, "학기")
    if any(value is not None for value in weights) and any(
        value is not None for value in semester_weights
    ):
        raise ValueError("학년 가중치와 학기 가중치는 동시에 사용할 수 없습니다.")

    achievement = _payload_mapping(payload, "achievement")
    _payload_exact_keys(achievement, {"handling", "career_subject_included"}, "achievement")
    if achievement.get("handling") not in ACHIEVEMENT_HANDLING_CODES:
        raise ValueError("허용되지 않은 achievement.handling입니다.")
    if achievement.get("career_subject_included") is not None and not isinstance(
        achievement.get("career_subject_included"), bool
    ):
        raise ValueError("career_subject_included는 bool 또는 null이어야 합니다.")

    z_score = _payload_mapping(payload, "z_score")
    _payload_exact_keys(z_score, {"policy", "source", "table_code"}, "z_score")
    if z_score.get("policy") not in Z_SCORE_POLICIES:
        raise ValueError("허용되지 않은 z_score.policy입니다.")
    if z_score.get("source") is not None and z_score.get("source") not in Z_SCORE_SOURCES:
        raise ValueError("허용되지 않은 z_score.source입니다.")
    if z_score.get("policy") == "TABLE_LOOKUP" and not z_score.get("table_code"):
        raise ValueError("TABLE_LOOKUP에는 z_score.table_code가 필요합니다.")

    components = _payload_mapping(payload, "non_predictive_components")
    _payload_exact_keys(
        components,
        {"attendance_included", "interview_ratio", "practical_ratio"},
        "non_predictive_components",
    )
    if components.get("attendance_included") is not None and not isinstance(
        components.get("attendance_included"), bool
    ):
        raise ValueError("attendance_included는 bool 또는 null이어야 합니다.")
    ratios = (
        _payload_decimal(components.get("interview_ratio")),
        _payload_decimal(components.get("practical_ratio")),
    )
    if any(value is not None and not Decimal(0) <= value <= Decimal(1) for value in ratios):
        raise ValueError("면접·실기 비율은 0 이상 1 이하여야 합니다.")
    if sum(value or Decimal(0) for value in ratios) > Decimal(1):
        raise ValueError("면접·실기 비율 합계는 1을 넘을 수 없습니다.")

    rounding = _payload_mapping(payload, "rounding")
    _payload_exact_keys(rounding, {"mode", "scale"}, "rounding")
    if rounding.get("mode") not in ROUNDING_MODES:
        raise ValueError("허용되지 않은 rounding.mode입니다.")
    scale = rounding.get("scale")
    if scale is not None and (
        not isinstance(scale, int) or isinstance(scale, bool) or not 0 <= scale <= 12
    ):
        raise ValueError("rounding.scale은 0~12 정수 또는 null이어야 합니다.")
    maximum_score = _payload_decimal(payload.get("maximum_score"))
    if maximum_score is not None and maximum_score <= 0:
        raise ValueError("maximum_score는 양수여야 합니다.")


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
                item[1].z_min_exclusive is not None,
                item[1].z_min_exclusive or Decimal(0),
            ),
        )
        previous_max: Decimal | None = None
        previous_open_ended = False
        for index, (row_number, row) in enumerate(ordered):
            if index > 0 and (
                previous_open_ended
                or row.z_min_exclusive is None
                or (previous_max is not None and row.z_min_exclusive < previous_max)
            ):
                overlap_found = True
                issues.append(
                    CsvValidationIssue(
                        row_number,
                        "z_min_exclusive",
                        "OVERLAPPING_Z_RANGE",
                        "같은 table_code의 Z점수 구간이 겹칩니다.",
                    )
                )
            previous_max = row.z_max_inclusive
            previous_open_ended = row.z_max_inclusive is None
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
            "z_min_exclusive": _decimal_text(row.z_min_exclusive) or "",
            "z_max_inclusive": _decimal_text(row.z_max_inclusive) or "",
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
                if key not in {"z_min_exclusive", "z_max_inclusive", "converted_value"}
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

    _check_formula_like_values(raw, row_number, issues, excluded_columns=set())
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
    booleans = {column: _boolean(raw[column], column, issue) for column in BOOLEAN_FIELDS}
    if source_status != "MANUAL_REVIEW":
        for column, boolean_value in booleans.items():
            if boolean_value is None:
                issue(column, "REQUIRED_VALUE_MISSING", "확정 출처 규칙의 boolean은 필수입니다.")

    semester_method = _choice(
        raw["semester_selection_method"],
        SEMESTER_SELECTION_METHODS,
        "semester_selection_method",
        issue,
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
    z_policy = _choice(raw["z_score_policy"], Z_SCORE_POLICIES, "z_score_policy", issue)
    z_source = (
        _choice(raw["z_score_source"], Z_SCORE_SOURCES, "z_score_source", issue)
        if raw["z_score_source"]
        else None
    )
    rounding_mode = _choice(raw["rounding_mode"], ROUNDING_MODES, "rounding_mode", issue)

    best_semester_count = _optional_integer(
        raw["best_semester_count"], "best_semester_count", issue
    )
    best_subject_count = _optional_integer(raw["best_subject_count"], "best_subject_count", issue)
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
    if any(value is not None for value in semester_weights) and sum(
        value for value in semester_weights if value is not None
    ) != Decimal(1):
        issue(
            "semester_weight_1_1",
            "SEMESTER_WEIGHT_SUM",
            "입력한 학기 가중치 합계는 1이어야 합니다.",
        )
    if any(value is not None for value in grade_weights) and any(
        value is not None for value in semester_weights
    ):
        issue(
            "semester_weight_1_1",
            "WEIGHT_MODE_CONFLICT",
            "학년 가중치와 학기 가중치는 동시에 사용할 수 없습니다.",
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
    maximum_score = _optional_decimal(raw["maximum_score"], "maximum_score", issue)
    if maximum_score is not None and maximum_score <= 0:
        issue("maximum_score", "POSITIVE_DECIMAL_REQUIRED", "maximum_score는 양수여야 합니다.")

    evidence_page = _optional_integer(raw["evidence_page"], "evidence_page", issue)
    if evidence_page is not None and evidence_page <= 0:
        issue("evidence_page", "POSITIVE_INTEGER_REQUIRED", "근거 페이지는 양수여야 합니다.")
    if source_status != "MANUAL_REVIEW":
        for column in ("evidence_document_id", "evidence_page", "evidence_location"):
            if not raw[column]:
                issue(column, "EVIDENCE_REQUIRED", "확정 출처 규칙에는 근거가 필요합니다.")
    if z_policy != "NOT_USED" and z_source is None:
        issue("z_score_source", "Z_SOURCE_REQUIRED", "Z점수 정책에는 출처 코드가 필요합니다.")
    if z_policy == "TABLE_LOOKUP" and not raw["z_score_table_code"]:
        issue("z_score_table_code", "Z_TABLE_REQUIRED", "표 조회 정책에는 table_code가 필요합니다.")

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
        semester_selection_method=semester_method,
        best_semester_count=best_semester_count,
        subject_selection_method=subject_method,
        best_subject_count=best_subject_count,
        subject_scope=subject_scope,
        credit_weighted=booleans["credit_weighted"],
        grade_weight_1=grade_weights[0],
        grade_weight_2=grade_weights[1],
        grade_weight_3=grade_weights[2],
        semester_weight_1_1=semester_weights[0],
        semester_weight_1_2=semester_weights[1],
        semester_weight_2_1=semester_weights[2],
        semester_weight_2_2=semester_weights[3],
        semester_weight_3_1=semester_weights[4],
        semester_weight_3_2=semester_weights[5],
        achievement_handling=achievement,
        career_subject_included=booleans["career_subject_included"],
        z_score_policy=z_policy,
        z_score_source=z_source,
        z_score_table_code=raw["z_score_table_code"] or None,
        attendance_included=booleans["attendance_included"],
        interview_ratio=interview_ratio,
        practical_ratio=practical_ratio,
        rounding_mode=rounding_mode,
        rounding_scale=rounding_scale,
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
        excluded_columns={"z_min_exclusive", "z_max_inclusive", "converted_value"},
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
    z_min = _optional_decimal(raw["z_min_exclusive"], "z_min_exclusive", issue)
    z_max = _optional_decimal(raw["z_max_inclusive"], "z_max_inclusive", issue)
    converted = _decimal(raw["converted_value"], "converted_value", issue)
    evidence_page = _integer(raw["evidence_page"], "evidence_page", issue)
    source_status = _choice(raw["source_status"], SOURCE_STATUSES, "source_status", issue)
    if z_min is not None and z_max is not None and z_min >= z_max:
        issue("z_min_exclusive", "Z_RANGE_ORDER", "Z점수 하한은 상한보다 작아야 합니다.")
    if evidence_page is not None and evidence_page <= 0:
        issue("evidence_page", "POSITIVE_INTEGER_REQUIRED", "근거 페이지는 양수여야 합니다.")
    if issues or converted is None or evidence_page is None:
        return None, tuple(issues)
    return (
        ZScoreTableRow(
            table_code=raw["table_code"],
            z_min_exclusive=z_min,
            z_max_inclusive=z_max,
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
        "semester_selection_method": definition.semester_selection_method,
        "best_semester_count": _optional_text(definition.best_semester_count),
        "subject_selection_method": definition.subject_selection_method,
        "best_subject_count": _optional_text(definition.best_subject_count),
        "subject_scope": definition.subject_scope,
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
        "z_score_policy": definition.z_score_policy,
        "z_score_source": definition.z_score_source or "",
        "z_score_table_code": definition.z_score_table_code or "",
        "interview_ratio": _decimal_text(definition.interview_ratio) or "",
        "practical_ratio": _decimal_text(definition.practical_ratio) or "",
        "rounding_mode": definition.rounding_mode,
        "rounding_scale": _optional_text(definition.rounding_scale),
        "maximum_score": _decimal_text(definition.maximum_score) or "",
        "evidence_document_id": row.evidence_document_id or "",
        "evidence_page": _optional_text(row.evidence_page),
        "evidence_location": row.evidence_location or "",
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


def _validate_weight_set(values: tuple[Decimal | None, ...], label: str) -> None:
    provided = tuple(value for value in values if value is not None)
    if not provided:
        return
    if any(not Decimal(0) <= value <= Decimal(1) for value in provided):
        raise ValueError(f"{label} 가중치는 0 이상 1 이하여야 합니다.")
    if sum(provided) != Decimal(1):
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
    "score_rule_to_payload",
    "validate_score_rule_payload",
    "write_score_rule_csv",
    "write_z_score_table_csv",
]
