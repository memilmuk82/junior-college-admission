# Phase 3 작업 카드

## 목표

학생을 하나의 전형 유형으로 미리 분류하지 않고 사실 정보와 전형별 제한형 규칙으로 지원자격을 독립 판정한다. 누락 정보와 검토 필요를 결격으로 바꾸지 않으며 모든 결과에 재현 가능한 설명 trace를 제공한다.

## 선행조건과 근거

- `PROJECT_STATUS.md`의 Phase 2 `PASS`
- 실행 개발 문서 v2의 `4.1`, `4.2`, `FR-04`, `FR-06`
- 마스터 프롬프트 v3의 `3.1`, `3.2`, `3.4`, `Phase 3 지원자격 엔진`
- 공식 근거가 없는 실제 대학 규칙은 만들거나 게시하지 않음
- 테스트에는 합성 전형·합성 학생 사실만 사용

## 허용 수정 경로

- 판정 엔진: `app/services/`
- 규칙 저장 계약: `app/models.py`, `migrations/`
- 규칙 검증: `scripts/validate_rules.py`
- 검증: `tests/`, `Makefile`
- 기록: `README.md`, `PROJECT_STATUS.md`, `DEVELOPMENT_LOG.md`, `docs/RULE_SCHEMA.md`, `docs/DOMAIN_GLOSSARY.md`, `docs/TEST_STRATEGY.md`, `tasks/PHASE_3.md`

## 금지 사항

- 두 기준 문서와 Phase 0~2 작업 카드 수정
- 대학명 조건 분기, `eval()` 가능한 문자열, 임의 Python 호출
- 학생에게 일반고·특성화고 전형 중 하나만 배정
- 누락 사실을 `False`, 0, `INELIGIBLE`로 변환
- 비게시·근거 미승인 규칙으로 운영 판정
- 민감 결격 사실의 불필요한 영구 저장
- 자격 판정 전 성적 계산

## Given/When/Then 수용 기준

- Given 같은 합성 일반고 직업위탁생, When 서로 다른 합성 전형 규칙을 평가하면, Then 전형별로 독립된 결과를 낸다.
- Given 일반고·특성화고 전형 규칙을 모두 만족하는 사실, When 각각 평가하면, Then 두 결과를 동시에 허용한다.
- Given 마이스터고·종합고·검정고시·학과 예외 조건, When 제한형 DSL로 평가하면, Then 대학명 하드코딩 없이 표현한다.
- Given 필요한 사실이 누락됨, When 판정하면, Then `INSUFFICIENT_DATA`와 누락 필드를 반환한다.
- Given 명시적 검토 규칙, When 판정하면, Then `NEEDS_REVIEW`를 확정 자격처럼 노출하지 않는다.
- Given 같은 사실과 규칙, When 반복 판정하면, Then 동일한 설명 trace를 반환한다.
- Given 계산 비허용 상태, When 계산 진입을 요청하면, Then 계산 전에 차단한다.

## 먼저 작성할 실패 테스트

- 전형별 상이한 결과와 복수 전형 동시 가능
- 5개 상태와 누락 사실의 3값 논리
- 학교 유형·검정고시·학과 예외 조건
- 허용 필드·연산자·payload 구조 제한
- 비게시·근거 미승인 규칙 거부
- 설명 trace 재현성과 계산 진입 차단

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

- 독립 검증 역할: 규칙 후보와 반례를 분리해 누락 사실이 결격으로 바뀌지 않는지, 전형 간 결과가 공유되지 않는지, 계산 코드가 먼저 실행되지 않는지 대조한다.
- 남은 위험: 공식 모집요강과 사람 검수 규칙 seed가 없으므로 이번 단계는 실행 계약과 합성 규칙만 검증한다. 실제 대학 결과는 Phase 5 파일럿 전까지 공개하지 않는다.
