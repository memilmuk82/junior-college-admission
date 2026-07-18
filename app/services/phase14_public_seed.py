from __future__ import annotations

import csv
import hashlib
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AdmissionRound, AdmissionTrack, Campus, Institution, Program
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


class Phase14SeedError(ValueError):
    pass


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
        )
        session.add(row)
        session.flush()
    _assert_name(row.name, payload["campus_name"], "캠퍼스")
    return row


def _program(session: Session, campus: Campus, payload: dict[str, str]) -> Program:
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
        )
        session.add(row)
        session.flush()
    _assert_name(row.name, payload["program_name"], "학과")
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


__all__ = ["Phase14SeedError", "load_phase14_public_seed"]
