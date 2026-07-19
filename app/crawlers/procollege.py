from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

import requests

from app.services.admission_results import (
    AdmissionResultCandidate,
    AdmissionResultKey,
    CollectionPolicy,
    SourceRequest,
    SourceResponse,
    SourceTransportError,
)

PROCOLLEGE_ENDPOINT = "https://www.procollege.kr/web/entrance/webEntrancePreResult.do?"
PROCOLLEGE_COLUMNS = (
    "지역",
    "대학명",
    "모집시기",
    "전공명",
    "입학정원",
    "주/야",
    "전형구분",
    "출신교",
    "점수산출_수능",
    "점수산출_학생부",
    "경쟁률",
    "평균_수능",
    "평균_학생부",
    "최저_수능",
    "최저_학생부",
)


class _DefTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.table_depth = 0
        self.in_target_table = False
        self.in_cell = False
        self.current_cell: list[str] = []
        self.current_row: list[str] = []
        self.rows: list[tuple[str, ...]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table":
            classes = (attributes.get("class") or "").split()
            if self.in_target_table:
                self.table_depth += 1
            elif "defTable" in classes:
                self.in_target_table = True
                self.table_depth = 1
        elif self.in_target_table and tag == "tr":
            self.current_row = []
        elif self.in_target_table and tag == "td":
            self.in_cell = True
            self.current_cell = []

    def handle_data(self, data: str) -> None:
        if self.in_target_table and self.in_cell:
            self.current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self.in_target_table:
            return
        if tag == "td" and self.in_cell:
            value = re.sub(r"\s+", " ", " ".join(self.current_cell)).strip()
            self.current_row.append(value)
            self.in_cell = False
        elif tag == "tr" and self.current_row:
            self.rows.append(tuple(self.current_row))
            self.current_row = []
        elif tag == "table":
            self.table_depth -= 1
            if self.table_depth <= 0:
                self.in_target_table = False


class ProcollegeAdapter:
    source_code = "PROCOLLEGE_PUBLIC_RESULTS"
    policy = CollectionPolicy(
        timeout_seconds=15,
        max_retries=2,
        retry_delay_seconds=2,
        rate_limit_seconds=1,
        max_response_bytes=5_000_000,
        max_pages=400,
        max_rows=50_000,
    )

    def __init__(
        self,
        *,
        page_count: int,
        key_resolver: Callable[[dict[str, object]], AdmissionResultKey] | None = None,
    ) -> None:
        if not 1 <= page_count <= self.policy.max_pages:
            raise ValueError("포털 수집 페이지 수는 1 이상 400 이하입니다.")
        self.page_count = page_count
        self.key_resolver = key_resolver

    def build_requests(self, academic_year: int) -> tuple[SourceRequest, ...]:
        if not 2000 <= academic_year <= 2100:
            raise ValueError("포털 결과 학년도를 확인하세요.")
        common = (
            ("schOrderField", "korname"),
            ("schOrderBy", "asc"),
            ("pageUnit", "100"),
            ("openyn", "2"),
            ("codeyear", str(academic_year)),
            ("sel_1", str(academic_year)),
            ("dc_univregion", "01"),
            ("dc_univregion", "04"),
            ("dc_univregion", "08"),
            ("univregion", "'01','04','08'"),
        )
        return tuple(
            SourceRequest(
                source_code=self.source_code,
                endpoint=PROCOLLEGE_ENDPOINT,
                academic_year=academic_year,
                page_number=page,
                parameters=common + (("pageIndex", str(page)),),
            )
            for page in range(1, self.page_count + 1)
        )

    def extract_rows(
        self, request: SourceRequest, response: SourceResponse
    ) -> tuple[dict[str, object], ...]:
        if request.endpoint != PROCOLLEGE_ENDPOINT or "html" not in response.content_type.lower():
            raise ValueError("전문대학포털 HTML 응답이 아닙니다.")
        parser = _DefTableParser()
        parser.feed(response.body.decode("utf-8", errors="replace"))
        return tuple(
            {
                "모집학년도": request.academic_year,
                **dict(zip(PROCOLLEGE_COLUMNS, row, strict=False)),
            }
            for row in parser.rows
            if len(row) >= len(PROCOLLEGE_COLUMNS)
        )

    def normalize(self, raw: dict[str, object]) -> AdmissionResultCandidate:
        if self.key_resolver is None:
            raise ValueError("canonical 기준정보 resolver가 필요합니다.")
        return AdmissionResultCandidate(
            key=self.key_resolver(raw),
            competition_rate=_decimal(raw.get("경쟁률")),
            average_score=_decimal(raw.get("평균_학생부")),
            lowest_score=_decimal(raw.get("최저_학생부")),
            score_basis=str(raw.get("점수산출_학생부") or "").strip() or None,
        )


class RequestsFormTransport:
    def fetch(self, request: SourceRequest, *, timeout_seconds: int) -> SourceResponse:
        if request.endpoint != PROCOLLEGE_ENDPOINT:
            raise SourceTransportError("허용되지 않은 포털 endpoint입니다.")
        try:
            response = requests.post(
                request.endpoint,
                data=list(request.parameters),
                timeout=timeout_seconds,
                allow_redirects=False,
                headers={"User-Agent": "junior-college-admission/1.0 source-review"},
            )
        except requests.RequestException as error:
            raise SourceTransportError("전문대학포털 요청에 실패했습니다.") from error
        return SourceResponse(
            status_code=response.status_code,
            content_type=response.headers.get("Content-Type", ""),
            body=response.content,
        )


def _decimal(value: object) -> Decimal | None:
    text = str(value or "").strip().replace(",", "")
    if not text or text in {"-", "없음"}:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if match is None:
        return None
    try:
        return Decimal(match.group())
    except InvalidOperation:
        return None


__all__ = [
    "PROCOLLEGE_COLUMNS",
    "PROCOLLEGE_ENDPOINT",
    "ProcollegeAdapter",
    "RequestsFormTransport",
]
