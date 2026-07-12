# Phase 4 작업 카드

## 목표

지원자격이 확인된 전형에 한해 게시된 규칙으로 성적 출처·학기·과목을 선택하고, 제한형 계산 DSL과 `Decimal` 산술로 재현 가능한 계산 trace를 만든다.

## 선행조건과 근거

- `PROJECT_STATUS.md`의 Phase 3 `PASS`
- 실행 개발 문서 v2의 `4.1`, `4.3`~`4.5`, `FR-05`
- 마스터 프롬프트 v3의 `3.2`, `3.3`, `3.5`, `Phase 4 성적 계산 엔진`
- 공식 근거가 없는 실제 대학 산식은 만들거나 게시하지 않음
- 테스트에는 합성 규칙·합성 익명 성적만 사용

## 허용 수정 경로

- 계산 엔진·저장소: `app/services/`
- 규칙 저장 계약: `app/models.py`, `migrations/`
- 규칙 검증: `scripts/validate_rules.py`
- 검증: `tests/`, `Makefile`
- 기록: `README.md`, `PROJECT_STATUS.md`, `DEVELOPMENT_LOG.md`, `docs/RULE_SCHEMA.md`, `docs/SCORE_RULE_CSV.md`, `docs/DOMAIN_GLOSSARY.md`, `docs/TEST_STRATEGY.md`, `tasks/PHASE_4.md`

## 금지 사항

- 두 기준 문서와 Phase 0~3 작업 카드 수정
- 자격 미확정 상태에서 성적 조회·선택·계산
- 대학명 조건 분기, `eval()` 가능한 문자열, 부동소수점 최종 산술
- 누락·`P`·표준편차 0을 0점으로 변환
- 원적교와 위탁기관 성적의 원본 단계 병합
- 근거·검증·골든·사람 승인이 없는 규칙 실행

## Given/When/Then 수용 기준

- Given 자격 허용 상태, When 전형별 출처 규칙을 적용하면, Then 허용된 출처만 계산 후보가 된다.
- Given 자격 미확정 상태, When 계산 진입을 요청하면, Then 성적 조회 전에 차단한다.
- Given 위탁 포함·제외 규칙, When 같은 합성 성적을 선택하면, Then 전형마다 선택 범위가 다르다.
- Given 검증되지 않은 행과 `P`, When 선택하면, Then 미검증 행은 제외하고 `P`는 숫자 0으로 바꾸지 않는다.
- Given 수동 검토 정책이나 빈 범위, When 선택하면, Then 각각 `NEEDS_REVIEW`·`INSUFFICIENT_DATA`를 반환한다.
- Given 게시 계산 규칙, When 반복 계산하면, Then 동일한 `Decimal` 결과와 trace를 반환한다.

## 먼저 작성할 실패 테스트

- 자격 상태 선행 게이트
- 여섯 성적 출처 범위 정책
- 미검증 행 제외와 `P` 보존
- 전형별 게시 범위 규칙 조회와 단일 버전 제약
- 학기·과목 선택, 변환표, 가중치, 반올림·절사
- 결정성·단조성·순서 독립성·점수 범위

## 실행 명령

```bash
make test-unit
make test-integration
make lint
make validate-rules
make check-sensitive-data
make check
```

## 독립 검증자와 남은 위험

- 독립 검증 역할: 자격 판정이 먼저인지, 출처·학기·과목 trace가 입력과 일치하는지, 누락값이 0이 되지 않는지 반례로 대조한다.
- 남은 위험: 공식 승인 대학 산식 seed가 없으므로 Phase 4는 합성 규칙으로 엔진 계약만 검증한다. 실제 대학 환산점수는 Phase 5 전까지 공개하지 않는다.
