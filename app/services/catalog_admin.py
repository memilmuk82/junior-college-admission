from __future__ import annotations

import re
from collections.abc import Mapping

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import AdmissionRound, AdmissionTrack, Campus, Institution, Program

ASCII_CODE_PATTERN = re.compile(r"[A-Za-z0-9_-]+\Z", flags=re.ASCII)
INSTITUTION_TYPES = frozenset({"JUNIOR_COLLEGE", "POLYTECHNIC"})


class CatalogValidationError(ValueError):
    """관리자 기준정보 입력이 유효하지 않을 때 발생한다."""


class CatalogDuplicateError(CatalogValidationError):
    """동일 업무키의 기준정보가 이미 있을 때 발생한다."""


def _required(form: Mapping[str, str], name: str, label: str, *, maximum: int) -> str:
    value = form.get(name, "").strip()
    if not value:
        raise CatalogValidationError(f"{label}을(를) 입력하세요.")
    if len(value) > maximum:
        raise CatalogValidationError(f"{label}은(는) {maximum}자 이하여야 합니다.")
    return value


def _code(
    form: Mapping[str, str],
    name: str,
    label: str,
    *,
    required: bool,
    maximum: int = 80,
) -> str | None:
    raw = form.get(name, "").strip()
    if not raw:
        if required:
            raise CatalogValidationError(f"{label}을(를) 입력하세요.")
        return None
    if len(raw) > maximum or not ASCII_CODE_PATTERN.fullmatch(raw):
        raise CatalogValidationError(
            f"{label}은(는) 영문 대문자, 숫자, 밑줄, 하이픈만 사용할 수 있습니다."
        )
    return raw.upper()


def _existing(session: Session, model: type, record_id: str, label: str):  # type: ignore[no-untyped-def]
    record = session.get(model, record_id)
    if record is None:
        raise CatalogValidationError(f"선택한 {label} 정보를 찾을 수 없습니다.")
    return record


def create_institution(session: Session, form: Mapping[str, str]) -> Institution:
    institution_type = _required(form, "institution_type", "기관 유형", maximum=40).upper()
    if institution_type not in INSTITUTION_TYPES:
        raise CatalogValidationError("기관 유형을 확인하세요.")
    code = _code(form, "code", "대학 코드", required=True)
    assert code is not None
    name = _required(form, "name", "대학명", maximum=200)
    duplicate_id = session.scalar(
        select(Institution.id)
        .where(or_(Institution.code == code, Institution.name == name))
        .limit(1)
    )
    if duplicate_id is not None:
        raise CatalogDuplicateError("같은 대학 코드 또는 대학명이 이미 등록되어 있습니다.")
    record = Institution(
        code=code,
        name=name,
        institution_type=institution_type,
    )
    session.add(record)
    session.flush()
    return record


def create_campus(session: Session, form: Mapping[str, str]) -> Campus:
    institution = _existing(
        session,
        Institution,
        _required(form, "institution_id", "대학", maximum=36),
        "대학",
    )
    code = _code(form, "code", "캠퍼스 코드", required=True)
    assert code is not None
    name = _required(form, "name", "캠퍼스명", maximum=200)
    duplicate_id = session.scalar(
        select(Campus.id)
        .where(
            Campus.institution_id == institution.id,
            or_(Campus.code == code, Campus.name == name),
        )
        .limit(1)
    )
    if duplicate_id is not None:
        raise CatalogDuplicateError(
            "이 대학에 같은 캠퍼스 코드 또는 캠퍼스명이 이미 등록되어 있습니다."
        )
    record = Campus(
        institution_id=institution.id,
        code=code,
        name=name,
    )
    session.add(record)
    session.flush()
    return record


def create_program(session: Session, form: Mapping[str, str]) -> Program:
    campus = _existing(
        session,
        Campus,
        _required(form, "campus_id", "캠퍼스", maximum=36),
        "캠퍼스",
    )
    code = _code(form, "code", "학과 코드", required=True, maximum=120)
    assert code is not None
    name = _required(form, "name", "학과명", maximum=200)
    duplicate_id = session.scalar(
        select(Program.id)
        .where(
            Program.campus_id == campus.id,
            or_(Program.code == code, Program.name == name),
        )
        .limit(1)
    )
    if duplicate_id is not None:
        raise CatalogDuplicateError(
            "이 캠퍼스에 같은 학과 코드 또는 학과명이 이미 등록되어 있습니다."
        )
    record = Program(
        campus_id=campus.id,
        code=code,
        name=name,
    )
    session.add(record)
    session.flush()
    return record


def create_admission_round(session: Session, form: Mapping[str, str]) -> AdmissionRound:
    institution = _existing(
        session,
        Institution,
        _required(form, "institution_id", "대학", maximum=36),
        "대학",
    )
    raw_year = _required(form, "academic_year", "모집학년도", maximum=4)
    try:
        academic_year = int(raw_year)
    except ValueError as error:
        raise CatalogValidationError("모집학년도를 숫자로 입력하세요.") from error
    if not 2000 <= academic_year <= 2100:
        raise CatalogValidationError("모집학년도는 2000년부터 2100년 사이여야 합니다.")
    code = _code(form, "code", "모집시기 코드", required=True)
    assert code is not None
    name = _required(form, "name", "모집시기명", maximum=200)
    duplicate_id = session.scalar(
        select(AdmissionRound.id)
        .where(
            AdmissionRound.institution_id == institution.id,
            AdmissionRound.academic_year == academic_year,
            AdmissionRound.code == code,
        )
        .limit(1)
    )
    if duplicate_id is not None:
        raise CatalogDuplicateError(
            "이 대학의 같은 모집학년도와 모집시기 코드가 이미 등록되어 있습니다."
        )
    record = AdmissionRound(
        institution_id=institution.id,
        academic_year=academic_year,
        code=code,
        name=name,
    )
    session.add(record)
    session.flush()
    return record


def create_admission_track(session: Session, form: Mapping[str, str]) -> AdmissionTrack:
    admission_round = _existing(
        session,
        AdmissionRound,
        _required(form, "admission_round_id", "모집시기", maximum=36),
        "모집시기",
    )
    program = _existing(
        session,
        Program,
        _required(form, "program_id", "학과", maximum=36),
        "학과",
    )
    campus = _existing(session, Campus, program.campus_id, "학과의 캠퍼스")
    if campus.institution_id != admission_round.institution_id:
        raise CatalogValidationError("모집시기와 학과는 같은 대학에 속해야 합니다.")
    code = _code(form, "code", "전형 코드", required=True)
    assert code is not None
    name = _required(form, "name", "전형명", maximum=200)
    duplicate_id = session.scalar(
        select(AdmissionTrack.id)
        .where(
            AdmissionTrack.admission_round_id == admission_round.id,
            AdmissionTrack.program_id == program.id,
            AdmissionTrack.code == code,
        )
        .limit(1)
    )
    if duplicate_id is not None:
        raise CatalogDuplicateError("이 모집시기와 학과에 같은 전형 코드가 이미 등록되어 있습니다.")
    record = AdmissionTrack(
        admission_round_id=admission_round.id,
        program_id=program.id,
        code=code,
        name=name,
    )
    session.add(record)
    session.flush()
    return record
