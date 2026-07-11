# 테스트 전략

Phase 0 검증 범위는 다음과 같다.

- Flask 앱 셸과 `/health` 응답
- Git 포함 대상의 원본 문서·스프레드시트·DB·환경 파일·API 키 패턴 검사
- `.gitignore`와 `.dockerignore` 정책의 수동 검토

후속 기능은 기준 문서에 따라 `Red → Green → Refactor → Regression → Independent check → Record` 순서를 적용한다.

## Phase 1 검증 범위

- 단위 테스트: Flask 셸, 임시 원본·파생물 삭제, 규칙 seed 계약
- PostgreSQL 17 통합 테스트: Alembic 최초 migration과 필수 테이블 전체
- Flask-Migrate 통합 테스트: `flask db upgrade`, schema drift 없는 `flask db migrate`
- PostgreSQL 제약 테스트: 혼합연도 문서 게시, 근거 없는 규칙 게시 차단
- 학생 성적 출처 분리 저장과 앱 팩토리 DB 연결
- Ruff 형식·정적 검사와 mypy 타입 검사
- Git 포함 대상 민감정보 검사
