from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from unicodedata import normalize

SOURCE_PATH = Path("tmp/codex-reference/csv/result2026 (2).csv")
SOURCE_SIZE = 603_788
SOURCE_SHA256 = "f8577f1e58dbcaa2d2e1bc11ea4ff68641f5e506466ab8d61c49c2ce65c3e8cd"
SOURCE_COLUMNS = (
    "모집학년도",
    "지역",
    "대학명",
    "모집시기",
    "전공명",
    "입학정원",
    "주/야",
    "전형구분",
    "출신교",
    "점수산출_수능",
    "점수산출_학생부",
    "경쟁률",
    "평균_수능",
    "평균_학생부",
    "최저_수능",
    "최저_학생부",
)
CATALOG_PATH = Path("data/seed/phase17_public_admission_catalog.csv")
RESULT_PATH = Path("data/seed/phase17_public_admission_results_2026.csv")
AUDIT_PATH = Path("data/seed/phase17_public_admission_audit.json")

KNOWN_INSTITUTION_CODES = {
    "동양미래대학교": "DONGYANG-MIRAE",
    "명지전문대학": "MYONGJI-COLLEGE",
    "인하공업전문대학": "INHA-TECHNICAL-COLLEGE",
    "연성대학교": "YEONSUNG",
}
ROUND_CODES = {
    "수시1차": "SUSI-1",
    "수시2차": "SUSI-2",
    "정시모집": "JEONGSI",
}
TRACK_CODES = {
    ("일반전형", "일반전형"): "GENERAL",
    ("특별전형", "일반고"): "SPECIAL-GENERAL-HS",
    ("특별전형", "특성화고"): "SPECIAL-VOCATIONAL-HS",
    ("특별전형", "대학자체"): "COLLEGE-SPECIFIC",
    ("특별전형", "고른기회"): "SPECIAL-OPPORTUNITY",
}
DAY_NIGHT_CODES = {"주간": "DAY", "야간": "NIGHT"}


@dataclass(frozen=True)
class Phase17SeedBuild:
    catalog_rows: tuple[dict[str, object], ...]
    result_rows: tuple[dict[str, object], ...]
    audit_payload: dict[str, object]
    source_row_count: int
    source_institution_count: int
    catalog_row_count: int
    catalog_program_count: int
    result_row_count: int
    rank_grade_row_count: int
    csat_grade_row_count: int
    point_score_row_count: int
    excluded_row_count: int
    exclusion_reason_counts: dict[str, int]


