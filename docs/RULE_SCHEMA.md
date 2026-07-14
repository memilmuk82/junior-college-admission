# 규칙 스키마

Phase 1은 실제 대학 규칙이나 계산식을 추가하지 않고 문서·규칙 버전 저장 계약만 정의했다. Phase 3는 지원자격 제한형 조건 DSL을 테스트 우선으로 구현한다.

규칙 상태는 `DRAFT → EXTRACTED → VERIFIED → TESTED → HUMAN_APPROVED → PUBLISHED → SUPERSEDED`를 사용한다.

`PUBLISHED` 규칙은 출처 인용, 독립 검증, 골든 테스트 참조, 사람 승인 시각이 모두 있어야 하며 PostgreSQL 제약조건과 `scripts/validate_rules.py`가 이를 차단한다. Codex는 사람 승인을 설정하지 않는다.

관리자 직접 작성 규칙도 중간 상태를 건너뛰지 않는다. `EXTRACTED`에서는 전형·citation 연결과 유형별 제한형 payload를 고정하고, `VERIFIED`에서는 현재 payload digest와 규칙 계약 digest에 별도 검수자의 승인된 `RuleReview`를 결속한다. 규칙 계약 digest는 규칙 ID·버전·전형 연결·ScoreRule 업무키와 citation·문서·승인 페이지·원본 파일 hash를 포함한다. `TESTED`에서는 VERIFIED에 사용한 바로 그 검수 기록이 유효한지 다시 확인한 뒤 합성 골든 테스트 참조를 기록한다. 승인·게시·실행은 `EXTRACTED → VERIFIED → TESTED → HUMAN_APPROVED → PUBLISHED` 감사 이벤트의 누락과 역순도 차단한다. 검수 취소, payload·업무키 변경, 근거 문서·페이지 상태 또는 연결 변경이 있으면 사람 승인·게시·실행을 모두 실패 처리한다.

기존 검수 행의 digest는 자동 보정하지 않는다. `payload_digest`, `contract_digest` 또는 `contract_schema_version`이 비어 있는 기존 행은 fail-closed로 취급하며, 실제 규칙이 있다면 새 근거 스냅샷으로 사람이 다시 검수해야 한다. 현재 계약 스키마 버전은 2이며 review·artifact·감사 이벤트에 별도 저장한다. 후속 버전은 기존 digest를 현재 알고리즘으로 덮어쓰지 않고 버전별 검증기와 새 검수·artifact로 전환한다.

공개 근거는 문서만 연결해서는 충분하지 않다. citation은 같은 문서의 `HUMAN_APPROVED` 페이지, 모집학년도, 쪽 번호, 표·문단 위치를 가져야 하며 대학·캠퍼스·모집시기·전형 연결과 일치해야 한다. `REFERENCE_ONLY`, `AI_EXTRACTED_DRAFT`, `MANUAL_REVIEW` 문서는 게시할 수 없다. `VERIFIED_REFERENCE` 또는 내부 산출 규칙은 사람이 검수한 참고 문서에만 연결하며 대학 공식 규칙으로 표시하지 않는다.

## Canonical 대학·캠퍼스 코드

`Institution.code`는 대학 전체에서 고유하고 `Campus.code`는 같은 대학 안에서 고유하다. 기존 행의 코드를 대학명이나 파일명으로 추정해 채우지 않기 위해 두 필드는 단계 전환 동안 nullable로 유지한다. 다만 `ScoreRule`은 `VERIFIED` 전환부터 업무키의 `university_code`·`campus_code`가 연결된 대학·캠퍼스의 canonical code와 정확히 일치해야 한다. code가 비어 있거나 다르면 검수·골든 테스트·승인·게시·실행을 모두 차단한다.

canonical code는 규칙 계약 digest v2에 포함된다. 검수 이후 code를 변경하면 기존 독립 검수와 골든 테스트는 자동 승격하거나 재사용하지 않고 새 계약 스냅샷으로 다시 검수해야 한다. 공식 registry가 없는 기존 행은 `NULL`로 보존하며 이름 기반 backfill을 금지한다.

