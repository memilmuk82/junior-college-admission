# Phase 11 작업 카드 — 내부 사용자 승인·권한·Google 로그인

## 목표

교직원·운영 사용자가 로컬 계정 또는 Google OIDC로 가입한 뒤 사람의 승인을 받아야만 상담 기능을 사용할 수 있게 한다. 역할은 `ADMIN`, `ASSISTANT_ADMIN`, `MEMBER`로 제한하고, 보조 관리자는 승인 대기 일반 회원의 승인만 수행한다.

상위 명세에서 제외한 **학생 공개 회원가입은 구현하지 않는다**. 이 Phase의 회원은 내부 교직원·운영 사용자다.

## 선행조건과 운영 경계

- Phase 10과 canonical 게시 게이트는 비운영 검증을 통과했다.
- live PostgreSQL은 `e51f0b24c8aa`, 저장소 migration head는 `0d9f4a7c2b11`이다.
- live의 기존 `golden_test_ref`는 대상 8개 테이블 모두 0건임을 읽기 전용 집계로 확인했다.
- 새 custom-format 백업의 checksum·archive 검증과 network-none 격리 복원이 통과했다.
- 현재 live 이미지 ID는 pre-migration 전용 로컬 롤백 태그에 고정했다. DB migration 이후의 단독 이미지 롤백으로 사용하지 않는다.
- 이번 구현에서 live DB migration, 실제 배포, Google OAuth client 생성·변경, 실제 회원 승인은 수행하지 않는다.

## 역할과 상태 계약

역할:

- `MEMBER`: 승인 후 상담 입력·검수·계산·학생/교사 출력과 본인 AI 설정 사용
- `ASSISTANT_ADMIN`: `MEMBER` 권한 + 승인 대기 `MEMBER` 승인
- `ADMIN`: 회원 상태·역할 및 기존 모든 관리자 설정 변경

상태:

- `PENDING_APPROVAL`
- `ACTIVE`
- `REJECTED`
- `SUSPENDED`

일반 가입과 최초 Google 로그인은 서버가 항상 `MEMBER/PENDING_APPROVAL`로 만든다. 클라이언트가 보낸 role/status는 무시한다. `ASSISTANT_ADMIN`은 자기 자신, 관리자·보조관리자, 이미 처리된 회원을 승인할 수 없고 역할 변경·거절·정지·관리 설정을 수행할 수 없다. 마지막 `ACTIVE ADMIN`의 강등·정지는 차단한다.

## 인증·OIDC 보안 계약

- 인증 완료 세션에는 불변 사용자 ID, `auth_version`, 인증 시각, CSRF 토큰만 둔다.
- 계정에는 불변·고유 `actor_ref`를 둔다. 기존 환경변수 관리자를 부트스트랩할 때는
  과거 검수·AI 소유권과의 호환을 위해 정규화된 기존 username을 유지하고, 신규 회원은
  `user:<uuid>`를 사용한다.
- 상태와 역할은 보호 요청마다 DB에서 다시 확인한다.
- 로그인 성공 때 session fixation을 막기 위해 기존 세션을 비운다.
- 승인 대기·거절·정지 사용자는 상담·관리 기능을 사용할 수 없다.
- Google은 Authlib의 Authorization Code + Discovery/JWKS + `state` + `nonce` + PKCE S256 흐름을 사용한다.
- Google 식별자는 이메일이 아니라 `(issuer, sub)`다. `email_verified=true`를 요구한다.
- 기존 로컬 계정과 같은 이메일의 새 Google identity를 자동 연결하지 않는다.
- OAuth code, access token, refresh token, ID token을 DB·세션·로그에 저장하지 않는다.
- callback query와 비밀값이 Nginx/Gunicorn/애플리케이션 로그에 남지 않게 한다.
- SQLAlchemy 오류의 statement parameter를 기록하지 않고 비식별 503 응답으로 실패한다.
- 상태 변경은 POST와 CSRF를 요구하며 외부 `next` redirect를 차단한다.

## 허용 수정 경로