def build_phase17_seed_rows() -> Phase17SeedBuild:
    source = SOURCE_PATH.read_bytes()
    if len(source) != SOURCE_SIZE or hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise SystemExit("BLOCKED_SOURCE: 2026 공개 결과 CSV size 또는 SHA-256이 다릅니다.")
    text = source.decode("utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    if tuple(reader.fieldnames or ()) != SOURCE_COLUMNS:
        raise SystemExit("BLOCKED_SOURCE: 2026 공개 결과 CSV 머리글이 계약과 다릅니다.")
    raw_rows = tuple(reader)
    if len(raw_rows) != 4_970:
        raise SystemExit("BLOCKED_SOURCE: 2026 공개 결과 CSV 행 수가 4,970이 아닙니다.")
    if {row["모집학년도"] for row in raw_rows} != {"2026"}:
        raise SystemExit("BLOCKED_SOURCE: 2026 외 모집학년도가 섞여 있습니다.")
    institutions = {_required(row, "대학명") for row in raw_rows}
    if len(institutions) != 42:
        raise SystemExit("BLOCKED_SOURCE: 2026 공개 결과 CSV 대학 수가 42개가 아닙니다.")

    catalog_rows: list[dict[str, object]] = []
    result_rows: list[dict[str, object]] = []
    excluded_rows: list[dict[str, object]] = []
    reason_counts: Counter[str] = Counter()
    catalog_keys: set[tuple[str, ...]] = set()
    program_keys: set[tuple[str, ...]] = set()

    for source_row_number, raw in enumerate(raw_rows, start=2):
        canonical = _catalog_row(raw, source_row_number)
        catalog_key = (
            str(canonical["institution_code"]),
            str(canonical["campus_code"]),
            str(canonical["program_code"]),
            str(canonical["day_night"]),
            str(canonical["admission_round_code"]),
            str(canonical["admission_track_code"]),
        )
        if catalog_key in catalog_keys:
            raise SystemExit(
                f"BLOCKED_SOURCE: 주야·지역 포함 canonical 업무키가 중복됩니다: {source_row_number}"
            )
        catalog_keys.add(catalog_key)
        program_keys.add(catalog_key[:4])
        catalog_rows.append(canonical)

        score_contract, reason_codes = _score_contract(raw)
        if reason_codes:
            reason_counts.update(reason_codes)
            excluded_rows.append(
                {
                    "source_row_number": source_row_number,
                    "reason_codes": list(reason_codes),
                }
            )
            continue
        assert score_contract is not None
        score_basis, score_direction, average, cutoff, score_columns = score_contract
        result_rows.append(
            {
                "result_academic_year": 2026,
                "region": canonical["region"],
                "institution_name": canonical["institution_name"],
                "campus_name": canonical["campus_name"],
                "admission_round_name": canonical["admission_round_name"],
                "program_name": canonical["program_name"],
                "day_night": canonical["day_night"],
                "admission_category": canonical["admission_category"],
                "admission_track_name": canonical["admission_track_label"],
                "capacity": _text(raw.get("입학정원")),
                "applicant_count": "",
                "admitted_count": "",
                "competition_rate": _text(raw.get("경쟁률")),
                "best_score": "",
                "average_score": average,
                "cutoff_score": cutoff,
                "score_basis": score_basis,
                "score_direction": score_direction,
                "source_reference": (
                    f"sha256:{SOURCE_SHA256}#CSV:{source_row_number};score_columns={score_columns}"
                ),
            }
        )

    if len(catalog_rows) != 4_970 or len(catalog_keys) != 4_970:
        raise SystemExit("BLOCKED_SOURCE: Phase 17 catalog 행 수가 원본과 일치하지 않습니다.")
    if len(program_keys) != 1_048:
        raise SystemExit("BLOCKED_SOURCE: Phase 17 주야·지역별 학과 수가 1,048개가 아닙니다.")
    if len(result_rows) != 4_094 or len(excluded_rows) != 876:
        raise SystemExit("BLOCKED_SOURCE: Phase 17 게시·제외 행 수가 검수 계약과 다릅니다.")
    if reason_counts != Counter({"SCORE_BASIS_MISSING": 572, "SCORE_OUT_OF_RANGE": 308}):
        raise SystemExit("BLOCKED_SOURCE: Phase 17 제외 사유 집계가 검수 계약과 다릅니다.")
    basis_counts = Counter(str(row["score_basis"]) for row in result_rows)
    if basis_counts != Counter({"RANK_GRADE": 3_562, "CSAT_GRADE": 208, "POINT_SCORE": 324}):
        raise SystemExit("BLOCKED_SOURCE: Phase 17 점수 척도 집계가 검수 계약과 다릅니다.")

    audit_payload: dict[str, object] = {
        "schema": "phase17_public_admission_audit",
        "version": 1,
        "source": {
            "filename": SOURCE_PATH.name,
            "size": SOURCE_SIZE,
            "sha256": SOURCE_SHA256,
            "result_academic_year": 2026,
            "target_academic_year": 2027,
            "row_count": len(raw_rows),
            "institution_count": len(institutions),
        },
        "catalog": {
            "row_count": len(catalog_rows),
            "institution_count": len(institutions),
            "region_campus_count": len(
                {(str(row["institution_code"]), str(row["campus_code"])) for row in catalog_rows}
            ),
            "program_count": len(program_keys),
            "policy": "원본 4,970행의 모든 제공 대학·학과·주야·전형을 선택 기준정보로 보존",
        },
        "published_results": {
            "row_count": len(result_rows),
            "rank_grade_row_count": basis_counts["RANK_GRADE"],
            "csat_grade_row_count": basis_counts["CSAT_GRADE"],
            "point_score_row_count": basis_counts["POINT_SCORE"],
            "policy": "2026 공개 참고 결과이며 2027 성적 규칙으로 직접 비교하지 않음",
        },
        "excluded_results": {
            "row_count": len(excluded_rows),
            "reason_counts": dict(sorted(reason_counts.items())),
            "zero_or_out_of_range_values_are_not_coerced": True,
            "rows": excluded_rows,
        },
    }
    return Phase17SeedBuild(
        catalog_rows=tuple(catalog_rows),
        result_rows=tuple(result_rows),
        audit_payload=audit_payload,
        source_row_count=len(raw_rows),
        source_institution_count=len(institutions),
        catalog_row_count=len(catalog_rows),
        catalog_program_count=len(program_keys),
        result_row_count=len(result_rows),
        rank_grade_row_count=basis_counts["RANK_GRADE"],
        csat_grade_row_count=basis_counts["CSAT_GRADE"],
        point_score_row_count=basis_counts["POINT_SCORE"],
        excluded_row_count=len(excluded_rows),
        exclusion_reason_counts=dict(sorted(reason_counts.items())),
    )


def main() -> None:
    built = build_phase17_seed_rows()
    _write_csv(CATALOG_PATH, built.catalog_rows)
    _write_csv(RESULT_PATH, built.result_rows)
    audit = dict(built.audit_payload)
    audit["derived_files"] = {
        "catalog_path": CATALOG_PATH.as_posix(),
        "catalog_sha256": hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest(),
        "result_path": RESULT_PATH.as_posix(),
        "result_sha256": hashlib.sha256(RESULT_PATH.read_bytes()).hexdigest(),
    }
    AUDIT_PATH.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "phase17 public seed "
        f"source={built.source_row_count} catalog={built.catalog_row_count} "
        f"published={built.result_row_count} excluded={built.excluded_row_count}"
    )


