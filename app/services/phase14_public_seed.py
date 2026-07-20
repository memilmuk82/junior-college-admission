from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AdmissionResultImportDataset,
    AdmissionRound,
    AdmissionTrack,
    Campus,
    Institution,
    Program,
    new_id,
)
from app.services.admission_result_file_imports import parse_admission_result_upload
from app.services.admission_result_imports import (
    DatabaseCatalogResolver,
    DuplicateAdmissionResultDataset,
    persist_admission_result_preview,
    publish_admission_result_dataset,
)

CATALOG_RELATIVE_PATH = Path("data/seed/phase14_public_admission_catalog.csv")
RESULT_RELATIVE_PATH = Path("data/seed/phase14_public_admission_results_2025.csv")
CATALOG_SHA256 = "d34f81d8bccab464a49026cec60c916f2f1b5c5786ea96fd853aac92b233ce5f"
RESULT_SHA256 = "bbc542687f299a1655d1ca480a9e67cafb034f7824d6abe78bd06990590604d2"
PHASE17_CATALOG_RELATIVE_PATH = Path("data/seed/phase17_public_admission_catalog.csv")
PHASE17_RESULT_RELATIVE_PATH = Path("data/seed/phase17_public_admission_results_2026.csv")
PHASE17_AUDIT_RELATIVE_PATH = Path("data/seed/phase17_public_admission_audit.json")
PHASE17_CATALOG_SHA256 = "f45c3eedf7b41208bf4c25023dfdac657d6048bed5c0518c8eb874dd7e2a0d81"
PHASE17_RESULT_SHA256 = "6546aedfd3aac0f4e051713f14aaaa3919d0b17b5060ec909be53fa3ac62215f"
PHASE17_AUDIT_SHA256 = "ddad414bee800ee3ed5ae650151febbb6a86260a645d24209ea503d74df3b42d"


class Phase14SeedError(ValueError):
    pass


@dataclass(frozen=True)
class Phase17PublicSeedResult:
    result_2025_dataset_id: str
    result_2026_dataset_id: str
    source_institution_names: tuple[str, ...]


def load_phase14_public_seed(
    session: Session,
    *,
    repository_root: Path,
    actor_ref: str,
    occurred_at: datetime,
) -> str:
    catalog_path = repository_root / CATALOG_RELATIVE_PATH
    result_path = repository_root / RESULT_RELATIVE_PATH
    catalog_bytes = _verified_bytes(catalog_path, CATALOG_SHA256)
    result_bytes = _verified_bytes(result_path, RESULT_SHA256)
    catalog_rows = tuple(csv.DictReader(catalog_bytes.decode("utf-8").splitlines()))
    if len(catalog_rows) != 482:
        raise Phase14SeedError("공개 catalog seed 행 수가 manifest와 다릅니다.")

    institutions: dict[str, Institution] = {}
    campuses: dict[tuple[str, str], Campus] = {}
    programs: dict[tuple[str, str], Program] = {}
    rounds: dict[tuple[str, int, str], AdmissionRound] = {}
    tracks: dict[tuple[str, str, str], AdmissionTrack] = {}

    for payload in catalog_rows:
        institution = institutions.get(payload["institution_code"])
        if institution is None:
            institution = _institution(session, payload)
            institutions[payload["institution_code"]] = institution
        campus_key = (institution.id, payload["campus_code"])
        campus = campuses.get(campus_key)
        if campus is None:
            campus = _campus(session, institution, payload)
            campuses[campus_key] = campus
        program_key = (campus.id, payload["program_code"])
        program = programs.get(program_key)
        if program is None:
            program = _program(session, campus, payload)
            programs[program_key] = program
        year = int(payload["target_academic_year"])
        round_key = (institution.id, year, payload["admission_round_code"])
        admission_round = rounds.get(round_key)
        if admission_round is None:
            admission_round = _round(session, institution, year, payload)
            rounds[round_key] = admission_round
        track_key = (admission_round.id, program.id, payload["admission_track_code"])
        if track_key not in tracks:
            tracks[track_key] = _track(session, admission_round, program, payload)
    session.flush()

    preview = parse_admission_result_upload(
        result_bytes,
        filename=RESULT_RELATIVE_PATH.name,
        result_academic_year=2025,
        target_academic_year=2027,
        catalog=DatabaseCatalogResolver(session),
    )
    if (
        preview.total_row_count,
        preview.valid_row_count,
        preview.review_row_count,
        preview.error_row_count,
    ) != (482, 482, 0, 0):
        raise Phase14SeedError("공개 결과 seed가 482개 VALID canonical 행을 만들지 못했습니다.")
    try:
        dataset = persist_admission_result_preview(
            session,
            preview,
            source_code="PROCOLLEGE_REFERENCE_XLSX_2025_RESULTS",
            source_dataset_version="2025-PILOT-XLSX-V1",
            source_reference="data/sources/index.yaml#PROCOLLEGE_REFERENCE_XLSX_2025_RESULTS",
            collected_at=occurred_at,
        )
    except DuplicateAdmissionResultDataset as error:
        return error.dataset_id
    session.flush()
    publish_admission_result_dataset(
        session,
        dataset.id,
        published_by=actor_ref,
        published_at=occurred_at,
        allow_partial=False,
    )
    return dataset.id