- `tasks/PHASE_11.md`, `PROJECT_STATUS.md`, `DEVELOPMENT_LOG.md`
- `pyproject.toml`, `uv.lock`, `.env.example`, `Makefile`
- `app/__init__.py`, `app/models.py`, `app/routes.py`, `app/admin_routes.py`
- `app/auth.py`, `app/auth_routes.py`, `app/member_routes.py`
- `app/services/authentication.py`, `app/services/membership.py`, `app/services/google_oidc.py`, `app/services/review_state.py`
- `app/templates/auth_*.html`, `app/templates/admin_members*.html`, `app/templates/index.html`
- `app/static/css/app.css`
- `migrations/versions/*_phase_11_membership_rbac_oidc.py`
- `docker-compose.alpha.yml`, `docker-compose.beta.yml`, `docker-compose.production.yml`,
  `docker-compose.host-nginx.yml`, `docker-compose.google-oidc.yml`
- `deploy/nginx.production.conf`
- `scripts/check_production_readiness.py`, `scripts/bootstrap_production.py`, `scripts/bootstrap_admin.py`
- 위 계약을 직접 검증하는 `tests/test_authentication.py`, `tests/test_membership.py`,
  `tests/test_auth_routes.py`, `tests/test_member_routes.py`, `tests/test_admin_auth.py`,
  `tests/test_admin_rule_routes.py`, `tests/test_review_routes.py`, `tests/test_review_state.py`,
  `tests/test_ai_routes.py`,
  `tests/test_consultation_routes.py`, `tests/test_migrations.py`,
  `tests/test_production_config.py`, `e2e/auth-membership.spec.js`, `e2e/admin.spec.js`

기준 원본 두 문서, 실제 secret, 실제 Google 계정·토큰, 학생 자료, 공식 모집요강 원본은 수정·반입하지 않는다.

## 먼저 작성할 실패 테스트

1. 로컬 가입은 role/status 조작에도 `MEMBER/PENDING_APPROVAL`이다.
2. 승인 전·거절·정지 회원은 보호 기능에 접근할 수 없고 승인 후에는 접근할 수 있다.
3. `ASSISTANT_ADMIN`은 대기 `MEMBER` 승인만 가능하며 모든 설정 변경은 403이다.
4. `ADMIN`은 회원 상태·역할과 기존 관리자 기능을 관리할 수 있다.
5. 마지막 활성 관리자의 강등·정지는 차단된다.
6. 상태·역할·비밀번호 변경 뒤 기존 `auth_version` 세션은 무효다.
7. CSRF, session fixation, open redirect, 계정 존재 여부 노출을 차단한다.
8. Google identity는 검증된 issuer/sub/email_verified만 수용하고 신규 계정은 승인 대기다.
9. 같은 Google subject는 멱등이며 같은 이메일의 로컬 계정에 자동 연결하지 않는다.
10. 비밀번호·OAuth code/state/token이 응답·세션·로그에 노출되지 않는다.
11. 환경변수 관리자를 DB의 활성 관리자 계정으로 멱등 부트스트랩한다.
12. JavaScript 없이 가입→대기→보조관리자 승인→로그인 흐름이 동작한다.
13. 사용자 행동 뒤 핵심 화면·DB 저장·브라우저 오류 부재를 Playwright로 검증한다.

## 수용 기준

- Given 신규 내부 사용자, When 로컬 또는 Google로 가입하면, Then 승인 대기 상태만 생성되고 보호 기능은 차단된다.
- Given 활성 보조 관리자, When 승인 대기 일반 회원을 승인하면, Then 회원은 새 로그인부터 사용 가능하고 감사 이벤트가 남는다.
- Given 보조 관리자, When 역할·규칙·시스템 설정을 변경하려 하면, Then 변경 없이 403이다.
- Given 활성 관리자, When 회원을 관리하면, Then 마지막 관리자 안전 제약과 감사 추적을 유지한다.
- Given 유효한 Google callback, When 최초 identity가 확인되면, Then 토큰을 보관하지 않고 승인 대기 회원과 불변 subject 연결만 저장한다.
- Given 보호 기능, When 지원자격 판정이 확정되지 않았으면, Then 기존과 동일하게 성적 계산을 수행하지 않는다.
- 전체 단위·PostgreSQL 통합·migration drift·SSR·Playwright·민감자료 검사가 통과한다.

