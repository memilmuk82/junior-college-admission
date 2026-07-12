# Phase 6 작업 카드

## 목표

입시결과 수집을 원본·staging·published 단계로 분리하고, 기존 노트북의 네트워크·파일쓰기 로직을 실행하지 않은 채 안전한 수집 어댑터 계약으로 대체한다.

## 선행조건

- `PROJECT_STATUS.md`의 Phase 5 `PASS`
- 제공 CSV는 성적 규칙이 아니라 과거 입시결과 자료임
- 제공 노트북은 정적 분석만 수행하고 임의 실행하지 않음

## 허용 수정 경로

- 수집·정규화 서비스: `app/services/`
- DB 계약: `app/models.py`, `migrations/`
- 수집 스크립트: `scripts/`
- 합성 검증: `tests/`, `Makefile`
- 기록: `README.md`, `PROJECT_STATUS.md`, `DEVELOPMENT_LOG.md`, `docs/`, `tasks/PHASE_6.md`

## 금지 사항

- 기준 원본 문서와 Phase 0~5 카드 수정
- 참고 CSV·노트북 및 원본·파생물 Git 추가
- 노트북 직접 실행, 무단 네트워크 호출·크롤링·파일쓰기
- 2026 입시결과를 2027 모집 산식으로 사용
- raw 행을 published 행으로 직접 승격
- 페이지·행 수 급감, 중복, 혼합연도 오류를 무시한 부분 게시

## 수용 기준

- source adapter는 요청·응답·정규화를 분리하고 timeout·재시도·rate limit을 명시한다.
- raw는 불변 수집 단위, staging은 정규화·검증 단위, published는 사람 승인 단위다.
- 대학·캠퍼스·모집학년도·모집시기·전형·학과 업무키를 고정한다.
- 행 수·페이지 수 급감, 중복, 빈 필수키, 연도 혼합을 명시적으로 차단한다.
- 과거 입시결과는 해당 당시 규칙 버전과 연결할 수 있지만 현재 규칙으로 자동 재해석하지 않는다.
- 테스트는 합성 응답만 사용하고 실제 사이트를 호출하지 않는다.

## 검증 명령

```bash
make test-unit
make test-integration
make lint
make validate-rules
make check-sensitive-data
make check
```

## 구현 현황

- [x] 요청·응답·정규화를 분리한 source adapter 계약
- [x] timeout·재시도·rate limit·응답 크기·페이지·행 상한
- [x] raw SHA-256 수집 단위와 staging 분리
- [x] 대학·캠퍼스·학년도·모집시기·전형·학과 업무키
- [x] 행·페이지 급감, 중복, 빈 키, 혼합연도 전체 batch 차단
- [x] 관리자 전체 행 확인 전 부분 게시 차단
- [x] raw·staging·published PostgreSQL 테이블과 migration
- [x] 과거 규칙 ID·버전·학년도 고정 및 현재 규칙 자동 재해석 차단
- [x] 활성 `PUBLISHED` 결과만 반환하는 분석 조회 서비스
- [x] 합성 transport·응답·결과만 사용하는 단위·통합 테스트

## 게이트 판정

`PASS`

- 단위 테스트 174건 통과
- PostgreSQL 통합 테스트 32건 통과
- Ruff·format·mypy 통과
- Alembic upgrade와 schema drift 검사 통과
- 규칙·민감자료 검사 통과
- 실제 외부 사이트 호출 0건
- 참고 원본·변환본 Git 포함 0건
