from __future__ import annotations

from app.services.eligibility import StudentFacts

VOCATIONAL_CURRENT = "VOCATIONAL_CURRENT"
GENERAL_GRADUATE = "GENERAL_GRADUATE"
PUBLIC_STUDENT_PROFILES = frozenset({VOCATIONAL_CURRENT, GENERAL_GRADUATE})


def resolve_public_student_profile(value: str | None) -> str:
    normalized = (value or "").strip() or VOCATIONAL_CURRENT
    if normalized not in PUBLIC_STUDENT_PROFILES:
        raise ValueError("학생 구분을 확인하세요.")
    return normalized


def public_student_fact_values(profile: str) -> dict[str, str]:
    resolved = resolve_public_student_profile(profile)
    facts = {
        "student_profile": resolved,
        "home_school_type": "GENERAL",
        "final_school_type": "GENERAL",
        "ged": "FALSE",
    }
    if resolved == VOCATIONAL_CURRENT:
        facts.update(
            graduation_status="EXPECTED",
            vocational_training_status="PARTICIPATING",
        )
    else:
        facts.update(
            graduation_status="GRADUATED",
            vocational_training_status="NONE",
        )
    return facts


def public_record_classification(profile: str, *, grade: int) -> tuple[str, bool]:
    resolved = resolve_public_student_profile(profile)
    if grade not in {1, 2, 3}:
        raise ValueError("학년은 1~3만 입력할 수 있습니다.")
    if grade == 3 and resolved == VOCATIONAL_CURRENT:
        return "VOCATIONAL_TRAINING_RECORD", True
    return "HOME_SCHOOL_RECORD", False


def student_profile_from_facts(facts: StudentFacts) -> str:
    """Map the two supported public profiles from explicit consultation facts."""
    if (
        facts.home_school_type == "GENERAL"
        and facts.final_school_type == "GENERAL"
        and facts.graduation_status == "GRADUATED"
        and facts.vocational_training_status == "NONE"
        and facts.ged is not True
    ):
        return GENERAL_GRADUATE
    return VOCATIONAL_CURRENT


__all__ = [
    "GENERAL_GRADUATE",
    "PUBLIC_STUDENT_PROFILES",
    "VOCATIONAL_CURRENT",
    "public_record_classification",
    "public_student_fact_values",
    "resolve_public_student_profile",
    "student_profile_from_facts",
]
