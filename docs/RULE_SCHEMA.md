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

## 활성 게시 규칙

`admission_eligibility_rules`, `multiple_application_rules`, `disqualification_rules`는 전형별로 `PUBLISHED` 상태를 하나만 허용하는 PostgreSQL partial unique index를 사용한다. DRAFT와 이전 `SUPERSEDED` 버전은 삭제하지 않는다. 실행 서비스는 게시 규칙 0건을 `PublishedRuleNotFound`, 방어적으로 감지한 복수 게시를 `PublishedRuleConflict`로 반환한다.

## 복수지원 payload v1

복수지원은 지원자격 상태를 변경하지 않는 별도 결과다. 대학별 전체 지원 횟수, 같은 캠퍼스 지원 횟수와 전형 ID 금지 조합만 데이터로 평가한다.

```json
{
  "schema_version": 1,
  "limits": {"total": 2, "per_campus": 1},
  "forbidden_track_combinations": [["track_a", "track_b"]],
  "reason_codes": {
    "allowed": "APPLICATION_ALLOWED",
    "history_incomplete": "APPLICATION_HISTORY_INCOMPLETE",
    "max_applications": "MAX_APPLICATIONS_REACHED",
    "max_per_campus": "MAX_CAMPUS_APPLICATIONS_REACHED",
    "forbidden_combination": "FORBIDDEN_TRACK_COMBINATION"
  }
}
```

제한값은 양의 정수 또는 `null`이다. 지원 이력이 완전하지 않으면 허용·차단을 추정하지 않고 `NEEDS_REVIEW`를 반환한다. trace에는 규칙 ID·버전, 평가한 건수와 일치한 제약 종류만 남긴다.

## 결격 payload v1

결격 규칙은 지원자격 DSL v1 구조를 재사용하지만 세션 전용 `additional.<snake_case>` bool 사실과 `is_true`·`is_false`만 허용한다. case 상태는 `INELIGIBLE`·`NEEDS_REVIEW`, default는 `ELIGIBLE`·`NEEDS_REVIEW`만 허용한다. 결과는 각각 `DISQUALIFIED`, `NEEDS_REVIEW`, `CLEAR`로 별도 변환하며 누락 사실은 `INSUFFICIENT_DATA`다.

민감 사실의 실제 bool 값은 함수 호출 중에만 존재하고 규칙 payload, 설명 trace 또는 DB에 저장하지 않는다. 결격 규칙은 `score_adjustment_rules`를 호출하거나 점수 감점으로 변환하지 않는다.
