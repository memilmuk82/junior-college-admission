from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from time import sleep
from typing import Protocol


class AdmissionResultCollectionError(RuntimeError):
    pass


class SourceTransportError(AdmissionResultCollectionError):
    pass


class StagingBlockedError(ValueError):
    pass


type RawScalar = str | int | float | bool | Decimal | None


@dataclass(frozen=True)
class CollectionPolicy:
    timeout_seconds: int
    max_retries: int
    retry_delay_seconds: int
    rate_limit_seconds: int
    max_response_bytes: int = 5_000_000
    max_pages: int = 1_000
    max_rows: int = 100_000

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("수집 timeout은 양수여야 합니다.")
        if self.max_retries < 0:
            raise ValueError("재시도 횟수는 0 이상이어야 합니다.")
        if self.retry_delay_seconds < 0 or self.rate_limit_seconds < 0:
            raise ValueError("재시도·호출 간격은 0 이상이어야 합니다.")
        if self.max_response_bytes <= 0 or self.max_pages <= 0 or self.max_rows <= 0:
            raise ValueError("응답 크기·페이지·행 제한은 양수여야 합니다.")


@dataclass(frozen=True)
class SourceRequest:
    source_code: str
    endpoint: str
    academic_year: int
    page_number: int
    parameters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.source_code or not self.endpoint:
            raise ValueError("source code와 endpoint가 필요합니다.")
        if self.academic_year < 2000 or self.page_number <= 0:
            raise ValueError("모집학년도와 페이지 번호가 유효하지 않습니다.")

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            {
                "source_code": self.source_code,
                "endpoint": self.endpoint,
                "academic_year": self.academic_year,
                "page_number": self.page_number,
                "parameters": sorted(self.parameters),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class SourceResponse:
    status_code: int
    content_type: str
    body: bytes


class AdmissionResultTransport(Protocol):
    def fetch(self, request: SourceRequest, *, timeout_seconds: int) -> SourceResponse: ...


class AdmissionResultSourceAdapter(Protocol):
    source_code: str
    policy: CollectionPolicy

    def build_requests(self, academic_year: int) -> tuple[SourceRequest, ...]: ...

    def extract_rows(
        self, request: SourceRequest, response: SourceResponse
    ) -> tuple[dict[str, object], ...]: ...

    def normalize(self, raw: dict[str, object]) -> AdmissionResultCandidate: ...


@dataclass(frozen=True)
class RawAdmissionResultRow:
    source_row_number: int
    fields: tuple[tuple[str, RawScalar], ...]

    def as_dict(self) -> dict[str, object]:
        return dict(self.fields)


@dataclass(frozen=True)
class RawAdmissionResultPage:
    page_number: int
    request_fingerprint: str
    response_digest: str
    rows: tuple[RawAdmissionResultRow, ...]


@dataclass(frozen=True)
class RawAdmissionResultCollection:
    source_code: str
    expected_academic_year: int
    policy: CollectionPolicy
    pages: tuple[RawAdmissionResultPage, ...]
    collection_digest: str

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def row_count(self) -> int:
        return sum(len(page.rows) for page in self.pages)


@dataclass(frozen=True)
class AdmissionResultKey:
    academic_year: int
    university_code: str
    campus_code: str
    admission_round: str
    admission_track_code: str
    program_code: str


@dataclass(frozen=True)
class AdmissionResultCandidate:
    key: AdmissionResultKey
    applicant_count: int | None = None
    admitted_count: int | None = None
    competition_rate: Decimal | None = None
    highest_score: Decimal | None = None
    average_score: Decimal | None = None
    lowest_score: Decimal | None = None
    score_basis: str | None = None


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str


@dataclass(frozen=True)
class StagedAdmissionResultRow:
    source_row_number: int
    candidate: AdmissionResultCandidate | None
    issues: tuple[ValidationIssue, ...]

    @property
    def status(self) -> str:
        return "VALID" if not self.issues and self.candidate is not None else "ERROR"


@dataclass(frozen=True)
class QualityBaseline:
    previous_row_count: int
    previous_page_count: int
    minimum_ratio: Decimal

    def __post_init__(self) -> None:
        if self.previous_row_count <= 0 or self.previous_page_count <= 0:
            raise ValueError("품질 기준의 이전 행·페이지 수는 양수여야 합니다.")
        if not Decimal(0) < self.minimum_ratio <= Decimal(1):
            raise ValueError("품질 최소 비율은 0 초과 1 이하여야 합니다.")


@dataclass(frozen=True)
class AdmissionResultStagingBatch:
    raw_collection_digest: str
    source_code: str
    expected_academic_year: int
    page_count: int
    rows: tuple[StagedAdmissionResultRow, ...]
    issues: tuple[ValidationIssue, ...]
    status: str

    @property
    def valid_row_count(self) -> int:
        return sum(row.status == "VALID" for row in self.rows)


@dataclass(frozen=True)
class Approval:
    approved_by: str
    approved_at: datetime
    confirmed_row_count: int


@dataclass(frozen=True)
class HistoricalRuleReference:
    rule_id: str
    version: str
    academic_year: int


@dataclass(frozen=True)
class PublishedAdmissionResult:
    candidate: AdmissionResultCandidate
    rule_reference: HistoricalRuleReference | None


@dataclass(frozen=True)
class PublishedAdmissionResultBatch:
    staging_digest: str
    approved_by: str
    approved_at: datetime
    rows: tuple[PublishedAdmissionResult, ...]


def collect_admission_result_raw(
    adapter: AdmissionResultSourceAdapter,
    transport: AdmissionResultTransport,
    *,
    academic_year: int,
    wait: Callable[[int], None] | None = None,
) -> RawAdmissionResultCollection:
    requests = adapter.build_requests(academic_year)
    if not requests:
        raise AdmissionResultCollectionError("수집 요청이 비어 있습니다.")
    if len(requests) > adapter.policy.max_pages:
        raise AdmissionResultCollectionError("수집 요청 페이지 수가 안전 제한을 초과했습니다.")
    if any(
        request.source_code != adapter.source_code or request.academic_year != academic_year
        for request in requests
    ):
        raise AdmissionResultCollectionError("요청의 출처 또는 모집학년도가 일치하지 않습니다.")
    fingerprints = tuple(request.fingerprint for request in requests)
    if len(set(fingerprints)) != len(fingerprints):
        raise AdmissionResultCollectionError("중복 수집 요청을 허용하지 않습니다.")

    sleeper = wait or sleep
    pages: list[RawAdmissionResultPage] = []
    source_row_number = 0
    for request_index, request in enumerate(requests):
        if request_index and adapter.policy.rate_limit_seconds:
            sleeper(adapter.policy.rate_limit_seconds)
        response = _fetch_with_retry(adapter, transport, request, sleeper)
        if not 200 <= response.status_code < 300:
            raise AdmissionResultCollectionError(
                f"수집 응답 상태 코드가 성공 범위가 아닙니다: {response.status_code}"
            )
        if len(response.body) > adapter.policy.max_response_bytes:
            raise AdmissionResultCollectionError("수집 응답이 안전 크기 제한을 초과했습니다.")
        try:
            extracted = adapter.extract_rows(request, response)
        except Exception as error:
            raise AdmissionResultCollectionError(
                "수집 응답을 행으로 해석하지 못했습니다."
            ) from error
        frozen_rows: list[RawAdmissionResultRow] = []
        for raw in extracted:
            source_row_number += 1
            if source_row_number > adapter.policy.max_rows:
                raise AdmissionResultCollectionError("수집 행 수가 안전 제한을 초과했습니다.")
            frozen_rows.append(RawAdmissionResultRow(source_row_number, _freeze_raw_fields(raw)))
        pages.append(
            RawAdmissionResultPage(
                page_number=request.page_number,
                request_fingerprint=request.fingerprint,
                response_digest=hashlib.sha256(response.body).hexdigest(),
                rows=tuple(frozen_rows),
            )
        )

    digest_payload = "|".join(
        f"{page.page_number}:{page.request_fingerprint}:{page.response_digest}" for page in pages
    ).encode()
    return RawAdmissionResultCollection(
        source_code=adapter.source_code,
        expected_academic_year=academic_year,
        policy=adapter.policy,
        pages=tuple(pages),
        collection_digest=hashlib.sha256(digest_payload).hexdigest(),
    )


def stage_admission_result_raw(
    raw: RawAdmissionResultCollection,
    adapter: AdmissionResultSourceAdapter,
    *,
    baseline: QualityBaseline | None = None,
) -> AdmissionResultStagingBatch:
    if raw.source_code != adapter.source_code:
        raise ValueError("raw 출처와 adapter 출처가 다릅니다.")
    batch_issues = list(_quality_issues(raw, baseline))
    staged: list[StagedAdmissionResultRow] = []
    key_rows: dict[AdmissionResultKey, list[int]] = {}
    for page in raw.pages:
        for raw_row in page.rows:
            issues: list[ValidationIssue] = []
            candidate: AdmissionResultCandidate | None = None
            try:
                candidate = adapter.normalize(raw_row.as_dict())
            except Exception:
                issues.append(
                    ValidationIssue(
                        "NORMALIZATION_ERROR",
                        "행을 canonical 입시결과 계약으로 정규화하지 못했습니다.",
                    )
                )
            if candidate is not None:
                issues.extend(_candidate_issues(candidate, raw.expected_academic_year))
                key_rows.setdefault(candidate.key, []).append(raw_row.source_row_number)
            staged.append(
                StagedAdmissionResultRow(raw_row.source_row_number, candidate, tuple(issues))
            )

    duplicate_rows = {
        row_number
        for row_numbers in key_rows.values()
        if len(row_numbers) > 1
        for row_number in row_numbers
    }
    if duplicate_rows:
        duplicate_issue = ValidationIssue(
            "DUPLICATE_BUSINESS_KEY",
            "동일 대학·캠퍼스·학년도·모집시기·전형·학과 키가 중복되었습니다.",
        )
        staged = [
            StagedAdmissionResultRow(
                row.source_row_number,
                row.candidate,
                row.issues + (duplicate_issue,)
                if row.source_row_number in duplicate_rows
                else row.issues,
            )
            for row in staged
        ]
    blocked = bool(batch_issues) or any(row.issues for row in staged) or not staged
    if not staged:
        batch_issues.append(ValidationIssue("EMPTY_COLLECTION", "수집된 입시결과 행이 없습니다."))
    return AdmissionResultStagingBatch(
        raw_collection_digest=raw.collection_digest,
        source_code=raw.source_code,
        expected_academic_year=raw.expected_academic_year,
        page_count=raw.page_count,
        rows=tuple(staged),
        issues=tuple(batch_issues),
        status="BLOCKED" if blocked else "READY",
    )


def publish_staging_batch(
    staging: AdmissionResultStagingBatch,
    approval: Approval,
    rule_reference: HistoricalRuleReference | None = None,
) -> PublishedAdmissionResultBatch:
    if not isinstance(staging, AdmissionResultStagingBatch):
        raise TypeError("raw 수집 단위를 직접 게시할 수 없습니다.")
    if staging.status != "READY" or staging.issues or any(row.issues for row in staging.rows):
        raise StagingBlockedError("오류가 있는 staging batch는 부분 게시할 수 없습니다.")
    if not approval.approved_by.strip() or approval.approved_at.tzinfo is None:
        raise StagingBlockedError(
            "게시에는 식별 가능한 관리자와 timezone 포함 승인시각이 필요합니다."
        )
    if approval.confirmed_row_count != len(staging.rows):
        raise StagingBlockedError("관리자가 확인한 행 수가 staging 전체 행 수와 다릅니다.")
    if rule_reference is not None:
        if not rule_reference.rule_id or not rule_reference.version:
            raise StagingBlockedError("과거 규칙 참조에는 규칙 ID와 버전이 필요합니다.")
        if rule_reference.academic_year != staging.expected_academic_year:
            raise StagingBlockedError("과거 입시결과와 규칙 버전의 모집학년도가 다릅니다.")
    candidates = tuple(row.candidate for row in staging.rows)
    if any(candidate is None for candidate in candidates):
        raise StagingBlockedError("정규화되지 않은 행을 게시할 수 없습니다.")
    published = tuple(
        PublishedAdmissionResult(candidate, rule_reference)
        for candidate in candidates
        if candidate is not None
    )
    staging_digest = hashlib.sha256(
        f"{staging.raw_collection_digest}:{approval.approved_at.isoformat()}".encode()
    ).hexdigest()
    return PublishedAdmissionResultBatch(
        staging_digest=staging_digest,
        approved_by=approval.approved_by,
        approved_at=approval.approved_at,
        rows=published,
    )


def _fetch_with_retry(
    adapter: AdmissionResultSourceAdapter,
    transport: AdmissionResultTransport,
    request: SourceRequest,
    wait: Callable[[int], None],
) -> SourceResponse:
    attempts = adapter.policy.max_retries + 1
    last_error: SourceTransportError | None = None
    for attempt in range(attempts):
        try:
            return transport.fetch(request, timeout_seconds=adapter.policy.timeout_seconds)
        except SourceTransportError as error:
            last_error = error
            if attempt + 1 < attempts and adapter.policy.retry_delay_seconds:
                wait(adapter.policy.retry_delay_seconds)
    raise AdmissionResultCollectionError("재시도 한도 안에 수집하지 못했습니다.") from last_error


def _freeze_raw_fields(raw: Mapping[str, object]) -> tuple[tuple[str, RawScalar], ...]:
    frozen: list[tuple[str, RawScalar]] = []
    for key, value in sorted(raw.items()):
        if not isinstance(key, str) or not key:
            raise AdmissionResultCollectionError("raw 행 필드 이름은 빈 문자열이 아니어야 합니다.")
        if value is not None and not isinstance(value, (str, int, float, bool, Decimal)):
            raise AdmissionResultCollectionError(
                "raw 행은 중첩 객체나 실행 가능한 값을 허용하지 않습니다."
            )
        frozen.append((key, value))
    return tuple(frozen)


def _quality_issues(
    raw: RawAdmissionResultCollection, baseline: QualityBaseline | None
) -> tuple[ValidationIssue, ...]:
    if baseline is None:
        return ()
    issues: list[ValidationIssue] = []
    if Decimal(raw.row_count) < Decimal(baseline.previous_row_count) * baseline.minimum_ratio:
        issues.append(
            ValidationIssue("ROW_COUNT_DROP", "이전 수집 대비 행 수가 허용 비율 미만입니다.")
        )
    if Decimal(raw.page_count) < Decimal(baseline.previous_page_count) * baseline.minimum_ratio:
        issues.append(
            ValidationIssue("PAGE_COUNT_DROP", "이전 수집 대비 페이지 수가 허용 비율 미만입니다.")
        )
    return tuple(issues)


def _candidate_issues(
    candidate: AdmissionResultCandidate, expected_academic_year: int
) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    key = candidate.key
    if key.academic_year != expected_academic_year:
        issues.append(
            ValidationIssue(
                "MIXED_ACADEMIC_YEAR",
                "행의 모집학년도가 수집 단위의 모집학년도와 다릅니다.",
            )
        )
    required = (
        key.university_code,
        key.campus_code,
        key.admission_round,
        key.admission_track_code,
        key.program_code,
    )
    if any(not value.strip() for value in required):
        issues.append(ValidationIssue("REQUIRED_KEY_MISSING", "입시결과 업무키가 비어 있습니다."))
    counts = (candidate.applicant_count, candidate.admitted_count)
    if any(value is not None and (isinstance(value, bool) or value < 0) for value in counts):
        issues.append(ValidationIssue("INVALID_COUNT", "인원 값은 0 이상의 정수 또는 빈 값입니다."))
    decimals = (
        candidate.competition_rate,
        candidate.highest_score,
        candidate.average_score,
        candidate.lowest_score,
    )
    if any(value is not None and (not value.is_finite() or value < 0) for value in decimals):
        issues.append(
            ValidationIssue("INVALID_DECIMAL", "결과 지표는 0 이상의 유한값이어야 합니다.")
        )
    if all(value is None for value in (*counts, *decimals)):
        issues.append(
            ValidationIssue("RESULT_METRIC_MISSING", "입시결과 지표가 모두 비어 있습니다.")
        )
    return tuple(issues)


__all__ = [
    "AdmissionResultCandidate",
    "AdmissionResultCollectionError",
    "AdmissionResultKey",
    "AdmissionResultStagingBatch",
    "Approval",
    "CollectionPolicy",
    "HistoricalRuleReference",
    "PublishedAdmissionResultBatch",
    "QualityBaseline",
    "RawAdmissionResultCollection",
    "SourceRequest",
    "SourceResponse",
    "SourceTransportError",
    "StagingBlockedError",
    "collect_admission_result_raw",
    "publish_staging_batch",
    "stage_admission_result_raw",
]
