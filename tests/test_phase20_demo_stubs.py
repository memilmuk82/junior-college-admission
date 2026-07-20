from __future__ import annotations

from pathlib import Path

from app.crawlers.procollege import ProcollegeAdapter
from app.services.admission_results import collect_admission_result_raw
from app.services.demo_ai_provider import DemoNarrativeProvider
from app.services.demo_crawler_fixture import DemoPhase17ProcollegeTransport


def test_demo_crawler_uses_reviewed_public_seed_without_network_or_synthetic_college() -> None:
    delays: list[int] = []
    collection = collect_admission_result_raw(
        ProcollegeAdapter(page_count=2),
        DemoPhase17ProcollegeTransport(Path(__file__).resolve().parents[1]),
        academic_year=2026,
        wait=delays.append,
    )

    assert collection.row_count == 20
    assert delays == [1]
    institutions = {row.as_dict()["대학명"] for page in collection.pages for row in page.rows}
    assert institutions
    assert "합성전문대" not in institutions
    assert all(
        row.as_dict()["모집학년도"] == 2026 for page in collection.pages for row in page.rows
    )


def test_demo_ai_provider_uses_payload_and_key_without_external_transport() -> None:
    provider = DemoNarrativeProvider("OPENAI")

    draft = provider.generate(
        {"schema_version": 3, "academic_year": 2027, "results": [{"status": "READY"}]},
        "synthetic-session-key",
    )

    assert "검증된 지원자격" in draft.text
    assert "합격 가능" not in draft.text
    assert len(draft.check_items) == 2
