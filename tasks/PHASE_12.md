# Phase 12 작업 카드 — 사이트 기능 완성

## 목표

운영자가 합성 코드나 직접 DB 작업 없이 관리자 화면에서 상담에 필요한 대학·캠퍼스·학과·모집시기·전형 기준정보를 등록하고 조회할 수 있게 한다. 기존 규칙 검수·상담·출력 기능과 데이터 게시 안전 게이트는 유지한다.

## 선행조건과 경계

- Phase 8 상담 UI와 Phase 11 회원 인증 코드는 비운영 환경에서 동작한다.
- 운영 DB는 현재 `e51f0b24c8aa`이므로 이 작업에서 운영 migration이나 배포를 수행하지 않는다.
- 공식 근거와 검수 없이 전형 규칙을 생성하거나 게시하지 않는다.
- 기존 모델을 사용하며 이번 기능 단위에서는 migration을 추가하지 않는다.

## 허용 수정 경로

- `tasks/PHASE_12.md`, `PROJECT_STATUS.md`, `DEVELOPMENT_LOG.md`, `README.md`
- `app/admin_routes.py`, `app/services/catalog_admin.py`
- `app/templates/admin_catalog.html`, `app/templates/admin_rules.html`, `app/templates/index.html`
- `app/static/css/app.css`
- 이 기능을 직접 검증하는 `tests/test_admin_rule_routes.py`

## 금지 사항

- 기준 원본 문서 수정
- 운영 DB migration·배포, Nginx·Cloudflare 변경
- 실제 비밀값·학생자료·공식 원본 반입
- 연쇄 삭제 위험이 있는 기준정보 삭제 UI
- 공식 근거 없는 규칙 자동 생성·승인·게시

## 수용 기준

- 관리자는 대학, 캠퍼스, 학과, 모집시기, 전형을 화면에서 순서대로 등록하고 즉시 조회할 수 있다.
- 캠퍼스·학과·모집시기·전형의 상위 참조를 서버에서 검증한다.
- 모집시기 대학과 학과 소속 대학이 다른 전형은 저장하지 않는다.
- 중복·누락·잘못된 코드는 데이터베이스 오류 원문 대신 사용자 메시지로 표시한다.
- 일반 회원과 비로그인 사용자는 기준정보 관리 화면에 접근할 수 없다.
- 등록만으로 규칙이나 상담 대상이 자동 게시되지 않는다.

## 현재 기능 단위

- [ ] 대학·전형 기준정보 등록·조회
- [ ] 관련 PostgreSQL route 테스트
- [ ] 관리자 화면에서 실제 등록 흐름 확인

