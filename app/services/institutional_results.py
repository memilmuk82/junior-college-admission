from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AdmissionRound,
    AdmissionTrack,
    Campus,
    Institution,
    InstitutionApplicationOutcome,
    Program,
    UserAccount,
)
from app.services.membership import has_teacher_capability, is_demo_actor_ref

ANONYMOUS_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}\Z")
OUTCOME_STATUSES = frozenset({"INITIAL_ACCEPTED", "WAITLIST_ACCEPTED", "REJECTED", "UNKNOWN"})
SOURCE_STATUSES = frozenset(
    {"STUDENT_REPORTED", "TEACHER_CONFIRMED", "OFFICIAL_CONFIRMED", "UNCONFIRMED"}
)


class InstitutionalResultError(ValueError):
    pass


@dataclass(frozen=True)
class TrackOption:
    track_id: str
    institution_id: str
    institution_name: str
    campus_name: str
    program_id: str
    program_name: str
    round_name: str
    track_name: str

    @property
    def label(self) -> str:
        return (
            f"{self.institution_name} · {self.campus_name} · {self.program_name} · "
            f"{self.round_name} · {self.track_name}"
        )


@dataclass(frozen=True)
class InstitutionalOutcomeView:
    outcome: InstitutionApplicationOutcome
    track: TrackOption


@dataclass(frozen=True)
class OutcomeSummary:
    total: int
    initial_accepted: int
    waitlist_accepted: int
    rejected: int
    unknown: int


def list_track_options(session: Session, *, academic_year: int) -> tuple[TrackOption, ...]:
    rows = session.execute(
        select(AdmissionTrack, AdmissionRound, Program, Campus, Institution)
        .join(AdmissionRound, AdmissionRound.id == AdmissionTrack.admission_round_id)
        .join(Program, Program.id == AdmissionTrack.program_id)
        .join(Campus, Campus.id == Program.campus_id)
        .join(Institution, Institution.id == Campus.institution_id)
        .where(AdmissionRound.academic_year == academic_year)
        .order_by(
            Institution.name,
            Campus.name,
            Program.name,
            AdmissionRound.name,
            AdmissionTrack.name,
        )
    )
    return tuple(
        TrackOption(
            track_id=track.id,
            institution_id=institution.id,
            institution_name=institution.name,
            campus_name=campus.name,
            program_id=program.id,
            program_name=program.name,
            round_name=round.name,
            track_name=track.name,
        )
        for track, round, program, campus, institution in rows
    )


def create_outcome(
    session: Session,
    *,
    user: UserAccount,
    values: Mapping[str, str],
) -> InstitutionApplicationOutcome:
    if not has_teacher_capability(user):
        raise InstitutionalResultError("활성 교사 계정만 기관 결과를 저장할 수 있습니다.")
    student_code = values.get("anonymous_student_code", "").strip()
    if not ANONYMOUS_CODE.fullmatch(student_code):
        raise InstitutionalResultError(
            "익명 학생 코드는 영문·숫자로 시작하는 1~40자의 영문·숫자·_-만 허용합니다."
        )
    academic_year = _required_integer(
        values.get("academic_year", ""), label="모집학년도", minimum=2000, maximum=2100
    )
    track_id = values.get("admission_track_id", "").strip()
    track = session.get(AdmissionTrack, track_id)
    if track is None:
        raise InstitutionalResultError("대학·학과·전형을 확인하세요.")
    round_year = session.scalar(
        select(AdmissionRound.academic_year).where(AdmissionRound.id == track.admission_round_id)
    )
    if round_year != academic_year:
        raise InstitutionalResultError("모집학년도와 전형의 학년도가 일치하지 않습니다.")
    outcome_status = values.get("outcome_status", "").strip()
    source_status = values.get("source_status", "").strip()
    if outcome_status not in OUTCOME_STATUSES:
        raise InstitutionalResultError("합격 결과 상태를 확인하세요.")
    if source_status not in SOURCE_STATUSES:
        raise InstitutionalResultError("결과 출처 상태를 확인하세요.")
    note = values.get("notes", "").strip()
    if len(note) > 1000:
        raise InstitutionalResultError("메모는 1,000자 이하여야 합니다.")
    outcome = InstitutionApplicationOutcome(
        managed_by_user_account_id=user.id,
        anonymous_student_code=student_code,
        academic_year=academic_year,
        admission_track_id=track.id,
        reflected_grade=_optional_decimal(values.get("reflected_grade", "")),
        outcome_status=outcome_status,
        initial_waitlist_number=_optional_integer(values.get("initial_waitlist_number", "")),
        final_waitlist_number=_optional_integer(values.get("final_waitlist_number", "")),
        source_status=source_status,
        notes=note or None,
    )
    session.add(outcome)
    return outcome


