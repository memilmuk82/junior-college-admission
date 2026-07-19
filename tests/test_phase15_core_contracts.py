from __future__ import annotations

from decimal import Decimal

from werkzeug.datastructures import MultiDict

from app.crawlers.procollege import ProcollegeAdapter
from app.routes import _public_target_values
from app.services.admission_results import (
    AdmissionResultKey,
    SourceResponse,
    collect_admission_result_raw,
    stage_admission_result_raw,
)


class FixtureTransport:
    def fetch(self, request, *, timeout_seconds: int):  # type: ignore[no-untyped-def]
        assert timeout_seconds == 15
        body = """
        <html><table class="defTable"><tbody><tr>
          <td>서울</td><td>합성전문대</td><td>수시1차</td><td>컴퓨터학과</td>
          <td>20</td><td>주간</td><td>일반전형</td><td>일반고</td>
          <td>-</td><td>석차등급</td><td>2.5:1</td><td>-</td>
          <td>4.25</td><td>-</td><td>6.10</td>
        </tr></tbody></table></html>
        """.encode()
        return SourceResponse(200, "text/html; charset=utf-8", body)


def test_public_consultation_forces_the_approved_2027_cohort() -> None:
    values = _public_target_values(
        MultiDict(
            {
                "academic_year": "2029",
                "home_school_type": "VOCATIONAL",
                "graduation_status": "GRADUATED",
                "vocational_training_status": "NONE",
                "ged": "TRUE",
            }
        )
    )

    assert values["academic_year"] == "2027"
    assert values["home_school_type"] == "GENERAL"
    assert values["final_school_type"] == "GENERAL"
    assert values["graduation_status"] == "EXPECTED"
    assert values["vocational_training_status"] == "PARTICIPATING"
    assert values["ged"] == "FALSE"


def test_procollege_fixture_uses_the_existing_raw_and_staging_contract() -> None:
    adapter = ProcollegeAdapter(
        page_count=1,
        key_resolver=lambda _raw: AdmissionResultKey(
            academic_year=2026,
            university_code="SYNTHETIC",
            campus_code="MAIN",
            admission_round="EARLY_1",
            admission_track_code="GENERAL",
            program_code="CS",
        ),
    )
    raw = collect_admission_result_raw(
        adapter,
        FixtureTransport(),
        academic_year=2026,
        wait=lambda _seconds: None,
    )
    staged = stage_admission_result_raw(raw, adapter)

    assert raw.row_count == 1
    assert raw.pages[0].rows[0].as_dict()["대학명"] == "합성전문대"
    assert staged.status == "READY"
    candidate = staged.rows[0].candidate
    assert candidate is not None
    assert candidate.competition_rate == Decimal("2.5")
    assert candidate.average_score == Decimal("4.25")
    assert candidate.lowest_score == Decimal("6.10")