## 골든 테스트 실행 증거

`golden_test_ref`는 자유 입력 경로나 사람이 적는 완료 표시가 아니다. 서버가 실행마다 `golden-run/<RULE_TYPE>/<UUID>` 형식으로 생성한 `RuleGoldenTestArtifact.artifact_ref`만 저장한다. 모든 규칙 테이블은 참조와 함께 `golden_test_rule_type`을 저장하고, `(golden_test_ref, rule.id, golden_test_rule_type)`을 artifact의 `(artifact_ref, rule_id, rule_type)`에 결속하는 `RESTRICT` 3열 외래 키로 참조한다. 각 규칙 테이블의 CHECK는 참조와 유형이 함께 NULL이거나 해당 테이블의 고정 유형과 정확히 일치하는 경우만 허용한다. 따라서 서로 다른 규칙 테이블에서 같은 UUID를 의도적으로 재사용해도 유형이 다른 artifact를 연결할 수 없다. artifact는 다음 항목을 고정한다.

- 규칙 유형·ID와 VERIFIED에 사용한 독립 검수 ID
- 현재 payload digest와 canonical code·전형·근거를 포함한 계약 digest 및 계약 스키마 버전
- 실행한 합성 suite의 고정 참조와 SHA-256 digest
- 전체·성공·실패 case 수, `PASSED` 또는 `FAILED` 결과
- runner 참조와 timezone 포함 실행 시각
- 위 필드를 canonical JSON으로 해시한 artifact digest

case가 0개이거나 집계 합이 맞지 않으면 저장할 수 없다. `PASSED`는 모든 case가 성공하고 실패가 0개일 때만 생성된다. 관리자 TESTED 화면은 현재 규칙·검수·payload·계약과 일치하고 미래 시각이 아닌 `PASSED` artifact만 선택지로 보여준다. TESTED 감사 이벤트에는 artifact ID·digest·suite·case 수를 함께 고정하며 사람 승인·게시·실행 때 DB artifact와 다시 대조한다. artifact 상태·집계·suite·digest, 규칙 payload, 근거 또는 canonical code가 바뀌면 fail-closed 처리한다.

기존 임의 문자열 `golden_test_ref`는 artifact로 자동 변환하거나 성공 증거로 간주하지 않는다. 실제 규칙 전환 전에는 기존 non-null 참조 건수와 canonical code 누락 건수를 먼저 집계하고, 새 독립 검수와 합성 테스트 실행 증거를 생성해야 한다. AI는 artifact를 근거로 `HUMAN_APPROVED`를 설정하거나 규칙을 자동 게시하지 않는다.

현재 artifact 기록 함수는 관리자 HTTP에 노출하지 않고 검증된 offline runner가 호출할 서비스 계약만 제공한다. 실제 대학 규칙용 artifact를 만들기 전에는 runner 최소권한, 허용 suite digest registry 또는 서명된 CI attestation을 별도 운영 게이트에서 확정해야 한다. 이 생산자 신뢰가 없는 자기신고 PASSED 행은 실제 게시 승인 근거로 사용하지 않는다. 규칙 삭제 뒤 review·artifact·audit를 남기는 것은 감사 보존을 위한 fail-closed 기본값이며, 보유기간 정책 없이 자동 cascade 삭제하지 않는다.

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

## 성적 출처 범위 payload v1

`grade_source_scope_rules`는 전형별 활성 `PUBLISHED` 버전을 하나만 허용한다. 자격 상태가 계산 허용 상태인 경우에만 다음 payload를 조회한다.

```json
{"schema_version": 1, "policy": "VOCATIONAL_INCLUDED"}
```

policy는 `HOME_ONLY`, `VOCATIONAL_INCLUDED`, `VOCATIONAL_ONLY`, `EXCLUDE_VOCATIONAL_SEMESTER`, `TRACK_DEPENDENT`, `MANUAL_REVIEW` 중 하나다. 앞의 네 정책은 저장된 출처와 위탁학기 표지를 그대로 사용하며, 뒤의 두 정책은 임의 범위를 만들지 않고 `NEEDS_REVIEW`를 반환한다.

