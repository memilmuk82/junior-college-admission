# Phase 10 작업 카드

## 목표

검증된 규칙을 대학 5곳 단위로 확대할 수 있는 운영 기반을 만들고, 최종 모집요강 교체·성능·보안·백업·복구와 현장 교사 파일럿을 준비한다.

## 범위

- 공개 근거와 규칙 버전이 확인된 대학만 배치에 포함
- 기존 게시 규칙을 덮어쓰지 않는 최종 모집요강 교체
- PostgreSQL 백업 생성·보호·복구 리허설 절차
- 성능 기준과 운영 보안 점검
- 합성 데이터 기반 현장 교사 파일럿 체크리스트

## 안전 경계

- 실제 운영 DB 삭제·복구와 외부 배포는 별도 명시 승인 없이는 수행하지 않는다.
- 실제 학생 자료와 원본 모집요강을 저장소·테스트·백업 예제로 사용하지 않는다.
- 공식 PDF가 없는 규칙은 `MANUAL_REVIEW` 또는 `VERIFIED_REFERENCE`로 유지하고 자동 게시하지 않는다.
- Phase 9 Gemini·Anthropic 유료 실키 검증은 완료 조건에서 제외하며, 합성 HTTP 계약 통과와 실제 성공 미주장을 유지한다.

## 작업 항목

- [x] Phase 10 작업 카드와 운영 게이트 정의
- [x] 백업 파일 권한·원자적 생성·실패 시 임시파일 정리
- [x] 백업·복구 런북과 읽기 전용 검증 절차 문서화
- [x] 2027학년도 공식 모집요강 후보 5곳 목록과 근거 대기 상태 점검
- [x] 후보별 대학·캠퍼스·모집시기·전형·페이지 교차검증(공식 후보·시행계획·독립 검수 대기·혼합연도·버전 충돌 분리)
- [x] 2차 페이지 검증 대상 10곳 추가 및 파일·페이지 수 인벤토리 확인
- [x] 2차 10곳 핵심 지원자격·반영학기·Z점수 페이지 대조 및 혼합연도 분리
- [x] 최종 모집요강 교체의 새 버전·영향도·회귀 테스트(합성 시행계획→최종본 계보·Decimal 영향도·롤백 보존)
- [x] 합성 회귀 실행시간 기준선 기록 (운영 쿼리 관찰 지표는 후속)
- [x] 합성 BYOK 암호화·교체·삭제 및 잘못된 키 거부 테스트 확인
- [x] 합성 보안·키 회전 검증과 보유기간 정책 주입형 dry-run 준비(실제 운영 실행은 별도 전환 게이트)
- [x] 합성 후보·교사 검토 흐름 테스트 (단위 10건, PostgreSQL 통합 게이트 52건에 관리자 AI 흐름 포함)
- [x] Phase 10 최종 게이트 `PASS_NONPROD` — 개발·합성 production 후보 준비 완료, 실제 운영 전환 별도 보류

## 비운영 준비 패키지

- [x] 상세 런북·승인 체크리스트
- [x] 합성 모집요강 버전 교체 리허설 절차
- [x] PostgreSQL 지표 수집 설정·검증 초안
- [x] 합성 키 회전 후 검증 체크리스트
- [x] 보유기간 정책 주입형 dry-run 조회 초안(실행 금지)

## 비운영 종료 판정

`비운영 준비 완료 — 운영 전환 별도 보류`로 종료한다. 운영 키 회전·운영 데이터 삭제·운영 PostgreSQL 설정 변경·실제 모집요강 게시·운영 배포는 향후 운영 전환 Phase로 이관하며 현재 Phase에서 실행하지 않는다.

## 내부 알파 컨테이너

- [x] 운영 Compose와 분리된 알파 앱·PostgreSQL 프로젝트 구성
- [x] 알파 DB·업로드 named volume과 loopback 앱 포트 분리
- [x] 시작 시 Alembic `head` 적용과 앱·DB healthcheck
- [x] 빈 DB 관리자 Playwright smoke 3건 통과
- [x] 전체 정적·단위 217건·PostgreSQL 통합 52건·규칙·민감자료 검사 통과
- [x] 합성 상담 seed 기반 알파 컨테이너 Playwright 8건 통과(업로드 검수 세션 전용 3건은 별도 skip)
- [x] 비식별 OpenAI 알파 smoke(`gpt-4.1-mini`)와 키 인증 통과

내부 알파 인프라와 합성 기능 인수는 `PASS`다. `gpt-5-mini`는 15초 응답 제한을 초과했으므로 알파에서는 검증된 `gpt-4.1-mini`를 사용한다. 베타 전환 전 별도 업로드 검수 세션 E2E와 WSGI·secret manager 등 베타 배포 조건을 확인한다.

## 내부 베타 컨테이너

