from __future__ import annotations

import re
from collections.abc import Mapping

from sqlalchemy.orm import Session

from app.models import AdmissionRound, AdmissionTrack, Campus, Institution, Program

CODE_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9_-]{0,119}\Z")
INSTITUTION_TYPES = frozenset({"JUNIOR_COLLEGE", "POLYTECHNIC"})


class CatalogValidationError(ValueError):
    """관리자 기준정보 입력이 유효하지 않을 때 발생한다."""


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
    raw = form.get(name, "").strip().upper()
    if not raw:
        if required:
            raise CatalogValidationError(f"{label}을(를) 입력하세요.")
        return None
    if len(raw) > maximum or not CODE_PATTERN.fullmatch(raw):
        raise CatalogValidationError(
            f"{label}은(는) 영문 대문자, 숫자, 밑줄, 하이픈만 사용할 수 있습니다."
        )
    return raw


def _existing(session: Session, model: type, record_id: str, label: str):  # type: ignore[no-untyped-def]
    record = session.get(model, record_id)
    if record is None:
        raise CatalogValidationError(f"선택한 {label} 정보를 찾을 수 없습니다.")
    return record


def create_institution(session: Session, form: Mapping[str, str]) -> Institution:
    institution_type = _required(
        form, "institution_type", "기관 유형", maximum=40
    ).upper()
    if institution_type not in INSTITUTION_TYPES:
        raise CatalogValidationError("기관 유형을 확인하세요.")
    record = Institution(
        code=_code(form, "code", "대학 코드", required=False),
        name=_required(form, "name", "대학명", maximum=200),
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
    record = Campus(
        institution_id=institution.id,
        code=_code(form, "code", "캠퍼스 코드", required=False),
        name=_required(form, "name", "캠퍼스명", maximum=200),
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
    record = Program(
        campus_id=campus.id,
        code=_code(form, "code", "학과 코드", required=False, maximum=120),
        name=_required(form, "name", "학과명", maximum=200),
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
    record = AdmissionRound(
        institution_id=institution.id,
        academic_year=academic_year,
        code=_code(form, "code", "모집시기 코드", required=True),
        name=_required(form, "name", "모집시기명", maximum=200),
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
    record = AdmissionTrack(
        admission_round_id=admission_round.id,
        program_id=program.id,
        code=_code(form, "code", "전형 코드", required=True),
        name=_required(form, "name", "전형명", maximum=200),
    )
    session.add(record)
    session.flush()
    return record