`MANUAL_INPUT`과 `GED_RECORD`는 이 여섯 정책에서 자동 포함하지 않는다. 별도 공식 규칙 없이 다른 출처로 변환하지 않으며, 선택 결과가 없으면 `INSUFFICIENT_DATA`다. 미검증 과목과 학기 역시 계산 후보에서 제외한다.

## Canonical 성적 규칙

관리자 메뉴의 직접 편집과 표준 CSV는 모두 `ManagedScoreRule`을 만들고 `score_rule_to_payload()`로 같은 제한형 payload를 생성한다. payload는 출처 포함, 값 우선 방향, 전역·학년별 학기 선택, 과목 선택, 학년·학기 가중치, 성취도, Z점수 출처·공식·table code·경계, 학기·학년 평균과 최종 표시의 단계별 반올림, 제한형 선형 점수 환산과 만점을 고정 객체로만 표현한다. 임의 필드와 자유 수식을 허용하지 않는다.

가중치 모드는 `EQUAL`, `GRADE_ONLY`, `GLOBAL_SEMESTER`, `GRADE_WITHIN_SEMESTER`로 구분한다. 마지막 모드는 학년 가중치와 학년 내부 학기 가중치를 곱하므로 두 수준을 전역 학기 가중치와 혼동하지 않는다. `PER_GRADE + BEST_N`은 각 학년의 우수 학기를 먼저 선택한 뒤 학년 가중치를 적용한다.

대학이 학기별 최소 이수단위를 요구하면 `minimum_semester_credits`로 명시한다. 하한 미달 학기는 우수학기 순위 전에 제외하고, 이수단위 누락은 0으로 보정하지 않고 검토 대상으로 돌린다.

Z점수 변환표는 하한·상한과 각 경계의 포함 여부를 별도 값으로 저장한다. `STANDARD_Z_V1` 계산의 원값·반올림값·절단값, 표 코드·버전, 근거 상태를 trace에 남긴다. 참고표는 `UNIVERSITY_OFFICIAL`로 승격할 수 없으며 공식 PDF 근거가 없는 경우 자동 게시하지 않는다.

성취도는 `EXCLUDE`, `GRADE_TABLE`, `DISTRIBUTION`, `MANUAL_REVIEW`로 분기한다. 자동 변환은 표 코드·버전·출처와 공식 버전을 요구하며 분포값은 `RATIO` 또는 `PERCENT` 척도와 합계를 검증한다. `CUMULATIVE_DISTRIBUTION_GRADE_V1`은 A·B·C 누적분포 등급 공식을 제한형으로 표현하며, `P`, 빈 분포, 잘못된 합계를 0으로 바꾸지 않는다.

출결 반영은 표 코드·버전·출처와 미인정 지각·조퇴·결과의 결석 환산 단위를 고정한다. 검증된 네 종류 횟수가 모두 있을 때만 별도 출결 점수를 만들고 교과 점수와 구분된 trace를 남긴다. 면접·실기는 계속 비예측 안내 값이며 출결과 같은 방식으로 합산하지 않는다.

규칙의 `evidence_level`은 `UNIVERSITY_OFFICIAL`, `COMMON_OFFICIAL`, `VERIFIED_REFERENCE`, `INTERNAL_CALCULATION`, `MANUAL_REVIEW`를 사용하고 생명주기와 분리한다. `source_status`는 최종 모집요강·시행계획·공통자료·참고자료라는 문서 상태를 나타내므로 두 필드를 서로 대체하지 않는다.

면접·실기 비율은 `non_predictive_components` 아래에 보존하여 안내 배점과 예상점수 계산 입력을 분리한다. 상세 CSV 열·허용 코드는 `docs/SCORE_RULE_CSV.md`를 따른다.