def _catalog_row(raw: Mapping[str, str], source_row_number: int) -> dict[str, object]:
    institution_name = _required(raw, "대학명")
    region = _required(raw, "지역")
    program_name = _required(raw, "전공명")
    raw_day_night = _required(raw, "주/야")
    try:
        day_night = DAY_NIGHT_CODES[raw_day_night]
        round_name = _required(raw, "모집시기")
        round_code = ROUND_CODES[round_name]
        category = _required(raw, "전형구분")
        track_label = _required(raw, "출신교")
        track_code = TRACK_CODES[(category, track_label)]
    except KeyError as error:
        raise SystemExit(
            f"BLOCKED_SOURCE: 지원하지 않는 공개 분류값입니다: CSV:{source_row_number}"
        ) from error
    institution_code = KNOWN_INSTITUTION_CODES.get(institution_name) or _hashed_code(
        "PROCOLLEGE-U", institution_name
    )
    if institution_name in KNOWN_INSTITUTION_CODES:
        campus_code, campus_name = "MAIN", "본교"
    else:
        campus_code = _hashed_code("REGION", region)
        campus_name = f"{region} 지역"
    if institution_name in KNOWN_INSTITUTION_CODES and day_night == "DAY":
        program_code = _hashed_code("PROGRAM", program_name)
    else:
        program_code = _hashed_code("PROGRAM", f"{program_name}|{day_night}")
    return {
        "institution_code": institution_code,
        "institution_name": institution_name,
        "institution_type": "JUNIOR_COLLEGE",
        "region": region,
        "campus_code": campus_code,
        "campus_name": campus_name,
        "program_code": program_code,
        "program_name": program_name,
        "day_night": day_night,
        "target_academic_year": 2027,
        "admission_round_code": round_code,
        "admission_round_name": round_name,
        "admission_track_code": track_code,
        "admission_track_name": f"{category} / {track_label}",
        "admission_category": category,
        "admission_track_label": track_label,
        "mapping_status": "EXPLICIT_PHASE17_PUBLIC_SOURCE",
        "source_reference": f"sha256:{SOURCE_SHA256}#CSV:{source_row_number}",
    }


def _score_contract(
    raw: Mapping[str, str],
) -> tuple[tuple[str, str, str, str, str] | None, tuple[str, ...]]:
    round_name = _required(raw, "모집시기")
    student_basis = _text(raw.get("점수산출_학생부"))
    csat_basis = _text(raw.get("점수산출_수능"))
    reason_codes: set[str] = set()
    score_contract: tuple[str, str, str, str, str] | None
    rank_values_for_audit = (
        _text(raw.get("평균_학생부")),
        _text(raw.get("최저_학생부")),
    )
    if any(_outside_rank_grade(value) for value in rank_values_for_audit if value):
        reason_codes.add("SCORE_OUT_OF_RANGE")

    if round_name in {"수시1차", "수시2차"}:
        if student_basis != "등급":
            reason_codes.add("SCORE_BASIS_MISSING")
            score_contract = None
        else:
            score_contract = (
                "RANK_GRADE",
                "LOWER_IS_BETTER",
                rank_values_for_audit[0],
                rank_values_for_audit[1],
                "평균_학생부,최저_학생부",
            )
    elif csat_basis == "백분위":
        point_average = _text(raw.get("평균_수능"))
        point_cutoff = _text(raw.get("최저_수능"))
        if any(_outside_point_score(value) for value in (point_average, point_cutoff) if value):
            reason_codes.add("SCORE_OUT_OF_RANGE")
        score_contract = (
            "POINT_SCORE",
            "HIGHER_IS_BETTER",
            point_average,
            point_cutoff,
            "평균_수능,최저_수능",
        )
    elif csat_basis == "등급":
        csat_average = _text(raw.get("평균_수능"))
        csat_cutoff = _text(raw.get("최저_수능"))
        if any(_outside_rank_grade(value) for value in (csat_average, csat_cutoff) if value):
            reason_codes.add("SCORE_OUT_OF_RANGE")
        score_contract = (
            "CSAT_GRADE",
            "LOWER_IS_BETTER",
            csat_average,
            csat_cutoff,
            "평균_수능,최저_수능",
        )
    else:
        reason_codes.add("SCORE_BASIS_MISSING")
        score_contract = None
    return (None if reason_codes else score_contract), tuple(sorted(reason_codes))


def _outside_rank_grade(value: str) -> bool:
    try:
        number = Decimal(value)
    except InvalidOperation:
        return True
    return not number.is_finite() or not Decimal("1") <= number <= Decimal("9")


def _outside_point_score(value: str) -> bool:
    try:
        number = Decimal(value)
    except InvalidOperation:
        return True
    return not number.is_finite() or number < 0


def _hashed_code(prefix: str, value: str) -> str:
    normalized = normalize("NFKC", value).strip()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12].upper()
    return f"{prefix}-{digest}"


def _required(row: Mapping[str, str], key: str) -> str:
    value = _text(row.get(key))
    if not value:
        raise SystemExit(f"BLOCKED_SOURCE: 필수 공개 필드가 비었습니다: {key}")
    return value


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _write_csv(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    materialized = list(rows)
    if not materialized:
        raise SystemExit(f"빈 공개 seed를 만들 수 없습니다: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(materialized[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(materialized)


if __name__ == "__main__":
    main()