def list_outcomes(
    session: Session,
    *,
    user: UserAccount,
    academic_year: int | None = None,
    institution_id: str = "",
    program_id: str = "",
    admission_track_id: str = "",
    outcome_status: str = "",
) -> tuple[InstitutionalOutcomeView, ...]:
    if not has_teacher_capability(user):
        raise InstitutionalResultError("기관 결과 조회 권한이 없습니다.")
    statement = (
        select(
            InstitutionApplicationOutcome,
            AdmissionTrack,
            AdmissionRound,
            Program,
            Campus,
            Institution,
        )
        .join(AdmissionTrack, AdmissionTrack.id == InstitutionApplicationOutcome.admission_track_id)
        .join(AdmissionRound, AdmissionRound.id == AdmissionTrack.admission_round_id)
        .join(Program, Program.id == AdmissionTrack.program_id)
        .join(Campus, Campus.id == Program.campus_id)
        .join(Institution, Institution.id == Campus.institution_id)
    )
    if user.role != "ADMIN" or is_demo_actor_ref(user.actor_ref):
        statement = statement.where(
            InstitutionApplicationOutcome.managed_by_user_account_id == user.id
        )
    if academic_year is not None:
        statement = statement.where(InstitutionApplicationOutcome.academic_year == academic_year)
    if institution_id:
        statement = statement.where(Institution.id == institution_id)
    if program_id:
        statement = statement.where(Program.id == program_id)
    if admission_track_id:
        statement = statement.where(AdmissionTrack.id == admission_track_id)
    if outcome_status:
        if outcome_status not in OUTCOME_STATUSES:
            raise InstitutionalResultError("합격 결과 필터를 확인하세요.")
        statement = statement.where(InstitutionApplicationOutcome.outcome_status == outcome_status)
    rows = session.execute(
        statement.order_by(
            InstitutionApplicationOutcome.academic_year.desc(),
            Institution.name,
            Program.name,
            InstitutionApplicationOutcome.anonymous_student_code,
        )
    )
    return tuple(
        InstitutionalOutcomeView(
            outcome=outcome,
            track=TrackOption(
                track_id=track.id,
                institution_id=institution.id,
                institution_name=institution.name,
                campus_name=campus.name,
                program_id=program.id,
                program_name=program.name,
                round_name=round.name,
                track_name=track.name,
            ),
        )
        for outcome, track, round, program, campus, institution in rows
    )


def summarize_outcomes(rows: tuple[InstitutionalOutcomeView, ...]) -> OutcomeSummary:
    counts = Counter(row.outcome.outcome_status for row in rows)
    return OutcomeSummary(
        total=len(rows),
        initial_accepted=counts["INITIAL_ACCEPTED"],
        waitlist_accepted=counts["WAITLIST_ACCEPTED"],
        rejected=counts["REJECTED"],
        unknown=counts["UNKNOWN"],
    )


def delete_outcome(
    session: Session, *, user: UserAccount, outcome_id: str
) -> InstitutionApplicationOutcome:
    outcome = session.get(InstitutionApplicationOutcome, outcome_id)
    global_admin = user.role == "ADMIN" and not is_demo_actor_ref(user.actor_ref)
    if outcome is None or (not global_admin and outcome.managed_by_user_account_id != user.id):
        raise InstitutionalResultError("기관 결과를 찾을 수 없습니다.")
    session.delete(outcome)
    return outcome


def _optional_decimal(raw: str) -> Decimal | None:
    if not raw.strip():
        return None
    try:
        value = Decimal(raw.strip())
    except InvalidOperation as error:
        raise InstitutionalResultError("반영등급은 숫자로 입력하세요.") from error
    if not value.is_finite() or not Decimal("1") <= value <= Decimal("9"):
        raise InstitutionalResultError("반영등급은 1 이상 9 이하로 입력하세요.")
    return value


def _optional_integer(raw: str) -> int | None:
    if not raw.strip():
        return None
    try:
        value = int(raw.strip())
    except ValueError as error:
        raise InstitutionalResultError("예비번호는 양의 정수로 입력하세요.") from error
    if value <= 0:
        raise InstitutionalResultError("예비번호는 양의 정수로 입력하세요.")
    return value


def _required_integer(raw: str, *, label: str, minimum: int, maximum: int) -> int:
    try:
        value = int(raw.strip())
    except ValueError as error:
        raise InstitutionalResultError(f"{label}은 정수로 입력하세요.") from error
    if not minimum <= value <= maximum:
        raise InstitutionalResultError(f"{label}은 {minimum} 이상 {maximum} 이하입니다.")
    return value


__all__ = [
    "InstitutionalOutcomeView",
    "InstitutionalResultError",
    "OutcomeSummary",
    "TrackOption",
    "create_outcome",
    "delete_outcome",
    "list_outcomes",
    "list_track_options",
    "summarize_outcomes",
]