def load_phase17_public_seed(
    session: Session,
    *,
    repository_root: Path,
    actor_ref: str,
    occurred_at: datetime,
) -> Phase17PublicSeedResult:
    """Load the complete public catalog and only the validated 2026 reference results."""

    result_2025_dataset_id = load_phase14_public_seed(
        session,
        repository_root=repository_root,
        actor_ref=actor_ref,
        occurred_at=occurred_at,
    )
    catalog_bytes = _verified_bytes(
        repository_root / PHASE17_CATALOG_RELATIVE_PATH,
        PHASE17_CATALOG_SHA256,
    )
    result_bytes = _verified_bytes(
        repository_root / PHASE17_RESULT_RELATIVE_PATH,
        PHASE17_RESULT_SHA256,
    )
    audit_bytes = _verified_bytes(
        repository_root / PHASE17_AUDIT_RELATIVE_PATH,
        PHASE17_AUDIT_SHA256,
    )
    catalog_rows = tuple(
        {key: value or "" for key, value in row.items()}
        for row in csv.DictReader(catalog_bytes.decode("utf-8").splitlines())
    )
    audit = json.loads(audit_bytes)
    _verify_phase17_contract(catalog_rows, audit)
    source_institution_names = _sync_phase17_catalog(session, catalog_rows)
    session.flush()

    preview = parse_admission_result_upload(
        result_bytes,
        filename=PHASE17_RESULT_RELATIVE_PATH.name,
        result_academic_year=2026,
        target_academic_year=2027,
        catalog=DatabaseCatalogResolver(session),
    )
    counts = (
        preview.total_row_count,
        preview.valid_row_count,
        preview.review_row_count,
        preview.error_row_count,
    )
    if counts != (4_094, 4_094, 0, 0):
        raise Phase14SeedError(
            "2026 공개 결과 seed가 4,094개 VALID canonical 행을 만들지 못했습니다."
        )
    basis_counts = Counter(row.score_basis for row in preview.rows)
    if basis_counts != Counter({"RANK_GRADE": 3_562, "CSAT_GRADE": 208, "POINT_SCORE": 324}):
        raise Phase14SeedError("2026 공개 결과 seed의 점수 척도별 행 수가 검수 계약과 다릅니다.")

    try:
        dataset = persist_admission_result_preview(
            session,
            preview,
            source_code="PROCOLLEGE_PUBLIC_RESULTS_2026",
            source_dataset_version="2026-PUBLIC-REFERENCE-V1",
            source_reference="data/sources/index.yaml#PROCOLLEGE_PUBLIC_RESULTS_2026",
            collected_at=occurred_at,
        )
        session.flush()
        publish_admission_result_dataset(
            session,
            dataset.id,
            published_by=actor_ref,
            published_at=occurred_at,
            allow_partial=False,
        )
        result_2026_dataset_id = dataset.id
    except DuplicateAdmissionResultDataset as error:
        existing = session.get(AdmissionResultImportDataset, error.dataset_id)
        if existing is None:
            raise Phase14SeedError("기존 2026 공개 결과 데이터셋을 찾을 수 없습니다.") from error
        if existing.lifecycle_status in {"READY", "STAGED"}:
            publish_admission_result_dataset(
                session,
                existing.id,
                published_by=actor_ref,
                published_at=occurred_at,
                allow_partial=False,
            )
        elif existing.lifecycle_status != "PUBLISHED":
            raise Phase14SeedError(
                "기존 2026 공개 결과 데이터셋이 활성 게시 상태가 아닙니다."
            ) from error
        result_2026_dataset_id = existing.id

    return Phase17PublicSeedResult(
        result_2025_dataset_id=result_2025_dataset_id,
        result_2026_dataset_id=result_2026_dataset_id,
        source_institution_names=source_institution_names,
    )


