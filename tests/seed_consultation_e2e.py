from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    AdmissionEligibilityRule,
    AdmissionTrack,
    GradeSourceScopeRule,
    Program,
    ScoreRule,
    SourceCitation,
)
from tests.test_consultation_routes import _seed
from tests.test_consultations import (
    _eligibility_payload,
    _metadata,
    _persist_published_rules,
    _score_payload,
)


def _seed_second_program(session: Session, first_track_id: str) -> None:
    first_track = session.get(AdmissionTrack, first_track_id)
    assert first_track is not None
    first_program = session.get(Program, first_track.program_id)
    assert first_program is not None
    first_rule = (
        session.query(AdmissionEligibilityRule).filter_by(admission_track_id=first_track.id).one()
    )
    citation = session.get(SourceCitation, first_rule.source_citation_id)
    assert citation is not None
    program = Program(campus_id=first_program.campus_id, name="합성 두번째 학과", code="P2")
    session.add(program)
    session.flush()
    track = AdmissionTrack(
        admission_round_id=first_track.admission_round_id,
        program_id=program.id,
        code="SECOND",
        name="두번째 합성 전형",
    )
    session.add(track)
    session.flush()
    _persist_published_rules(
        session,
        [
            AdmissionEligibilityRule(
                version="eligibility-second-v1",
                rule_payload=_eligibility_payload(),
                **_metadata(track, citation),
            ),
            GradeSourceScopeRule(
                version="scope-second-v1",
                rule_payload={"schema_version": 1, "policy": "HOME_ONLY"},
                **_metadata(track, citation),
            ),
            ScoreRule(
                version="score-second-v1",
                rule_payload=_score_payload(),
                admission_year=2027,
                university_code="SYNTHETIC_U",
                university_name="합성 상담 전문대",
                campus_code="MAIN",
                admission_round="EARLY_1",
                admission_track_code="SECOND",
                admission_track_name="두번째 합성 전형",
                evidence_document_ref=citation.source_document_id,
                evidence_page=citation.page_number,
                evidence_location=citation.locator,
                source_status="FINAL_GUIDE",
                change_reason="Phase 13 복수 학과 합성 E2E",
                **_metadata(track, citation),
            ),
        ],
    )
    session.commit()


def _seed_status_programs(session: Session, first_track_id: str) -> None:
    first_track = session.get(AdmissionTrack, first_track_id)
    assert first_track is not None
    first_program = session.get(Program, first_track.program_id)
    assert first_program is not None
    first_rule = (
        session.query(AdmissionEligibilityRule).filter_by(admission_track_id=first_track.id).one()
    )
    citation = session.get(SourceCitation, first_rule.source_citation_id)
    assert citation is not None

    ineligible_program = Program(
        campus_id=first_program.campus_id,
        name="합성 자격미달 학과",
        code="P_INELIGIBLE",
    )
    preparing_program = Program(
        campus_id=first_program.campus_id,
        name="합성 준비중 학과",
        code="P_PREPARING",
    )
    session.add_all([ineligible_program, preparing_program])
    session.flush()
    ineligible_track = AdmissionTrack(
        admission_round_id=first_track.admission_round_id,
        program_id=ineligible_program.id,
        code="INELIGIBLE",
        name="합성 자격미달 전형",
    )
    preparing_track = AdmissionTrack(
        admission_round_id=first_track.admission_round_id,
        program_id=preparing_program.id,
        code="PREPARING",
        name="합성 규칙 준비중 전형",
    )
    session.add_all([ineligible_track, preparing_track])
    session.flush()
    _persist_published_rules(
        session,
        [
            AdmissionEligibilityRule(
                version="eligibility-ineligible-v1",
                rule_payload={
                    "schema_version": 1,
                    "cases": [],
                    "default": {
                        "status": "INELIGIBLE",
                        "reason_code": "SYNTHETIC_INELIGIBLE",
                    },
                },
                **_metadata(ineligible_track, citation),
            )
        ],
    )
    session.commit()


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url or not database_url.startswith("postgresql+"):
        raise RuntimeError("합성 E2E seed에는 PostgreSQL DATABASE_URL이 필요합니다.")
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            first_track_id = _seed(session)
            _seed_second_program(session, first_track_id)
            _seed_status_programs(session, first_track_id)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
