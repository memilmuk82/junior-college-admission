from __future__ import annotations

from dataclasses import dataclass

from app.services.ai_providers import PROVIDER_CODES, NarrativeDraft, NarrativeProviderError


@dataclass(slots=True)
class DemoNarrativeProvider:
    """Deterministic, network-free provider for the isolated public sandbox."""

    provider_code: str

    def __post_init__(self) -> None:
        if self.provider_code not in PROVIDER_CODES:
            raise NarrativeProviderError("지원하지 않는 외부 AI 공급자입니다.")

    def generate(self, payload: dict[str, object], api_key: str) -> NarrativeDraft:
        if not payload or not api_key:
            raise NarrativeProviderError("체험 상담 문장을 만들 입력과 키가 필요합니다.")
        return NarrativeDraft(
            text=(
                "검증된 지원자격과 성적 산출 결과를 근거 범위 안에서 요약했습니다. "
                "화면에 표시된 공식 근거와 준비 중 항목을 함께 확인하세요."
            ),
            check_items=(
                "게시된 모집요강과 입시결과의 학년도·전형·점수 척도를 다시 확인하세요.",
                "체험 환경의 문장을 교사가 검토한 뒤 사용할 문장만 확정하세요.",
            ),
        )


__all__ = ["DemoNarrativeProvider"]