- [x] 알파와 분리된 베타 Gunicorn 앱·PostgreSQL 프로젝트 구성
- [x] 베타 시작 시 Alembic `head`, HTTP health, Gunicorn 23 확인
- [x] 합성 상담·BYOK·학생/교사 A4 Playwright 8건 통과
- [x] 합성 OCR 업로드 검수 데스크톱·모바일·무JavaScript Playwright 3건 통과
- [x] env-file의 Werkzeug 해시 `$` 보존 절차 검증

내부 베타 인수는 총 Playwright 11건 실패·skip 0으로 `PASS`다. 실제 서비스 전환은 reverse proxy·TLS, 운영 secret manager, 보유기간·백업·복구 정책, 최종 모집요강 사람 승인과 운영 변경창이 확인될 때까지 별도 보류한다.

## 실제 서비스 시작 차단 계약

- [x] 운영 모드의 개발용·짧은 `SECRET_KEY` 거부
- [x] PostgreSQL 외 `DATABASE_URL` 거부
- [x] 관리자 ID와 유효한 Werkzeug scrypt 해시 검증
- [x] Fernet `BYOK_MASTER_KEY` 검증
- [x] HTTPS `PUBLIC_BASE_URL`과 정확한 `TRUSTED_HOSTS` 검증
- [x] 신뢰 reverse proxy 한 단계만 허용
- [x] secure·HTTP-only·SameSite session cookie와 `ProxyFix` 적용
- [x] 비밀값을 출력하지 않는 `make production-preflight`

위 검사는 안전하지 않은 구성으로 운영 프로세스가 시작되는 것을 차단한다. reverse proxy·TLS 인증서·secret manager·정책·공식 자료 승인이 실제 환경에서 확인되기 전에는 외부 배포를 수행하지 않는다.

## 합성 production 후보 리허설

- [x] Nginx TLS → Gunicorn → PostgreSQL 분리 구성과 독립 network·volume
- [x] 파일 기반 secret 주입과 direct 값 동시 지정·빈값·다중행·과대 파일 차단
- [x] PostgreSQL migration `head`와 앱·DB·proxy healthcheck
- [x] CA 검증 HTTPS health와 HSTS·nosniff·referrer·frame 보안 헤더
- [x] HTTP → HTTPS `308` redirect와 Nginx 설정 검사
- [x] 관리자·상담·BYOK·학생/교사 A4 Playwright 8건 통과
- [x] 합성 OCR 업로드 검수 데스크톱·모바일·무JavaScript Playwright 3건 통과
- [x] 호스트 Nginx 원본 포트를 `127.0.0.1:8000`으로 제한하고 컨테이너 수신 포트와 일치
- [x] 호스트 Nginx용 Gunicorn production override와 앱 보안 헤더 계약
- [x] 전체 정적·단위 241건·PostgreSQL 통합 53건·규칙·민감자료 검사 통과

위 리허설은 `/tmp`의 합성 secret·단기 인증서·익명 데이터만 사용했다. 실제 도메인·공인 TLS·secret manager·운영 DB·외부 Cloudflare 설정·공식 모집요강 게시 상태는 변경하지 않았으며 별도 운영 게이트로 남긴다.

## 게이트

Phase 9는 OpenAI 비식별 실호출, 세 공급자 합성 HTTP 계약, BYOK 암호화와 교사 확정 경계를 통과했다. Gemini·Anthropic 유료 실키 호출은 사용자 방침에 따라 완료 조건에서 제외했으며 실제 연결 성공을 주장하지 않는다.

Phase 10은 대학 후보 근거 분류, 버전 교체 영향도, 알파·베타·합성 production 후보, PostgreSQL 통합, HTTPS E2E, 비운영 보안·삭제 준비까지 통과해 `PASS_NONPROD`로 종료한다. 실제 도메인·공인 TLS·secret manager·운영 DB 정책·최종 모집요강 사람 승인·운영 변경창은 저장소 개발 Phase가 아닌 별도 운영 전환 게이트로 유지한다.

## 실제 서비스 기반 부트스트랩

- [x] live 전용 PostgreSQL·업로드 volume을 기존 합성 환경과 분리
- [x] 호스트 계정 UID/GID로 비root 웹 컨테이너를 실행하고 `0600` secret 읽기 확인
- [x] 네트워크 없는 최소 capability 초기화 컨테이너로 업로드 volume 권한 `0700` 적용
- [x] Alembic `head`, Gunicorn health, loopback 원본 포트 확인
- [x] 호스트 Nginx·Cloudflare 공인 HTTPS health와 HSTS 등 보안 헤더 확인
- [x] 실제 HTTPS 관리자 smoke Playwright 3건 통과

실제 서비스 기반의 빈 DB 부트스트랩은 `PASS_LIVE_BOOTSTRAP`이다. 이는 서버 경로가 정상이라는 판정이며, 공식 대학 규칙의 사람 승인·게시나 학생 실데이터 반입을 뜻하지 않는다. 키 회전, 보유기간 삭제, PostgreSQL 관찰 지표와 백업·복구는 운영 안정화 게이트에서 별도로 수행한다.
