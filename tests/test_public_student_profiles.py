from __future__ import annotations

import pytest

from app.services.eligibility import StudentFacts
from app.services.public_student_profiles import (
    GENERAL_GRADUATE,
    VOCATIONAL_CURRENT,
    public_record_classification,
    public_student_fact_values,
    resolve_public_student_profile,
    student_profile_from_facts,
)


def test_public_student_profile_defaults_to_current_vocational_student() -> None:
    assert resolve_public_student_profile("") == VOCATIONAL_CURRENT
    assert resolve_public_student_profile(None) == VOCATIONAL_CURRENT


def test_public_student_profile_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="학생 구분"):
        resolve_public_student_profile("UNTRUSTED_PROFILE")


def test_current_vocational_profile_derives_facts_and_mixed_record_sources() -> None:
    assert public_student_fact_values(VOCATIONAL_CURRENT) == {
        "student_profile": VOCATIONAL_CURRENT,
        "home_school_type": "GENERAL",
        "final_school_type": "GENERAL",
        "graduation_status": "EXPECTED",
        "vocational_training_status": "PARTICIPATING",
        "ged": "FALSE",
    }
    assert public_record_classification(VOCATIONAL_CURRENT, grade=1) == (
        "HOME_SCHOOL_RECORD",
        False,
    )
    assert public_record_classification(VOCATIONAL_CURRENT, grade=2) == (
        "HOME_SCHOOL_RECORD",
        False,
    )
    assert public_record_classification(VOCATIONAL_CURRENT, grade=3) == (
        "VOCATIONAL_TRAINING_RECORD",
        True,
    )


def test_general_graduate_profile_derives_home_school_records_for_all_grades() -> None:
    assert public_student_fact_values(GENERAL_GRADUATE) == {
        "student_profile": GENERAL_GRADUATE,
        "home_school_type": "GENERAL",
        "final_school_type": "GENERAL",
        "graduation_status": "GRADUATED",
        "vocational_training_status": "NONE",
        "ged": "FALSE",
    }
    for grade in (1, 2, 3):
        assert public_record_classification(GENERAL_GRADUATE, grade=grade) == (
            "HOME_SCHOOL_RECORD",
            False,
        )


def test_public_record_classification_rejects_an_invalid_grade() -> None:
    with pytest.raises(ValueError, match="학년"):
        public_record_classification(VOCATIONAL_CURRENT, grade=4)


def test_saved_consultation_profile_uses_explicit_general_graduate_facts() -> None:
    assert (
        student_profile_from_facts(
            StudentFacts(
                home_school_type="GENERAL",
                final_school_type="GENERAL",
                graduation_status="GRADUATED",
                vocational_training_status="NONE",
                ged=False,
            )
        )
        == GENERAL_GRADUATE
    )
    assert (
        student_profile_from_facts(
            StudentFacts(
                home_school_type="GENERAL",
                final_school_type="GENERAL",
                graduation_status="EXPECTED",
                vocational_training_status="PARTICIPATING",
                ged=False,
            )
        )
        == VOCATIONAL_CURRENT
    )
