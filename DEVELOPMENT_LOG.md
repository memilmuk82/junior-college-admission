# 개발 기록

## 2026-07-10 · Phase 0

- 빈 `main` 브랜치와 기존 요구사항 문서 두 개를 확인했다.
- 문서의 상하 관계와 Phase 경계를 검토했다.
- 저장소에 실제 학생 자료, PDF·엑셀, 업로드 파일, DB 또는 파생 이미지가 없음을 확인했다.
- 저장소 안전 정책, 초기 Flask 앱 셸, 검증 스크립트와 테스트를 추가했다.

## 2026-07-11 · Phase 1

- DB와 DB 통합 테스트를 PostgreSQL 17로 통일했다.
- 문서·규칙·학생성적 23개 핵심 테이블과 Alembic 최초 migration을 추가했다.
- SQLAlchemy 2.x 모델을 Flask-SQLAlchemy와 연결하고 Flask-Migrate CLI를 등록했다.
- 혼합연도 문서와 승인·출처·골든 테스트가 없는 공개 규칙을 DB 제약으로 차단했다.
- 원적교·위탁기관 성적 출처를 분리하고 임시 원본·파생물 삭제 검증 서비스를 추가했다.
- 단위 테스트 7건과 PostgreSQL 통합 테스트 7건이 통과했다.
- Ruff, mypy, 규칙 검증, 민감자료 검사가 통과했다.
- 실제 학생 자료와 실제 대학 규칙은 사용하지 않았다.


## 확정 기술 결정

- uv로 Python 환경과 잠금 파일을 관리한다.
- PostgreSQL을 기본 DB로 사용하고 `web`·`db`·`postgres_data`를 분리한다.
- Jinja2 SSR을 기본으로 하며 SPA·TypeScript를 사용하지 않는다.
- 핵심 흐름은 JavaScript 없이 동작하고 별도 A4 인쇄 CSS를 사용한다.

## 검증 기록

- pytest: 2건 통과
- 민감자료 검사: 통과
- Docker Compose config: 통과
- Python·백업 스크립트 구문 검사: 통과
- Docker web 이미지 빌드: 통과
- 실제 HTTP `/`, `/health`, 인쇄 CSS 응답: 통과
- 자동 브라우저 검증: 실행 도구 미설치로 미수행, HTTP 검증으로 대체