def _verify_phase17_contract(catalog_rows: tuple[dict[str, str], ...], audit: object) -> None:
    if len(catalog_rows) != 4_970:
        raise Phase14SeedError("Phase 17 공개 catalog 행 수가 4,970개가 아닙니다.")
    institutions = {row["institution_name"] for row in catalog_rows}
    catalog_keys = {
        (
            row["institution_code"],
            row["campus_code"],
            row["program_code"],
            row["day_night"],
            row["admission_round_code"],
            row["admission_track_code"],
        )
        for row in catalog_rows
    }
    program_keys = {key[:4] for key in catalog_keys}
    if len(institutions) != 42 or len(catalog_keys) != 4_970 or len(program_keys) != 1_048:
        raise Phase14SeedError("Phase 17 공개 catalog의 대학·학과 업무키 집계가 다릅니다.")
    if {row["day_night"] for row in catalog_rows} - {"DAY", "NIGHT"}:
        raise Phase14SeedError("Phase 17 공개 catalog의 주·야 구분이 canonical 값이 아닙니다.")

    root = _audit_mapping(audit, "audit")
    source = _audit_mapping(root.get("source"), "source")
    catalog = _audit_mapping(root.get("catalog"), "catalog")
    published = _audit_mapping(root.get("published_results"), "published_results")
    excluded = _audit_mapping(root.get("excluded_results"), "excluded_results")
    derived = _audit_mapping(root.get("derived_files"), "derived_files")
    if source != {
        "filename": "result2026 (2).csv",
        "institution_count": 42,
        "result_academic_year": 2026,
        "row_count": 4_970,
        "sha256": "f8577f1e58dbcaa2d2e1bc11ea4ff68641f5e506466ab8d61c49c2ce65c3e8cd",
        "size": 603_788,
        "target_academic_year": 2027,
    }:
        raise Phase14SeedError("Phase 17 감사 기록의 원본 출처 계약이 다릅니다.")
    if (
        catalog.get("row_count"),
        catalog.get("institution_count"),
        catalog.get("region_campus_count"),
        catalog.get("program_count"),
    ) != (4_970, 42, 44, 1_048):
        raise Phase14SeedError("Phase 17 감사 기록의 catalog 집계가 다릅니다.")
    if (
        published.get("row_count"),
        published.get("rank_grade_row_count"),
        published.get("csat_grade_row_count"),
        published.get("point_score_row_count"),
    ) != (4_094, 3_562, 208, 324):
        raise Phase14SeedError("Phase 17 감사 기록의 게시 결과 집계가 다릅니다.")
    reason_counts = _audit_mapping(excluded.get("reason_counts"), "reason_counts")
    excluded_rows = excluded.get("rows")
    if (
        excluded.get("row_count") != 876
        or reason_counts != {"SCORE_BASIS_MISSING": 572, "SCORE_OUT_OF_RANGE": 308}
        or excluded.get("zero_or_out_of_range_values_are_not_coerced") is not True
        or not isinstance(excluded_rows, list)
        or len(excluded_rows) != 876
    ):
        raise Phase14SeedError("Phase 17 감사 기록의 제외 결과 집계가 다릅니다.")
    excluded_by_row = {
        item.get("source_row_number"): item.get("reason_codes")
        for item in excluded_rows
        if isinstance(item, dict)
    }
    zero_score_reasons = excluded_by_row.get(1571)
    if (
        len(excluded_by_row) != 876
        or not isinstance(zero_score_reasons, list)
        or "SCORE_OUT_OF_RANGE" not in zero_score_reasons
    ):
        raise Phase14SeedError("Phase 17 0점 원본 행의 fail-closed 감사 기록이 없습니다.")
    if (
        derived.get("catalog_sha256") != PHASE17_CATALOG_SHA256
        or derived.get("result_sha256") != PHASE17_RESULT_SHA256
    ):
        raise Phase14SeedError("Phase 17 감사 기록의 파생 파일 SHA-256이 다릅니다.")


