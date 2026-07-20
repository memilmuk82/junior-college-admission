from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import SavedConsultation, StudentAcademicRecord, StudentCourseRecord, UserAccount
from app.services.ai_payloads import validated_saved_payload_copy
from app.services.public_student_profiles import (
    VOCATIONAL_CURRENT,
    resolve_public_student_profile,
)
from app.services.score_inputs import AcademicRecordInput, CourseRecordInput
from app.services.structured_imports import NormalizedCourseRow, ScoreValue
from app.services.temporary_uploads import TemporaryUploadStore

ANONYMOUS_STATE_FILENAME = "anonymous-calculation.json"
ANONYMOUS_SESSION_TTL = timedelta(minutes=30)
MAX_ANONYMOUS_STATE_BYTES = 2 * 1024 * 1024


class AnonymousCalculationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AnonymousCalculationState:
    owner_token: str
    created_at: datetime
    expires_at: datetime
    record_source: str
    is_vocational_training_semester: bool
    rows: tuple[NormalizedCourseRow, ...]
    student_profile: str = VOCATIONAL_CURRENT
    consultation_snapshot: dict[str, Any] | None = None


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _integer(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(str(value))


def _text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _row_payload(row: NormalizedCourseRow) -> dict[str, object]:
    return {
        "academic_year": row.academic_year,
        "grade": row.grade,
        "semester": row.semester,
        "subject_group": row.subject_group,
        "subject_name": row.subject_name,
        "credits": str(row.credits) if row.credits is not None else None,
        "raw_score": str(row.raw_score) if row.raw_score is not None else None,
        "course_mean": str(row.course_mean) if row.course_mean is not None else None,
        "standard_deviation": (
            str(row.standard_deviation) if row.standard_deviation is not None else None
        ),
        "achievement_level": row.achievement_level,
        "enrollment_count": row.enrollment_count,
        "rank_grade": str(row.rank_grade) if row.rank_grade is not None else None,
        "source_sheet": row.source_sheet,
        "source_row_number": row.source_row_number,
        "source_page": row.source_page,
        "record_source": row.record_source,
        "is_vocational_training_semester": row.is_vocational_training_semester,
    }


def _row_from_payload(payload: dict[str, Any]) -> NormalizedCourseRow:
    raw_value = payload.get("raw_score")
    raw_score: ScoreValue = "P" if raw_value == "P" else _decimal(raw_value)
    return NormalizedCourseRow(
        academic_year=_integer(payload.get("academic_year")),
        grade=_integer(payload.get("grade")),
        semester=_integer(payload.get("semester")),
        subject_group=_text(payload.get("subject_group")),
        subject_name=_text(payload.get("subject_name")),
        credits=_decimal(payload.get("credits")),
        raw_score=raw_score,
        course_mean=_decimal(payload.get("course_mean")),
        standard_deviation=_decimal(payload.get("standard_deviation")),
        achievement_level=_text(payload.get("achievement_level")),
        enrollment_count=_integer(payload.get("enrollment_count")),
        rank_grade=_decimal(payload.get("rank_grade")),
        source_sheet=_text(payload.get("source_sheet")),
        source_row_number=_integer(payload.get("source_row_number")),
        source_page=_integer(payload.get("source_page")),
        record_source=_text(payload.get("record_source")),
        is_vocational_training_semester=(
            bool(payload["is_vocational_training_semester"])
            if payload.get("is_vocational_training_semester") is not None
            else None
        ),
    )


class AnonymousCalculationStore:
    def __init__(self, upload_store: TemporaryUploadStore) -> None:
        self.upload_store = upload_store

    def _path(self, calculation_id: str) -> Path:
        return self.upload_store.session_path(calculation_id) / "derived" / ANONYMOUS_STATE_FILENAME

    def save(
        self,
        calculation_id: str,
        *,
        owner_token: str,
        record_source: str,
        is_vocational_training_semester: bool,
        rows: tuple[NormalizedCourseRow, ...],
        student_profile: str = VOCATIONAL_CURRENT,
    ) -> AnonymousCalculationState:
        if not owner_token or not rows:
            raise AnonymousCalculationError("익명 계산 상태가 유효하지 않습니다.")
        now = datetime.now(UTC)
        state = AnonymousCalculationState(
            owner_token=owner_token,
            created_at=now,
            expires_at=now + ANONYMOUS_SESSION_TTL,
            record_source=record_source,
            is_vocational_training_semester=is_vocational_training_semester,
            rows=rows,
            student_profile=resolve_public_student_profile(student_profile),
        )
        self._write_state(calculation_id, state)
        self.purge_originals(calculation_id)
        return state

    def _write_state(self, calculation_id: str, state: AnonymousCalculationState) -> None:
        payload = {
            "owner_token": state.owner_token,
            "created_at": state.created_at.isoformat(),
            "expires_at": state.expires_at.isoformat(),
            "record_source": state.record_source,
            "is_vocational_training_semester": state.is_vocational_training_semester,
            "rows": [_row_payload(row) for row in state.rows],
            "student_profile": state.student_profile,
            "consultation_snapshot": state.consultation_snapshot,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        if len(encoded) > MAX_ANONYMOUS_STATE_BYTES:
            raise AnonymousCalculationError("익명 계산 상태 크기 제한을 초과했습니다.")
        path = self._path(calculation_id)
        path.parent.mkdir(mode=0o700, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        try:
            with temporary.open("wb") as output:
                output.write(encoded)
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def attach_consultation_snapshot(
        self,
        calculation_id: str,
        *,
        owner_token: str,
        snapshot: dict[str, Any],
    ) -> AnonymousCalculationState:
        state = self.load(calculation_id, owner_token=owner_token)
        updated = AnonymousCalculationState(
            owner_token=state.owner_token,
            created_at=state.created_at,
            expires_at=state.expires_at,
            record_source=state.record_source,
            is_vocational_training_semester=state.is_vocational_training_semester,
            rows=state.rows,
            student_profile=state.student_profile,
            consultation_snapshot=snapshot,
        )
        self._write_state(calculation_id, updated)
        return updated

    def load(self, calculation_id: str, *, owner_token: str) -> AnonymousCalculationState:
        path = self._path(calculation_id)
        if not path.is_file() or path.stat().st_size > MAX_ANONYMOUS_STATE_BYTES:
            raise AnonymousCalculationError("익명 계산 세션을 찾을 수 없습니다.")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            state = AnonymousCalculationState(
                owner_token=str(payload["owner_token"]),
                created_at=datetime.fromisoformat(str(payload["created_at"])),
                expires_at=datetime.fromisoformat(str(payload["expires_at"])),
                record_source=str(payload["record_source"]),
                is_vocational_training_semester=bool(payload["is_vocational_training_semester"]),
                rows=tuple(_row_from_payload(row) for row in payload["rows"]),
                student_profile=resolve_public_student_profile(
                    _text(payload.get("student_profile"))
                ),
                consultation_snapshot=(
                    dict(payload["consultation_snapshot"])
                    if isinstance(payload.get("consultation_snapshot"), dict)
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise AnonymousCalculationError("익명 계산 상태를 읽을 수 없습니다.") from error
        if state.owner_token != owner_token:
            raise AnonymousCalculationError("익명 계산 세션을 찾을 수 없습니다.")
        if state.expires_at <= datetime.now(UTC):
            self.upload_store.purge_session(calculation_id)
            raise AnonymousCalculationError("익명 계산 세션이 만료되었습니다.")
        return state

    def purge_originals(self, calculation_id: str) -> None:
        original = self.upload_store.session_path(calculation_id) / "original"
        if original.exists():
            shutil.rmtree(original)
        if original.exists():
            raise AnonymousCalculationError("업로드 원본 삭제를 확인하지 못했습니다.")


def to_academic_record_inputs(
    state: AnonymousCalculationState,
) -> tuple[AcademicRecordInput, ...]:
    grouped: dict[tuple[int, int, int, str, bool], list[tuple[int, NormalizedCourseRow]]] = {}
    for index, row in enumerate(state.rows):
        if row.academic_year is None or row.grade is None or row.semester is None:
            raise AnonymousCalculationError("확정 성적의 학년도·학년·학기가 누락되었습니다.")
        record_source = row.record_source or state.record_source
        is_vocational = (
            row.is_vocational_training_semester
            if row.is_vocational_training_semester is not None
            else state.is_vocational_training_semester
        )
        grouped.setdefault(
            (row.academic_year, row.grade, row.semester, record_source, is_vocational),
            [],
        ).append((index, row))

    records: list[AcademicRecordInput] = []
    for record_index, (term, rows) in enumerate(sorted(grouped.items())):
        academic_year, grade, semester, record_source, is_vocational = term
        courses = tuple(
            CourseRecordInput(
                course_record_id=f"anonymous-course-{record_index}-{row_index}",
                subject_group=row.subject_group,
                subject_name=row.subject_name or "",
                credits=row.credits,
                raw_score=row.raw_score if isinstance(row.raw_score, Decimal) else None,
                raw_score_label="P" if row.raw_score == "P" else None,
                course_mean=row.course_mean,
                standard_deviation=row.standard_deviation,
                achievement_level=row.achievement_level,
                enrollment_count=row.enrollment_count,
                rank_grade=row.rank_grade,
                user_verified=True,
            )
            for row_index, row in rows
        )
        records.append(
            AcademicRecordInput(
                academic_record_id=f"anonymous-record-{record_index}",
                academic_year=academic_year,
                grade=grade,
                semester=semester,
                record_source=record_source,
                is_vocational_training_semester=is_vocational,
                verification_status="USER_VERIFIED",
                courses=courses,
            )
        )
    return tuple(records)


def save_anonymous_records(
    session: Session,
    *,
    state: AnonymousCalculationState,
    calculation_id: str,
    user: UserAccount,
) -> tuple[str, ...]:
    if user.status != "ACTIVE" or user.role not in {"STUDENT", "TEACHER"}:
        raise AnonymousCalculationError("활성 학생 또는 교사 계정만 성적을 저장할 수 있습니다.")
    student_id = (
        f"account:{user.id}" if user.role == "STUDENT" else f"teacher:{user.id}:{calculation_id}"
    )
    if user.role == "TEACHER" and session.scalar(
        select(StudentAcademicRecord.id).where(StudentAcademicRecord.student_id == student_id)
    ):
        raise AnonymousCalculationError("이 익명 계산 성적은 이미 저장되었거나 중복됩니다.")
    saved: list[StudentAcademicRecord] = []
    for record in to_academic_record_inputs(state):
        stored = session.scalar(
            select(StudentAcademicRecord)
            .where(
                StudentAcademicRecord.student_id == student_id,
                StudentAcademicRecord.academic_year == record.academic_year,
                StudentAcademicRecord.grade == record.grade,
                StudentAcademicRecord.semester == record.semester,
                StudentAcademicRecord.record_source == record.record_source,
            )
            .with_for_update()
        )
        if stored is None:
            stored = StudentAcademicRecord(
                student_id=student_id,
                owner_user_account_id=user.id if user.role == "STUDENT" else None,
                managed_by_user_account_id=user.id if user.role == "TEACHER" else None,
                academic_year=record.academic_year,
                grade=record.grade,
                semester=record.semester,
                record_source=record.record_source,
                is_vocational_training_semester=record.is_vocational_training_semester,
                verification_status="USER_VERIFIED",
            )
            session.add(stored)
            session.flush()
        else:
            if (
                user.role != "STUDENT"
                or stored.owner_user_account_id != user.id
                or stored.managed_by_user_account_id is not None
            ):
                raise AnonymousCalculationError("다른 소유자의 성적과 충돌하여 저장할 수 없습니다.")
            stored.is_vocational_training_semester = record.is_vocational_training_semester
            stored.verification_status = "USER_VERIFIED"
            session.execute(
                delete(StudentCourseRecord).where(
                    StudentCourseRecord.academic_record_id == stored.id
                )
            )
        for course in record.courses:
            session.add(
                StudentCourseRecord(
                    academic_record_id=stored.id,
                    subject_group=course.subject_group,
                    subject_name=course.subject_name,
                    credits=course.credits,
                    raw_score=course.raw_score,
                    raw_score_label=course.raw_score_label,
                    course_mean=course.course_mean,
                    standard_deviation=course.standard_deviation,
                    achievement_level=course.achievement_level,
                    enrollment_count=course.enrollment_count,
                    rank_grade=course.rank_grade,
                    extraction_method="ANONYMOUS_CONFIRMED",
                    user_verified=True,
                )
            )
        saved.append(stored)
    return tuple(record.id for record in saved)


def save_anonymous_consultation(
    session: Session,
    *,
    state: AnonymousCalculationState,
    calculation_id: str,
    user: UserAccount,
    counselor_note: str = "",
) -> SavedConsultation:
    if user.status != "ACTIVE" or user.role not in {"STUDENT", "TEACHER"}:
        raise AnonymousCalculationError("활성 학생 또는 교사만 상담 결과를 저장할 수 있습니다.")
    snapshot = state.consultation_snapshot
    if not isinstance(snapshot, dict):
        raise AnonymousCalculationError("먼저 대학·학과 계산 결과를 확인해야 저장할 수 있습니다.")
    if session.scalar(
        select(SavedConsultation.id).where(SavedConsultation.calculation_id == calculation_id)
    ):
        raise AnonymousCalculationError("이 계산 결과는 이미 저장되었습니다.")
    note = counselor_note.strip()
    if user.role != "TEACHER" and note:
        raise AnonymousCalculationError("교사 계정만 상담 메모를 저장할 수 있습니다.")
    if len(note) > 2000:
        raise AnonymousCalculationError("상담 메모는 2,000자 이하여야 합니다.")
    payload = snapshot.get("result_snapshot")
    targets = snapshot.get("selected_targets")
    academic_year = snapshot.get("academic_year")
    if (
        not isinstance(payload, dict)
        or not isinstance(targets, list)
        or not isinstance(academic_year, int)
    ):
        raise AnonymousCalculationError("저장할 상담 결과 구조가 유효하지 않습니다.")
    try:
        durable_payload = validated_saved_payload_copy(payload)
    except ValueError as error:
        raise AnonymousCalculationError("저장할 상담 결과 구조가 유효하지 않습니다.") from error
    target_keys = frozenset({"program_id", "institution_name", "campus_name", "program_name"})
    if any(
        not isinstance(target, dict)
        or frozenset(target) != target_keys
        or not all(isinstance(target[key], str) and target[key] for key in target_keys)
        for target in targets
    ):
        raise AnonymousCalculationError("저장할 대학·학과 선택 구조가 유효하지 않습니다.")
    student_reference = (
        f"account:{user.id}" if user.role == "STUDENT" else f"teacher:{user.id}:{calculation_id}"
    )
    saved = SavedConsultation(
        calculation_id=calculation_id,
        student_reference=student_reference,
        owner_user_account_id=user.id if user.role == "STUDENT" else None,
        managed_by_user_account_id=user.id if user.role == "TEACHER" else None,
        academic_year=academic_year,
        student_profile=state.student_profile,
        selected_targets=targets,
        result_snapshot=durable_payload,
        student_print_snapshot={"audience": "STUDENT", "result": durable_payload},
        teacher_print_snapshot={"audience": "TEACHER", "result": durable_payload},
        counselor_note=note or None,
    )
    session.add(saved)
    session.flush()
    return saved


__all__ = [
    "AnonymousCalculationError",
    "AnonymousCalculationState",
    "AnonymousCalculationStore",
    "save_anonymous_records",
    "save_anonymous_consultation",
    "to_academic_record_inputs",
]
