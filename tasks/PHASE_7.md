# Phase 7 작업 카드

## 목표

관리자가 대학·캠퍼스·모집학년도·모집시기·전형별 규칙을 직접 검수·버전 생성·승인·게시할 수 있도록 DB와 SSR 관리자 기능을 구현한다. 표준 CSV는 같은 canonical 규칙 스키마를 사용해 신규 규칙과 새 DRAFT 버전을 일괄 준비하되 자동 게시하지 않는다.

## 선행조건

- `PROJECT_STATUS.md`의 Phase 6 `PASS`
- 규칙 실행은 게시·근거·독립 검증·골든·사람 승인 게이트를 유지함
- AI가 `HUMAN_APPROVED`를 직접 설정하거나 규칙을 자동 게시하지 않음

## 허용 수정 경로

- 관리자·검수 서비스: `app/services/`
- 관리자 SSR route·template·CSS·필요 최소 JavaScript: `app/`
- DB 계약: `app/models.py`, `migrations/`
- 합성 검증: `tests/`, `Makefile`
- 기록: `README.md`, `PROJECT_STATUS.md`, `DEVELOPMENT_LOG.md`, `docs/`, `tasks/PHASE_7.md`

## 금지 사항

- 기준 원본 문서와 Phase 0~6 카드 수정
- 참고 PDF·XLSX·CSV·노트북 또는 파생물 Git 추가
- 기존 `PUBLISHED` 규칙 직접 덮어쓰기
- 오류 CSV의 정상 행 임의 게시
- 사람 승인 없는 게시
- 근거가 불명확한 후보를 `UNIVERSITY_OFFICIAL` 또는 공식 규칙으로 표시
- 자유 수식·실행 코드·임의 JSON 계산식 허용
- 관리자 핵심 기능을 JavaScript 전용으로 구현

## 수용 기준

- 게시 규칙 수정은 새 `DRAFT` 버전 복제로 시작하며 이전 버전을 보존한다.
- 규칙의 이전·새 payload 비교와 계산 영향도 표본 결과를 제공한다.
- 검수·승인·게시·반려·대체 작업을 감사 로그로 남긴다.
- 관리자 직접 편집과 CSV가 동일한 canonical 규칙과 생명주기를 사용한다.
- CSV는 고정 헤더, UTF-8/BOM, 허용 코드, Decimal, TRUE/FALSE, 중복 키, 빈 값/0, formula injection을 검증한다.
- CSV 업로드는 신규·변경·충돌·오류를 분류하고 변경 전후 미리보기를 제공한다.
- 오류가 있으면 자동 게시하지 않으며 관리자가 확인한 유효 행만 DRAFT로 생성한다.
- 문서·근거 위치와 source status가 검수 화면에 표시된다.
- `HUMAN_APPROVED`와 `PUBLISHED`는 명시적 사람 동작으로만 전환된다.
- 규칙과 입시결과 원본·staging·published 자료는 관리자 권한 경계 밖에 노출하지 않는다.
- 합성 데이터로 버전 보존, 비교, 영향도, 감사 로그, CSV 미리보기와 승인 게이트를 검증한다.

## 검증 명령

```bash
make test-unit
make test-integration
make test-e2e
make lint
make validate-rules
make check-sensitive-data
make check
```
