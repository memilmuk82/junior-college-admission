from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SavedConsultation, StudentAcademicRecord, UserAccount, new_id
from app.services.ai_payloads import (
    build_anonymous_consultation_payload,
    validated_payload_copy,
)
from app.services.consultations import BatchConsultationResult
from app.services.public_student_profiles import resolve_public_student_profile
from app.services.student_record_access import can_read_academic_record


class AccountConsultationError(ValueError):
    pass


def save_account_consultation(
    session: Session,
    *,
    user: UserAccount,
    student_reference: str,
    result: BatchConsultationResult,
    student_profile: str,
    counselor_note: str = "",
) -> SavedConsultation:
    if user.status != "ACTIVE" or user.role not in {"STUDENT", "TEACHER"}:
        raise AccountConsultationError("활성 학생 또는 교사만 상담자료를 저장할 수 있습니다.")
    reference = student_reference.strip()
    if not reference or len(reference) > 120:
        raise AccountConsultationError("상담 대상 학생을 확인하세요.")
    records = tuple(
        session.scalars(
            select(StudentAcademicRecord).where(StudentAcademicRecord.student_id == reference)
        )
    )
    if not records or any(
        not can_read_academic_record(session, user=user, record=record) for record in records
    ):
        raise AccountConsultationError("연결되었거나 직접 관리하는 학생만 저장할 수 있습니다.")
    if user.role == "STUDENT" and reference != f"account:{user.id}":
        raise AccountConsultationError("학생은 본인 상담자료만 저장할 수 있습니다.")

    note = counselor_note.strip()
    if user.role != "TEACHER" and note:
        raise AccountConsultationError("상담 메모는 교사만 저장할 수 있습니다.")
    if len(note) > 2000:
        raise AccountConsultationError("상담 메모는 2,000자 이하여야 합니다.")

    payload = validated_payload_copy(build_anonymous_consultation_payload(result))
    resolved_student_profile = resolve_public_student_profile(student_profile)
    selected_targets = [
        {
            "program_id": program.program_id,
            "institution_name": program.institution_name,
            "campus_name": program.campus_name,
            "program_name": program.program_name,
        }
        for program in result.selected_programs
    ]
    saved = SavedConsultation(
        calculation_id=f"stored:{new_id()}",
        student_reference=reference,
        owner_user_account_id=user.id if user.role == "STUDENT" else None,
        managed_by_user_account_id=user.id if user.role == "TEACHER" else None,
        academic_year=result.academic_year,
        student_profile=resolved_student_profile,
        selected_targets=selected_targets,
        result_snapshot=payload,
        student_print_snapshot={"audience": "STUDENT", "result": payload},
        teacher_print_snapshot={"audience": "TEACHER", "result": payload},
        counselor_note=note or None,
    )
    session.add(saved)
    session.flush()
    return saved


__all__ = ["AccountConsultationError", "save_account_consultation"]
