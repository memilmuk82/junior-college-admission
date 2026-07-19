# Phase 15 · 상담 제품 구조 재설계

## 목표

- 2027학년도 일반고 직업위탁 재학생이라는 고정 대상자 사실을 화면과 서버 입력 계약에 함께 적용한다.
- 공개 상담을 첫 화면의 핵심 기능으로 만들고, 성적 입력·대학/학과 선택·자격 판정·공개 입시결과 비교가 로그인 없이 이어지게 한다.
- 학생 저장/복제/BYOK, 교사의 비식별 지원·합격 결과 관리, 관리자의 출처 문서·검증·포털 수집 흐름을 기존 서비스 위에 보완한다.
- 공식 공개 결과, 사용자 개인 저장 자료, 기관 내부 비식별 결과를 서로 다른 권한과 표현으로 유지한다.

## 승인된 변경 경로

- 애플리케이션: `app/__init__.py`, `app/auth.py`, `app/routes.py`, `app/account_routes.py`, `app/admin_routes.py`, `app/admission_result_import_routes.py`, `app/teacher_routes.py`, `app/source_document_routes.py`, `app/models.py`
- 서비스/수집기: `app/services/`, `app/crawlers/`
- 화면/스타일: `app/templates/`, `app/static/css/app.css`, `app/static/js/public_calculation.js`
- DB: 신규 `migrations/versions/` migration 한 개
- 검증: 기존 핵심 테스트 수정과 Phase 15 합성 익명 테스트, 기존 Playwright 핵심 흐름
- 문서: `README.md`, `DEVELOPMENT_LOG.md`, `PROJECT_STATUS.md`, `docs/`

## 비범위

- 새 패키지·프레임워크·비동기 작업 큐 도입
- 원본 요구사항 문서 변경
- 기존 Compose 삭제·통합, 운영 DB migration, 포털 전체 네트워크 수집
- Docker volume·기존 데이터 삭제
- 커밋·푸시·배포·DNS·Cloudflare·호스트 Nginx 변경

## 단계 게이트

1. 고정 대상자 입력 계약과 공개 SSR 흐름
2. 개인 저장/복제와 역할별 접근 경계
3. 기관 내부 비식별 결과와 출처/수집 관리
4. 대표 단위·통합·브라우저 회귀, 민감자료 검사
5. README·개발 로그·상태 문서에 실제 결과 반영

지원자격이 `ELIGIBLE`로 확인되기 전 성적 계산을 수행하지 않으며, 공식 근거가 없는 규칙이나 합격 가능성을 생성하지 않는다.
