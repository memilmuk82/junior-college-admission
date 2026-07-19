# Phase 16 작업 카드 — 역할별 업무공간과 학생·교사 연동

## 목표

- 학생이 본인 성적·저장 상담·교사 학급 연결·개인 BYOK 분석으로 바로 이동하는 메뉴를 사용한다.
- 교사가 학과·학급과 비식별 학생 명단을 관리하고, 학생별 성적을 추가·확인한 뒤 BYOK 상담자료를 만든다.
- 학생이 교사가 발급한 일회용 연결 코드로 명단에 연결되면 원본 소유권을 바꾸거나 복사하지 않고 두 계정에 허용된 성적·상담자료를 함께 표시한다.
- `ASSISTANT_ADMIN`의 관리 기능은 승인 대기 계정 승인으로 제한하고, `ADMIN`만 역할·상태·기준정보·입시결과 import·포털 수집·출처 문서 업로드와 검증을 수행한다.

## 승인된 변경 경로

- 애플리케이션: `app/__init__.py`, `app/auth.py`, `app/auth_routes.py`, `app/member_routes.py`, `app/account_routes.py`, `app/admin_routes.py`, `app/teacher_routes.py`, `app/models.py`
- 서비스: `app/services/`
- 화면/스타일: `app/templates/`, `app/static/css/app.css`, 기존 Vanilla JavaScript
- DB: `migrations/versions/` 신규 migration 한 개
- 검증: `tests/`의 합성 익명 단위·PostgreSQL·Playwright 테스트
- 문서: `README.md`, `DEVELOPMENT_LOG.md`, `PROJECT_STATUS.md`, `docs/`, 이 작업 카드
- 자동화: `Makefile`의 Phase 16 통합·Playwright 검증 대상 추가
- 릴리스: 민감정보 검사와 전체 회귀 통과 후 현재 변경만 커밋·push하고, 운영 백업을 검증한 뒤 기존 production Compose의 `web-production` 이미지만 재빌드·재기동한다.

## 금지 사항

- 기존 Docker volume·운영 데이터 삭제
- 원본 요구사항 문서 변경
- 실제 학생 이름·학번·성적을 테스트·Git·로그에 저장
- 학생 성적을 교사 계정으로 복사하거나 소유권을 묵시적으로 이전
- 연결 코드 원문을 DB·로그에 저장
- 보조 관리자에게 역할·상태·입시자료·규칙·수집 권한 부여
- 근거 없는 입시 규칙 게시 또는 포털 전체 자동 수집

## 수용 기준

1. 역할별 대시보드에서 허용된 메뉴만 보이며 서버 권한과 일치한다.
2. 학생과 교사는 각자 암호화된 BYOK 키와 비식별 상담 초안을 관리한다.
3. 교사는 학과·학급·비식별 학생 코드를 만들고 해당 학생 성적을 직접 추가·확인한다.
4. 연결 코드는 한 번만 표시되고 SHA-256 digest·끝 4자리·24시간 만료만 저장되며 사용·해제·계정 정지/역할 변경 후 폐기된다.
5. 학생이 전체 공유 범위에 명시적으로 동의한 뒤 연결 학생과 담당 교사는 공유된 성적·상담을 읽을 수 있지만 상대 소유 자료를 삭제하거나 수정할 수 없다.
6. 연결되지 않은 다른 학생·교사 계정에는 존재 여부를 포함해 자료가 노출되지 않는다.
7. 보조 관리자는 승인 대기 학생·교사·일반 회원 승인만 가능하고 관리자 전용 route는 403이다.
8. 주 관리자는 회원 역할·상태, 기준정보, 규칙, 입시결과 파일 import, 제한형 포털 수집, PDF·PNG·JPG·CSV·XLSX 출처 문서 입력·검증 메뉴를 사용한다.
9. JavaScript 없이 핵심 생성·연결·성적 추가·승인 흐름이 동작한다.
10. 단위·PostgreSQL 통합·Playwright·lint·mypy·규칙·민감정보 검사가 통과한다.

## 릴리스 게이트

1. `git status`, `git diff`, 민감정보 검사를 검토한다.
2. 현재 변경 경로만 자연스러운 한국어 메시지로 커밋하고 `origin/main`에 push한다.
3. 운영 PostgreSQL custom-format 백업·checksum·archive 검증을 완료한다.
4. `production-origin-up`으로 비파괴 Alembic upgrade와 웹 이미지 재빌드를 수행한다.
5. migration head·health·공인 HTTPS 역할별 핵심 화면을 확인한다.
