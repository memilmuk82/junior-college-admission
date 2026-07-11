# 규칙 스키마

Phase 1은 실제 대학 규칙이나 계산식을 추가하지 않고 문서·규칙 버전 저장 계약만 정의한다. 제한형 규칙 DSL은 Phase 3·4에서 테스트 우선으로 구현한다.

규칙 상태는 `DRAFT → EXTRACTED → VERIFIED → TESTED → HUMAN_APPROVED → PUBLISHED → SUPERSEDED`를 사용한다.

`PUBLISHED` 규칙은 출처 인용, 독립 검증, 골든 테스트 참조, 사람 승인 시각이 모두 있어야 하며 PostgreSQL 제약조건과 `scripts/validate_rules.py`가 이를 차단한다. Codex는 사람 승인을 설정하지 않는다.