def _audit_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise Phase14SeedError(f"Phase 17 감사 기록의 {label} 구조가 잘못되었습니다.")
    return value


def _sync_phase17_catalog(
    session: Session, catalog_rows: tuple[dict[str, str], ...]
) -> tuple[str, ...]:
    institution_payloads: dict[str, dict[str, str]] = {}
    campus_payloads: dict[tuple[str, str], dict[str, str]] = {}
    program_payloads: dict[tuple[str, str, str], dict[str, str]] = {}
    round_payloads: dict[tuple[str, int, str], dict[str, str]] = {}
    for payload in catalog_rows:
        institution_key = payload["institution_code"]
        _remember_payload(
            institution_payloads,
            institution_key,
            payload,
            ("institution_name", "institution_type"),
            "대학",
        )
        campus_key = (institution_key, payload["campus_code"])
        _remember_payload(
            campus_payloads,
            campus_key,
            payload,
            ("campus_name", "region"),
            "캠퍼스",
        )
        program_key = (*campus_key, payload["program_code"])
        _remember_payload(
            program_payloads,
            program_key,
            payload,
            ("program_name", "day_night"),
            "학과",
        )
        round_key = (
            institution_key,
            int(payload["target_academic_year"]),
            payload["admission_round_code"],
        )
        _remember_payload(
            round_payloads,
            round_key,
            payload,
            ("admission_round_name",),
            "모집시기",
        )

    existing_institutions = tuple(session.scalars(select(Institution)))
    institutions_by_code = {row.code: row for row in existing_institutions if row.code}
    institutions_by_name = {row.name: row for row in existing_institutions}
    institutions: dict[str, Institution] = {}
    for code, payload in institution_payloads.items():
        institution_row = institutions_by_code.get(code) or institutions_by_name.get(
            payload["institution_name"]
        )
        if institution_row is None:
            institution_row = Institution(
                id=new_id(),
                code=code,
                name=payload["institution_name"],
                institution_type=payload["institution_type"],
            )
            session.add(institution_row)
        elif institution_row.code not in {None, code}:
            raise Phase14SeedError("같은 대학 이름이 다른 코드로 이미 등록되어 있습니다.")
        else:
            institution_row.code = code
            _assert_name(institution_row.name, payload["institution_name"], "대학")
            if institution_row.institution_type != payload["institution_type"]:
                raise Phase14SeedError("대학 유형이 공개 catalog와 다릅니다.")
        institutions[code] = institution_row

    existing_campuses = tuple(session.scalars(select(Campus)))
    campuses_by_code = {
        (row.institution_id, row.code): row for row in existing_campuses if row.code
    }
    campuses_by_name = {(row.institution_id, row.name): row for row in existing_campuses}
    campuses: dict[tuple[str, str], Campus] = {}
    for (institution_code, campus_code), payload in campus_payloads.items():
        institution = institutions[institution_code]
        campus_row = campuses_by_code.get((institution.id, campus_code)) or campuses_by_name.get(
            (institution.id, payload["campus_name"])
        )
        if campus_row is None:
            campus_row = Campus(
                id=new_id(),
                institution_id=institution.id,
                code=campus_code,
                name=payload["campus_name"],
                region=payload["region"],
            )
            session.add(campus_row)
        elif campus_row.code not in {None, campus_code}:
            raise Phase14SeedError("같은 캠퍼스 이름이 다른 코드로 이미 등록되어 있습니다.")
        else:
            campus_row.code = campus_code
            _assert_name(campus_row.name, payload["campus_name"], "캠퍼스")
            if campus_row.region is None:
                campus_row.region = payload["region"]
            elif campus_row.region != payload["region"]:
                raise Phase14SeedError("캠퍼스 지역이 공개 catalog와 다릅니다.")
        campuses[(institution_code, campus_code)] = campus_row

    existing_programs = tuple(session.scalars(select(Program)))
    programs_by_code = {(row.campus_id, row.code): row for row in existing_programs if row.code}
    programs_by_name_day = {
        (row.campus_id, row.name, row.day_night): row for row in existing_programs
    }
    programs: dict[tuple[str, str, str], Program] = {}
    for (institution_code, campus_code, program_code), payload in program_payloads.items():
        campus = campuses[(institution_code, campus_code)]
        desired_day_night = payload["day_night"]
        program_row = programs_by_code.get((campus.id, program_code)) or programs_by_name_day.get(
            (campus.id, payload["program_name"], desired_day_night)
        )
        if program_row is None:
            legacy_program = programs_by_name_day.get(
                (campus.id, payload["program_name"], "UNKNOWN")
            )
            if legacy_program is not None and legacy_program.day_night == "UNKNOWN":
                program_row = legacy_program
        if program_row is None:
            program_row = Program(
                id=new_id(),
                campus_id=campus.id,
                code=program_code,
                name=payload["program_name"],
                day_night=desired_day_night,
            )
            session.add(program_row)
        else:
            _assert_name(program_row.name, payload["program_name"], "학과")
            if program_row.day_night == "UNKNOWN":
                program_row.day_night = desired_day_night
            elif program_row.day_night != desired_day_night:
                raise Phase14SeedError("학과 코드의 주·야 구분이 공개 catalog와 다릅니다.")
        programs_by_code[(campus.id, program_code)] = program_row
        programs_by_name_day[(campus.id, payload["program_name"], desired_day_night)] = program_row
        programs[(institution_code, campus_code, program_code)] = program_row

    existing_rounds = tuple(session.scalars(select(AdmissionRound)))
    rounds_by_key = {
        (row.institution_id, row.academic_year, row.code): row for row in existing_rounds
    }
    rounds: dict[tuple[str, int, str], AdmissionRound] = {}
    for (institution_code, year, round_code), payload in round_payloads.items():
        institution = institutions[institution_code]
        round_row = rounds_by_key.get((institution.id, year, round_code))
        if round_row is None:
            round_row = AdmissionRound(
                id=new_id(),
                institution_id=institution.id,
                academic_year=year,
                code=round_code,
                name=payload["admission_round_name"],
            )
            session.add(round_row)
        else:
            _assert_name(round_row.name, payload["admission_round_name"], "모집시기")
        rounds[(institution_code, year, round_code)] = round_row

    existing_tracks = tuple(session.scalars(select(AdmissionTrack)))
    tracks_by_key = {
        (row.admission_round_id, row.program_id, row.code): row for row in existing_tracks
    }
    seen_tracks: set[tuple[str, str, str]] = set()
    for payload in catalog_rows:
        admission_round = rounds[
            (
                payload["institution_code"],
                int(payload["target_academic_year"]),
                payload["admission_round_code"],
            )
        ]
        program = programs[
            (
                payload["institution_code"],
                payload["campus_code"],
                payload["program_code"],
            )
        ]
        key = (admission_round.id, program.id, payload["admission_track_code"])
        if key in seen_tracks:
            raise Phase14SeedError("Phase 17 공개 catalog의 전형 업무키가 중복되었습니다.")
        seen_tracks.add(key)
        track_row = tracks_by_key.get(key)
        if track_row is None:
            session.add(
                AdmissionTrack(
                    id=new_id(),
                    admission_round_id=admission_round.id,
                    program_id=program.id,
                    code=payload["admission_track_code"],
                    name=payload["admission_track_name"],
                )
            )
        else:
            _assert_name(track_row.name, payload["admission_track_name"], "전형")
    return tuple(sorted(payload["institution_name"] for payload in institution_payloads.values()))


