# Phase 1 작업 카드

## 목표

PostgreSQL 전용 문서·규칙·학생성적 스키마와 Alembic 마이그레이션을 만들고, 학생 원본과 파생물을 세션 단위로 임시 저장한 뒤 삭제 여부를 검증하는 기반을 구축한다.

## 선행조건과 근거

- `PROJECT_STATUS.md`의 Phase 0 `PASS`
- 실행 개발 문서 v2의 `Phase 1 하네스·스키마·개인정보 기반`
- 마스터 프롬프트 v3의 `Phase 1 하네스·스키마·삭제 기반`
- 저장소 지침의 PostgreSQL 기본 DB 및 분리 컨테이너·volume 원칙
- 실제 대학 규칙은 사용하지 않으며 스키마 계약 `phase1-schema-v1`만 정의

## 허용 수정 경로

- 하네스: `pyproject.toml`, `uv.lock`, `Makefile`, `alembic.ini`, `migrations/`, `Dockerfile`, `docker-compose.yml`, `.env.example`
- 애플리케이션: `app/__init__.py`, `app/database.py`, `app/models.py`, `app/services/`
- 검증: `tests/`, `scripts/check_sensitive_data.py`, `scripts/validate_rules.py`
- 기록: `README.md`, `PROJECT_STATUS.md`, `DEVELOPMENT_LOG.md`, `docs/DATABASE_OPERATIONS.md`, `docs/PRIVACY_DATA_RETENTION.md`, `docs/RULE_SCHEMA.md`, `docs/TEST_STRATEGY.md`, `tasks/PHASE_1.md`

## 금지 사항

- 두 기준 문서와 Phase 0 카드 수정
- SQLite DB 또는 SQLite 기반 테스트 추가
- 실제 대학 전형 규칙·학생 자료·원본 모집요강 추가
- 자격 판정·성적 계산·입력 파서·상담 UI 구현
- Codex가 규칙을 `HUMAN_APPROVED`로 승인하거나 공식 근거가 없는 규칙을 게시
- 원본 파일명, 학생 행 또는 성적 원문을 로그에 기록

## Given/When/Then 수용 기준

- Given 빈 PostgreSQL 테스트 데이터베이스, When Alembic을 `head`까지 실행하면, Then 문서·규칙·학생성적 핵심 테이블과 제약조건이 생성된다.
- Given Flask 앱과 PostgreSQL 연결, When `flask db migrate`와 `flask db upgrade`를 실행하면, Then CLI가 정상 실행되고 metadata와 최초 migration 사이에 schema drift가 없다.
- Given 혼합연도 문서, When `PUBLISHED` 상태로 저장하면, Then PostgreSQL이 게시를 거부한다.
- Given 사람 승인·출처·골든 테스트가 없는 규칙, When `PUBLISHED` 상태로 저장하면, Then PostgreSQL이 게시를 거부한다.
- Given 동일 학생의 원적교와 위탁기관 성적, When 저장하면, Then 서로 다른 `record_source` 레코드로 보존된다.
- Given 합성 업로드 원본과 파생물, When 검수 세션을 폐기하면, Then 세션 디렉터리가 없어졌음을 검증한다.
- Given 삭제 함수가 파일을 남긴 경우, When 삭제 검증을 수행하면, Then 조용히 성공하지 않고 명시적 오류를 낸다.

## 먼저 작성할 실패 테스트

- 필수 테이블·제약조건의 PostgreSQL 마이그레이션 테스트
- 혼합연도 문서 및 미승인 공개 규칙 차단 테스트
- 학생 성적 출처 분리 저장 테스트
- 임시 원본·파생물 삭제 및 삭제 실패 표면화 테스트
- 앱 팩토리의 PostgreSQL 초기화 테스트

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

- 독립 검증 역할: 구현 코드와 별도로 PostgreSQL Alembic `upgrade head` 결과, SQLAlchemy 메타데이터, 삭제 후 파일시스템, Git 포함 대상을 순차 대조한다.
- 남은 위험: 실제 학생 입력 파서와 OCR은 Phase 2 범위이며, 현재 테스트는 합성 익명 데이터만 사용한다.
