# Phase 2 작업 카드

## 목표

학생 자료 입력 게이트웨이를 구조화 입력부터 구축한다. CSV·XLSX·표 붙여넣기를 표준 필드로 변환하고, 누락·신뢰도·오류를 교사 검수 전에 명시하며, 확인된 행 외에는 영구 저장하지 않는 계약을 만든 뒤 PDF·이미지 OCR로 확장한다.

## 선행조건과 근거

- `PROJECT_STATUS.md`의 Phase 1 `PASS`
- 실행 개발 문서 v2의 `FR-02 학생 자료 입력 게이트웨이`, `FR-03 위탁기관 학급 성적표 처리`
- 마스터 프롬프트 v3의 `Phase 2 입력 게이트웨이`
- 입력 순서는 `XLSX·CSV·표 붙여넣기 → 텍스트 PDF → 이미지·클립보드 → 이미지형·손상 PDF → 교사 검수 화면`
- 실제 학생 자료가 아닌 합성 익명 입력만 테스트에 사용

## 허용 수정 경로

- 의존성과 하네스: `pyproject.toml`, `uv.lock`, `Makefile`
- 입력 서비스: `app/services/`
- 저장 계약: `app/models.py`, `migrations/`
- 검수 SSR: `app/routes.py`, `app/templates/`, `app/static/css/`, `app/static/js/`
- 검증: `tests/`, `scripts/check_sensitive_data.py`
- 기록: `README.md`, `PROJECT_STATUS.md`, `DEVELOPMENT_LOG.md`, `docs/INPUT_GATEWAY.md`, `docs/PRIVACY_DATA_RETENTION.md`, `docs/TEST_STRATEGY.md`, `tasks/PHASE_2.md`

## 금지 사항

- 두 기준 문서와 Phase 0·1 작업 카드 수정
- 실제 학생 파일·학생 식별정보·다른 학생 성적 행을 DB·로그·캐시·테스트에 저장
- 누락된 값, `P`, 선택 열 부재를 0점이나 불가로 변환
- `세부능력 및 특기사항` 원문을 점수 입력 또는 외부 AI payload에 포함
- OCR 결과를 교사 확인 없이 확정 저장
- 지원자격 판정 또는 성적 계산 실행

## Given/When/Then 수용 기준

- Given 합성 CSV·XLSX·표 텍스트, When 입력하면, Then 파일 해시·형식과 표준 필드 후보를 만들고 원문 누락을 보존한다.
- Given `P`, 빈칸, 선택 열 부재, 잘못된 숫자, When 정규화하면, Then 0으로 바꾸지 않고 값과 검수 이슈를 분리해 표시한다.
- Given 같은 원본 바이트, When 재입력하면, Then 동일 SHA-256으로 중복 후보를 식별한다.
- Given 학급 전체 위탁 성적표, When 대상 학생을 선택하면, Then 대상 행과 과목 통계만 결과에 남고 다른 학생 행은 저장·로그되지 않는다.
- Given 교사가 일부 행만 확인, When 확정하면, Then 확인된 행만 PostgreSQL에 저장하고 원본·파생물 삭제를 검증한다.

## 먼저 작성할 실패 테스트

- CSV·표 붙여넣기 표준 필드 변환과 누락 보존
- `P` 및 잘못된 숫자의 비파괴 처리
- 동일 바이트 중복 해시
- XLSX 복수 시트·머리글 탐지
- 대상 학생 외 행 제거
- 확인 행만 저장 및 원본 삭제 검증

## 실행 명령

```bash
make test-unit
make test-integration
make lint
make check-sensitive-data
make check
```

## 독립 검증자와 남은 위험

- 독립 검증 역할: 정규화 결과에 원문 누락이 그대로 남는지, 다른 학생 행이 반환·로그·DB에 없는지, 확정 저장 전에 계산 코드가 호출되지 않는지 대조한다.
- 남은 위험: 실제 학교별 XLS/XLSX 배치는 공식 샘플을 안전하게 분석하기 전까지 일반화하지 않으며, OCR 정확도는 구조화 입력 계약 이후 별도 게이트에서 검증한다.

## 완료 판정

- 상태: `PASS` (2026-07-11)
- 구조화 입력부터 이미지형 PDF까지 모든 입력은 교사 검수 전 미리보기로만 처리한다.
- 교사 선택 행만 PostgreSQL에 저장하고 임시 원본·파생물·검수 상태 삭제를 검증한다.
- SSR 검수 화면의 수정·선택·확정·폐기, JavaScript 비활성 경로와 반응형 화면을 자동 검증했다.
- Phase 3 전까지 지원자격 판정과 성적 계산은 호출하지 않는다.
