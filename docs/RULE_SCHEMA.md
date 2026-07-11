# 규칙 스키마

Phase 1은 실제 대학 규칙이나 계산식을 추가하지 않고 문서·규칙 버전 저장 계약만 정의했다. Phase 3는 지원자격 제한형 조건 DSL을 테스트 우선으로 구현한다.

규칙 상태는 `DRAFT → EXTRACTED → VERIFIED → TESTED → HUMAN_APPROVED → PUBLISHED → SUPERSEDED`를 사용한다.

`PUBLISHED` 규칙은 출처 인용, 독립 검증, 골든 테스트 참조, 사람 승인 시각이 모두 있어야 하며 PostgreSQL 제약조건과 `scripts/validate_rules.py`가 이를 차단한다. Codex는 사람 승인을 설정하지 않는다.

## 지원자격 규칙 payload v1

지원자격 규칙은 실행 가능한 문자열이나 대학별 Python 분기를 저장하지 않는다. payload는 다음 고정 구조만 허용한다.

```json
{
  "schema_version": 1,
  "cases": [
    {
      "case_id": "synthetic_case",
      "when": {"fact": "final_school_type", "op": "eq", "value": "GENERAL"},
      "status": "ELIGIBLE",
      "reason_code": "SYNTHETIC_REASON"
    }
  ],
  "default": {
    "status": "NEEDS_REVIEW",
    "reason_code": "NO_MATCHED_CASE"
  }
}
```

조건 조합은 `all`, `any`, `not`만 허용한다. 단일 조건 연산자는 `eq`, `ne`, `in`, `not_in`, `gte`, `lte`, `is_true`, `is_false`로 제한한다. 조건 깊이는 20, 노드는 500, case는 100개를 넘을 수 없다.

기본 사실 필드는 학교 유형, 졸업 상태, 직업위탁 상태·학기·시간·개월, 전학, 검정고시로 제한한다. 전형별 추가 조건은 `additional.<snake_case>`만 허용하며 학생 식별정보를 사실 필드로 사용할 수 없다.

필요한 사실이 없으면 조건은 거짓이 아닌 `UNKNOWN`이다. 어떤 case도 확정 일치하지 않고 `UNKNOWN`이 남으면 기본 상태 대신 `INSUFFICIENT_DATA`를 반환한다. 설명 trace는 규칙 ID·버전, 조건 경로·연산자·결과를 포함하지만 실제 학생 사실값은 복사하지 않는다.