def _remember_payload[PayloadKey](
    values: dict[PayloadKey, dict[str, str]],
    key: PayloadKey,
    payload: dict[str, str],
    compared_fields: tuple[str, ...],
    label: str,
) -> None:
    previous = values.setdefault(key, payload)
    if any(previous[field] != payload[field] for field in compared_fields):
        raise Phase14SeedError(f"Phase 17 {label} 코드가 서로 다른 값에 사용되었습니다.")


def _verified_bytes(path: Path, expected_hash: str) -> bytes:
    value = path.read_bytes()
    if hashlib.sha256(value).hexdigest() != expected_hash:
        raise Phase14SeedError(f"seed SHA-256이 manifest와 다릅니다: {path.name}")
    return value


def _institution(session: Session, payload: dict[str, str]) -> Institution:
    row = session.scalar(select(Institution).where(Institution.code == payload["institution_code"]))
    if row is None:
        row = Institution(
            code=payload["institution_code"],
            name=payload["institution_name"],
            institution_type=payload["institution_type"],
        )
        session.add(row)
        session.flush()
    _assert_name(row.name, payload["institution_name"], "대학")
    return row


def _campus(session: Session, institution: Institution, payload: dict[str, str]) -> Campus:
    row = session.scalar(
        select(Campus).where(
            Campus.institution_id == institution.id,
            Campus.code == payload["campus_code"],
        )
    )
    if row is None:
        row = Campus(
            institution_id=institution.id,
            code=payload["campus_code"],
            name=payload["campus_name"],
            region=payload.get("region") or None,
        )
        session.add(row)
        session.flush()
    _assert_name(row.name, payload["campus_name"], "캠퍼스")
    incoming_region = payload.get("region")
    if incoming_region:
        if row.region is None:
            row.region = incoming_region
        elif row.region != incoming_region:
            raise Phase14SeedError("캠퍼스 지역이 공개 catalog와 다릅니다.")
    return row