## 실행 명령

```bash
make lint
make test-unit
make test-integration
make test-e2e
make validate-rules
make check-sensitive-data
make check
```

Google 실제 브라우저 로그인은 별도 OAuth client·HTTPS redirect URI가 있을 때만 검증한다. 이번 Phase의 자동 테스트는 합성 OIDC 응답과 네트워크 없는 실패 계약을 사용한다.

## 독립 검증과 남은 위험

- 독립 검증자는 권한 우회, pending 접근, 마지막 관리자, 동시 승인, OAuth 계정 연결, query-string 로그 노출을 재검사한다.
- 실제 Google 로그인의 남은 외부 조건은 Google Cloud의 Web application client와 정확히 일치하는 HTTPS callback URI다.
- live migration과 배포는 이 Phase 코드 검증과 별도 변경창·백업·post-migration 롤백 계획을 요구한다.
- 기존 환경변수 관리자 username과 DB 관리자의 `actor_ref`가 동일함을 회귀 테스트로 고정한다.
- 컨테이너 Nginx에는 로그인·가입 IP rate limit이 있으나 host-Nginx/Cloudflare 경로에도
  동등한 제한을 적용하기 전 공개 전환하지 않는다.
- pre-migration 롤백은 DB 복원 확인·이미지 ID 일치·`--no-build`를 강제하는
  `production-origin-rollback-app`만 사용하며, 구버전 이미지에서는 신규 관리자
  bootstrap 명령도 건너뛴다. image-only rollback은 금지한다.

## 작업 항목

- [x] 운영 사전 안전 게이트와 rollback-pre-migration 이미지 태그
- [x] 실패 테스트와 회원·identity·감사 DB 계약
- [x] 로컬 가입·로그인·승인 대기·로그아웃
- [x] ADMIN/ASSISTANT_ADMIN/MEMBER 권한 행렬과 감사
- [x] Google OIDC 가입·로그인과 자동 연결 금지
- [x] Google issuer 허용 표기를 canonical HTTPS issuer로 고정해 subject 멱등성 보장
- [x] 환경변수 관리자 멱등 DB 부트스트랩
- [x] 기존 관리자 `actor_ref`·검수·AI 소유권 호환과 비식별 DB 오류 처리
- [x] 동시 승인·상태/비밀번호 세션 무효화·감사 이벤트 회귀
- [x] OAuth query·secret 비노출 로그 설정
- [x] 컨테이너 Nginx의 모든 공개 로그인·가입 진입점 rate limit과 안전한 `--no-build` 롤백 게이트
- [x] SSR·PostgreSQL·migration·Playwright 회귀
- [x] 민감자료 검사와 독립 보안 검증

## 완료 판정

- 판정: `PASS_NONPROD_PHASE_11`
- 단위 273건, PostgreSQL 통합 112건, 무JavaScript Playwright 2건을 통과했다.
- 운영 백업 복제본의 `e51f0b24c8aa`에서 `6c1a2e9f4b73`까지 전체 migration을 통과했고 기존 `golden_test_ref` 합계는 0건을 유지했다.
- live DB·live 앱에는 migration이나 회원 부트스트랩을 적용하지 않았다.
- pre-migration 이미지 태그 단독 rollback은 신규 DB head와 호환되지 않는다. 실제 배포 rollback은 검증 백업 복원 또는 신규 head 호환 이미지가 필요하다.
- 현재 live 호스트 Nginx는 callback query를 기본 access log에 남길 수 있으므로 이를 수정하기 전 Google OIDC override를 활성화하지 않는다.
- host-Nginx/Cloudflare의 공개 로그인·가입 rate limit과 실제 Google Web application
  client/HTTPS callback 등록은 배포 전 운영 게이트다.
