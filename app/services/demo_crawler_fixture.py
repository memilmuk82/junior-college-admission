from __future__ import annotations

import csv
from html import escape
from pathlib import Path

from app.crawlers.procollege import PROCOLLEGE_ENDPOINT
from app.services.admission_results import SourceRequest, SourceResponse


class DemoPhase17ProcollegeTransport:
    """Render reviewed Phase 17 seed rows as bounded portal-like HTML pages."""

    def __init__(self, repository_root: Path, *, rows_per_page: int = 10) -> None:
        if not 1 <= rows_per_page <= 100:
            raise ValueError("체험 수집 페이지 행 수를 확인하세요.")
        path = repository_root / "data" / "seed" / "phase17_public_admission_results_2026.csv"
        with path.open(encoding="utf-8", newline="") as stream:
            self._rows = tuple(
                row for row in csv.DictReader(stream) if row.get("score_basis") == "RANK_GRADE"
            )
        if not self._rows:
            raise ValueError("체험 수집에 사용할 검수 공개 결과가 없습니다.")
        self._rows_per_page = rows_per_page

    def fetch(self, request: SourceRequest, *, timeout_seconds: int) -> SourceResponse:
        if request.endpoint != PROCOLLEGE_ENDPOINT or timeout_seconds <= 0:
            raise ValueError("체험 포털 수집 요청이 유효하지 않습니다.")
        parameters = dict(request.parameters)
        page_number = int(parameters.get("pageIndex", "0"))
        if page_number <= 0 or request.academic_year != 2026:
            raise ValueError("체험 포털 수집은 검수된 2026 결과만 제공합니다.")
        offset = (page_number - 1) * self._rows_per_page
        rows = self._rows[offset : offset + self._rows_per_page]
        body_rows = "".join(self._html_row(row) for row in rows)
        body = f'<html><table class="defTable"><tbody>{body_rows}</tbody></table></html>'
        return SourceResponse(200, "text/html; charset=utf-8", body.encode("utf-8"))

    @staticmethod
    def _html_row(row: dict[str, str]) -> str:
        values = (
            row.get("region", ""),
            row.get("institution_name", ""),
            row.get("admission_round_name", ""),
            row.get("program_name", ""),
            row.get("capacity", ""),
            "주간" if row.get("day_night") == "DAY" else "야간",
            row.get("admission_category", ""),
            row.get("admission_track_name", ""),
            "-",
            "석차등급",
            row.get("competition_rate", ""),
            "-",
            row.get("average_score", ""),
            "-",
            row.get("cutoff_score", ""),
        )
        return "<tr>" + "".join(f"<td>{escape(value or '-')}</td>" for value in values) + "</tr>"


__all__ = ["DemoPhase17ProcollegeTransport"]