def _program(session: Session, campus: Campus, payload: dict[str, str]) -> Program:
    day_night = payload.get("day_night") or "DAY"
    row = session.scalar(
        select(Program).where(
            Program.campus_id == campus.id,
            Program.code == payload["program_code"],
        )
    )
    if row is None:
        row = Program(
            campus_id=campus.id,
            code=payload["program_code"],
            name=payload["program_name"],
            day_night=day_night,
        )
        session.add(row)
        session.flush()
    _assert_name(row.name, payload["program_name"], "학과")
    if row.day_night == "UNKNOWN":
        row.day_night = day_night
    elif row.day_night != day_night:
        raise Phase14SeedError("학과 코드의 주·야 구분이 공개 catalog와 다릅니다.")
    return row


def _round(
    session: Session,
    institution: Institution,
    year: int,
    payload: dict[str, str],
) -> AdmissionRound:
    row = session.scalar(
        select(AdmissionRound).where(
            AdmissionRound.institution_id == institution.id,
            AdmissionRound.academic_year == year,
            AdmissionRound.code == payload["admission_round_code"],
        )
    )
    if row is None:
        row = AdmissionRound(
            institution_id=institution.id,
            academic_year=year,
            code=payload["admission_round_code"],
            name=payload["admission_round_name"],
        )
        session.add(row)
        session.flush()
    _assert_name(row.name, payload["admission_round_name"], "모집시기")
    return row


def _track(
    session: Session,
    admission_round: AdmissionRound,
    program: Program,
    payload: dict[str, str],
) -> AdmissionTrack:
    row = session.scalar(
        select(AdmissionTrack).where(
            AdmissionTrack.admission_round_id == admission_round.id,
            AdmissionTrack.program_id == program.id,
            AdmissionTrack.code == payload["admission_track_code"],
        )
    )
    if row is None:
        row = AdmissionTrack(
            admission_round_id=admission_round.id,
            program_id=program.id,
            code=payload["admission_track_code"],
            name=payload["admission_track_name"],
        )
        session.add(row)
        session.flush()
    _assert_name(row.name, payload["admission_track_name"], "전형")
    return row


def _assert_name(actual: str, expected: str, label: str) -> None:
    if actual != expected:
        raise Phase14SeedError(f"{label} 코드가 다른 이름으로 이미 사용 중입니다.")


__all__ = [
    "Phase14SeedError",
    "Phase17PublicSeedResult",
    "load_phase14_public_seed",
    "load_phase17_public_seed",
]
