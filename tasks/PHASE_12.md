# Phase 12 작업 카드 — 사이트 기능 완성·공개 데모

## 목표

운영자가 합성 코드나 직접 DB 작업 없이 관리자 화면에서 상담에 필요한 대학·캠퍼스·학과·모집시기·전형 기준정보를 등록하고 조회할 수 있게 한다. 기존 규칙 검수·상담·출력 기능과 데이터 게시 안전 게이트는 유지한다.

포트폴리오 방문자는 의도적으로 공개된 데모 교사 계정으로 로그인해 실제 대학·학생 자료와 분리된 합성 상담 흐름과 학생용·교사용 A4 출력을 체험할 수 있게 한다. 데모 계정은 관리자·회원관리·규칙관리·파일 검수·BYOK AI 기능에 접근하지 못한다.

## 선행조건과 경계

- Phase 8 상담 UI와 Phase 11 회원 인증 코드는 비운영 환경에서 동작한다.
- 구현 시작 시 운영 DB 기준선은 `e51f0b24c8aa`이며, 운영 migration·배포는 코드 수용 기준과 별도로 사용자 승인·새 백업·격리 복원을 통과한 경우에만 수행한다.
- 공식 근거와 검수 없이 전형 규칙을 생성하거나 게시하지 않는다.
- 기존 모델을 사용하며 이번 기능 단위에서는 migration을 추가하지 않는다.
- 데모 자료는 공식 모집요강이나 게시 규칙으로 저장하지 않고 메모리의 명시적 합성 예시로만 실행한다.

## 허용 수정 경로

- `tasks/PHASE_12.md`, `PROJECT_STATUS.md`, `DEVELOPMENT_LOG.md`, `README.md`
- `app/admin_routes.py`, `app/services/catalog_admin.py`
- `app/__init__.py`, `app/auth.py`, `app/auth_routes.py`, `app/routes.py`
- `app/services/membership.py`, `app/services/eligibility.py`,
  `app/services/demo_consultations.py`
- `app/templates/admin_catalog.html`, `app/templates/admin_rules.html`, `app/templates/index.html`
- `app/templates/auth_login.html`, `app/templates/admin_consultation_form.html`
- `app/templates/admin_consultation_result.html`, `app/templates/consultation_print.html`
- `app/static/css/app.css`
- `.env.example`, `docker-compose.alpha.yml`, `docker-compose.beta.yml`,
  `docker-compose.production.yml`, `docker-compose.google-oidc.yml`
- `Makefile`, `deploy/postgres_demo_rollback_gate.sql`
- 이 기능을 직접 검증하는 `tests/test_admin_rule_routes.py`, `tests/test_auth_routes.py`,
  `tests/test_consultation_routes.py`, `tests/test_application_policies.py`,
  `tests/test_production_config.py`

## 금지 사항

- 기준 원본 문서 수정
- 별도 사용자 승인과 복구 게이트 없는 운영 DB migration·배포, Nginx·Cloudflare 변경
- 실제 비밀값·학생자료·공식 원본 반입
- 연쇄 삭제 위험이 있는 기준정보 삭제 UI
- 공식 근거 없는 규칙 자동 생성·승인·게시
- 데모 계정에서 업로드·AI 키·AI 초안·관리 기능 허용
- 데모 합성 자료를 일반 회원의 게시 상담 대상으로 노출

## 수용 기준

- 관리자는 대학, 캠퍼스, 학과, 모집시기, 전형을 화면에서 순서대로 등록하고 즉시 조회할 수 있다.
- 캠퍼스·학과·모집시기·전형의 상위 참조를 서버에서 검증한다.
- 모집시기 대학과 학과 소속 대학이 다른 전형은 저장하지 않는다.
- 중복·누락·잘못된 코드는 데이터베이스 오류 원문 대신 사용자 메시지로 표시한다.
- 일반 회원과 비로그인 사용자는 기준정보 관리 화면에 접근할 수 없다.
- 등록만으로 규칙이나 상담 대상이 자동 게시되지 않는다.
- 구성된 공개 데모 계정은 별도 관리자 승인 없이 멱등 부트스트랩되며 `MEMBER/ACTIVE`만 갖는다.
- 데모 계정은 합성 학생·합성 대학·합성 규칙임을 모든 상담·출력 화면에 표시한다.
- 데모 상담은 지원자격 선행 판정과 결정론적 성적 계산 엔진을 재사용하되 DB 게시 규칙을 생성하지 않는다.
- 데모 계정은 상담 입력·결과·학생용/교사용 출력 외 쓰기 기능과 관리 기능에서 403으로 차단된다.
- 일반 회원과 관리자는 기존 DB 게시 규칙 상담 흐름을 그대로 사용하며 데모 합성 대상을 보지 않는다.

## 현재 기능 단위

- [x] 대학·전형 기준정보 등록·조회
- [x] 관련 PostgreSQL route 테스트
- [x] 관리자 화면에서 실제 등록 흐름 확인

- [x] 공개 데모 교사 계정 멱등 부트스트랩
- [x] 데모 전용 합성 학생 상담·A4 출력
- [x] 데모 계정의 관리·업로드·BYOK AI 차단
- [x] README 공개 체험 계정·Google 로그인 상태 안내

## 릴리스·운영 검증

- [x] 구현 커밋 `a55e679a90492c431f7b7dff680f3b8099307b59`를 `main`·`origin/main` 이력에 동기화하고 운영 결과를 후속 문서 커밋에 반영
- [x] 새 live custom-format 백업·SHA-256·archive·manifest·network-none/tmpfs 격리 복원
- [x] 이전 image ID·rollback 태그 보존과 production 이미지 재빌드
- [x] 승인된 live migration `e51f0b24c8aa → 6c1a2e9f4b73`과 web 교체
- [x] Docker health·loopback origin·Cloudflare/host Nginx 공인 HTTPS·TLS·보안 헤더
- [x] 운영 관리자·모바일·무JavaScript Playwright와 비파괴 catalog·데모 권한 smoke
- [x] 최근 web·전용 Nginx 로그의 5xx·fatal·query·비밀값·학생 PII 패턴 0건
- [x] live catalog·공식 게시 규칙 0건, Google OIDC 비활성 유지

운영 성공 등록은 합성 기준정보를 남기지 않기 위해 실행하지 않았다. 대학→캠퍼스→학과→모집시기→전형의 실제 저장과 DB 결과는 격리 PostgreSQL E2E에서 확인했고, live에서는 동일 이미지·migration의 관리자 조회와 유효성 오류 경로를 비파괴로 검증했다. 공식 근거와 사람 승인을 받은 규칙이 없으므로 최종 콘텐츠 상태는 준비 전이다.
