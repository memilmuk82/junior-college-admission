# 프로젝트 상태

- 기준일: 2026-07-20
- 현재 단계: Phase 17 공개 검증 흐름과 2026 입시결과 복구
- 단계 판정: `PASS_PRODUCTION_PHASE_17` — 위탁학생 기본 성적 계약, 2026 공개 결과, 전체 대학·학과 선택, 네 역할 데모와 BYOK 격리를 운영 HTTPS에서 검증
- 현재 작업: 구현 커밋·push, 운영 backup/restore 검증, migration `b6f1e8a42c73`, 2026 seed, `web-production` 비파괴 재빌드와 역할별 Chromium 회귀 완료
- 다음 게이트: 운영자가 로그인 화면의 네 데모 계정으로 사용자 인수 확인을 진행하고, 공식 모집요강 기반 실행 규칙은 기존 사람 검수·게시 게이트를 계속 적용

## 저장소 인벤토리

| 구분 | 상태 | 비고 |
|---|---|---|
| 실행 개발 문서 v2 | `REFERENCE_ONLY` | 변경 금지 기준 문서 |
| Codex 마스터 프롬프트 v3 | `REFERENCE_ONLY` | 변경 금지 실행 지침 |
| 공식 모집요강·시행계획 원본 | `REFERENCE_ONLY` | Git 제외 `tmp/codex-reference/pdfs/`에서 읽기 전용 검증 |
| 학생 개인정보·업로드 원본 | `BLOCKED_SOURCE` | 저장소 반입 금지, 현재 미발견 |
| 공개 정제 전형 데이터 | `VERIFIED_SOURCE` | 기존 목록과 2026 원본 42개 대학·4,970행을 합친 최종 43개 대학, 검수 결과 4,094행·선택 기준 1,048개 학과/주야·2025 결과 482행·출처 manifest |

## Phase 0 완료 항목

- [x] 기존 Git 상태와 사용자 파일 확인
- [x] 두 기준 문서 원문 확인 및 충돌 검토
- [x] 개인정보·원본·파생 파일 잔존 검사
- [x] Git·Docker 제외 정책 구성
- [x] 공개 정제 데이터 경로 분리
- [x] 최소 Flask 앱 셸과 헬스체크 작성
- [x] 테스트와 민감자료 검사 통과
- [x] Git 변경 검토, 단일 커밋, 원격 push

## Phase 1 완료 항목

- [x] PostgreSQL 전용 SQLAlchemy 2.x 핵심 스키마와 Alembic 최초 migration
- [x] Flask-SQLAlchemy·Flask-Migrate 앱 팩토리 및 `flask db migrate/upgrade` 연동
- [x] 문서 혼합연도 게시 및 근거 없는 규칙 게시의 DB 제약 차단
- [x] 원적교·위탁기관 학생 성적 출처 분리
- [x] 임시 원본·파생물 세션 저장과 삭제 검증 서비스
- [x] PostgreSQL 17 `tmpfs` 통합 테스트 컨테이너
- [x] `make` 자동 실행 하네스와 Ruff·mypy·pytest 구성
- [x] 단위 7건·PostgreSQL 통합 7건·규칙·민감정보 검사 통과
- [x] 실제 학생 자료·원본·DB 파일 Git 포함 0건

## Phase 2 완료 항목

- [x] CSV·표 붙여넣기 표준 필드 정규화와 누락 보존
- [x] XLSX 복수 시트 및 앞부분 설명 행 이후 머리글 탐지
- [x] 동일 원본 SHA-256과 입력 크기·시트·행 제한
- [x] CSV·XLSX 학급표에서 대상 학생 외 행 제거와 과목 통계 추출
- [x] 교사 확인 행만 PostgreSQL 저장하고 원본·파생물 삭제 검증
- [x] 삭제 실패 시 DB transaction rollback과 명시적 오류
- [x] `P`를 0점으로 바꾸지 않는 원문 라벨 저장 제약
- [x] 텍스트 PDF의 페이지 비고정 교과 표 탐색과 페이지 trace
- [x] 세부능력 및 특기사항 원문 입력 제외
- [x] 암호화·무텍스트·과대 PDF 명시적 분기
- [x] PNG·JPEG signature와 크기·해상도 제한
- [x] 클립보드 이미지와 파일 이미지의 동일 로컬 OCR 계약
- [x] Tesseract 한국어·영어 로컬 OCR 및 교사 검수 필수 표시
- [x] 이미지형 PDF 페이지별 메모리 렌더링과 로컬 OCR
- [x] EOF 누락 등 경미 손상 복구 가능 시 처리
- [x] 암호화·복구 불가·렌더링 실패 PDF 명시적 거부
- [x] 교사 미리보기·행 수정·선택 확정 SSR 화면
- [x] JavaScript 없이 선택 행 확정·임시자료 삭제
- [x] CSRF·비공개 캐시·CSP와 원본 파일명 비표시
- [x] 데스크톱·모바일 Playwright 사용자 흐름 검증

## Phase 3 완료 항목

- [x] 학생에게 전형 유형을 배정하지 않는 사실 모델
- [x] 허용 필드·연산자·깊이·노드 수를 제한한 조건 DSL
- [x] `ELIGIBLE`·`CONDITIONALLY_ELIGIBLE`·`INELIGIBLE`·`NEEDS_REVIEW`·`INSUFFICIENT_DATA`
- [x] 누락 사실을 결격으로 바꾸지 않는 3값 조건 평가
- [x] 실제 사실값을 복사하지 않는 규칙 버전·조건 결과 trace
- [x] 비게시·근거 미승인 규칙 실행 차단
- [x] 자격 미확정 상태의 성적 계산 진입 차단 계약
- [x] 복수지원 규칙과 지원자격의 독립 판정
- [x] 민감 결격 규칙의 비영구 입력 계약
- [x] PostgreSQL 게시 규칙 조회·판정 서비스 연결
- [x] 전형별 활성 게시 규칙 단일 버전 DB 제약
- [x] 규칙 seed payload의 제한형 DSL 검증

## Phase 4 진행 항목

- [x] 자격 허용 상태 이전의 성적 조회·선택 차단
- [x] 여섯 성적 출처 범위 정책의 제한형 payload
- [x] 원적교·위탁기관 기록의 전형별 독립 선택
- [x] 교사 검증 완료 과목만 계산 후보로 선택
- [x] `P` 원문 라벨 비수치 보존
- [x] 선택 출처·학기·과목과 제외 이유 trace
- [x] 전형별 활성 성적 범위 규칙 단일 버전 DB 제약
- [x] 관리자 직접 편집과 CSV가 공유하는 canonical 성적 규칙 스키마
- [x] UTF-8/BOM 고정 CSV import/export와 엄격 헤더 검증
- [x] boolean·Decimal·빈값/0·중복키·수식형 셀 검증
- [x] 별도 `z_score_tables.csv`와 `z_score_table_code` 연결 계약
- [x] 전체·최초·최근·우수 N개 학기와 과목 선택
- [x] 학년·학기 가중치와 Decimal 계산·반올림·절사
- [x] 전역·학년 내부 학기 가중치와 학년별 우수학기 선택
- [x] 값 우선 방향·학기 중간 반올림·표시 자릿수 분리
- [x] 학년 평균 중간 반올림과 학년 가중치 적용 순서 분리
- [x] 버전 고정 Z점수 계산·경계 포함 여부·출처 trace
- [x] 제한형 선형 점수 환산과 성적 계산 규칙 단일 게시 버전 제약
- [x] 참고 XLSX 실제 수식과 합성 성적 10,601건 차등 검증
- [x] 성취도 분포 변환과 공식 출결 계산
- [x] 골든·속성 테스트와 계산 trace

### 참고 XLSX 차등 검증 판정

- 지원 수식 15종: 합성 학기 등급 500세트, 7,500건 일치
- 학기 이수단위 가중: 합성 과목·학점 2,500건 일치
- XLSX 참고 Z점수 경계: `-3.00`~`3.00` 0.01 간격 601건 일치
- 제외 수식: `대학별 등급!J18` 참조 범위 불일치, `J20` 우수학기·고정학기 혼합
- 근거 판정: XLSX 경계는 `VERIFIED_REFERENCE`; 대학별 공식 PDF 경계가 우선이며 자동 게시하지 않음
- 폴리텍 서울정수 2027: 학기 4자리·학년 2자리 반올림, 학년 30%·30%·40%, 교과 320점·출석 80점 합성 골든 일치
- 폴리텍 참고 XLSX: 가중치 구조는 일치하지만 중간 반올림 누락으로 정밀 경계값 불일치; 공식 PDF식 우선
- 결합 PDF 33~34쪽 서울정수, 67~69쪽 서울강서의 2026 입시결과를 캠퍼스별로 분리하며 2027 규칙으로 사용하지 않음

## Phase 6 진행 항목

- [x] 과거 입시결과 CSV·노트북·PDF 용도 분류
- [x] 노트북 네트워크·파일쓰기 코드 미실행
- [x] timeout·재시도·rate limit이 고정된 source adapter 계약
- [x] raw·staging·published PostgreSQL 단계와 migration
- [x] 업무키·혼합연도·중복·빈 키·행/페이지 급감 차단
- [x] 오류 batch 부분 게시 차단과 관리자 전체 행 승인
- [x] 과거 규칙 버전 고정과 현재 규칙 자동 재해석 금지
- [x] 게시 승인 결과 전용 분석 조회 서비스
- [x] Phase 6 전체 검증 및 게이트 `PASS`

## Phase 7 진행 항목

- [x] 게시 규칙을 직접 수정하지 않는 새 DRAFT 복제
- [x] payload 변경 전후 및 합성 표본 영향도 비교
- [x] 규칙 버전 계보·변경 사유·감사 로그 DB 계약
- [x] TESTED·근거·독립 검증·골든·명시적 사람 승인 게시 게이트
- [x] 관리자 해시 인증·CSRF·비공개 캐시 경계
- [x] JavaScript 없는 규칙 목록·상세·DRAFT 복제·승인·게시 SSR
- [x] CSV 신규·변경·동일·충돌·오류 분류와 선택 DRAFT 후보 계약
- [x] CSV 선택 DRAFT DB 저장과 SSR 미리보기
- [x] 관리자 브라우저 E2E·접근성 검증
- [x] 현재 성적 규칙 표준 CSV 내보내기
- [x] DRAFT canonical 규칙 직접 편집과 전형·근거 연결
- [x] Phase 7 최종 게이트 `PASS`

## Phase 8 진행 항목

- [x] 작업 카드와 자격 우선·규칙 버전·입시결과 비교 경계 확정
- [x] 단계형 학생 입력과 지원자격 우선 상담 흐름
- [x] 성적 계산·같은 연도/규칙 버전 입시결과 비교
- [x] 학생용·교사용 결과 및 A4 출력
- [x] Playwright·접근성·인쇄 검증
- [x] Phase 8 최종 게이트 `PASS`

## Phase 9 진행 항목

- [x] 비식별 고정 payload allowlist와 SHA-256 digest
- [x] 누락값과 숫자 0의 독립 직렬화
- [x] 자격·점수·합격 가능성 표현을 거부하는 공급자 중립 응답 계약
- [x] 사용자·공급자별 API 키의 Fernet 인증 암호화·마스킹·교체·삭제 서비스
- [x] 암호문 변조·잘못된 master key 차단
- [x] 생성 초안과 교사 수정·확정 상태의 분리 저장 계약
- [x] 관리자 인증·CSRF·비공개 캐시를 유지한 BYOK 설정·초안 검수 SSR
- [x] OpenAI·Gemini·Anthropic 실제 공급자 호출 어댑터
- [x] 상담 결과 SSR에서 관리자 소유 키로 검토용 초안 생성
- [x] 고정 엔드포인트·구조화 JSON·15초 timeout·64/128 KiB 제한·오류 은닉
- [x] OpenAI 운영 성공 smoke test(비식별 합성 payload)
- [x] Gemini·Anthropic 유료 실키 검증 제외 방침 확정(실제 성공 미주장, 합성 HTTP 계약 검증 유지)
- [x] PostgreSQL 통합·마이그레이션 drift·브라우저 E2E
- [x] Phase 9 최종 게이트 `PASS`

## Phase 10 진행 항목

- [x] 대상 대학 확대·운영 작업 카드
- [x] 백업 파일 권한·원자적 생성·실패 시 임시파일 정리
- [x] 백업·복구 런북과 읽기 전용 archive 점검 절차
- [x] Phase 10 이후 전체 회귀(단위 217건·통합 52건·정적·규칙·민감자료) 통과
- [x] 최신 문서 변경 후 단위 217건·lint·mypy·규칙·민감자료 재검증 통과
- [x] Docker API 권한 부여 후 통합 테스트 52건 통과
- [x] 2027학년도 공식 모집요강 후보 5곳 목록과 근거 대기 상태 점검
- [x] 1·2차 후보별 대학·모집시기·전형·핵심 페이지 교차검증과 근거 상태 분리
- [x] 2차 10곳 핵심 지원자격·반영학기·Z점수 페이지 대조와 시행계획/최종본 상태 분리
- [x] 인덕 결합 PDF의 2027 시행계획과 2026 모집요강 혼합연도 분리
- [x] 동서울 1~2학년 4개 학기 중 최우수 2개 학기로 사용자 정정·시행계획 일치 확인
- [x] 연성 시행계획의 위탁생 일반고 지원 가능에서 최종 모집요강의 지원 불가로 변경된 출처 버전 충돌 확인
- [x] 합성 시행계획을 최종 모집요강 새 버전으로 교체하는 계보·영향도·이전 payload 보존 회귀 테스트
- [x] 합성 회귀 실행시간 기준선 기록 (운영 쿼리 관찰 지표는 후속)
- [x] 합성 BYOK 보안 테스트 및 리허설 절차 문서화 (실제 운영 회전·삭제는 보류)
- [x] 합성 데이터 교사 검토 흐름 테스트
- [x] 독립 알파 앱·PostgreSQL 컨테이너 기동, migration `head`, healthcheck
- [x] 알파 관리자 Playwright smoke 3건 통과
- [x] 합성 상담 seed 기반 알파 컨테이너 Playwright 8건 통과(검수 세션 전용 3건 skip)
- [x] OpenAI 키 인증과 비식별 `gpt-4.1-mini` 구조화 응답 알파 smoke
- [x] 독립 베타 Gunicorn·PostgreSQL 컨테이너와 migration·healthcheck
- [x] 베타 상담·BYOK·A4 Playwright 8건과 업로드 검수 Playwright 3건 통과
- [x] 베타 env-file 해시 보존과 합성 DB 저장 흐름 검증
- [x] 운영 시작 전 secret·PostgreSQL·HTTPS·신뢰 호스트·proxy fail-closed 계약
- [x] secure session cookie와 비밀값 비출력 `production-preflight`
- [x] 파일 기반 secret 주입과 충돌·빈값·다중행·과대 파일 fail-closed 검증
- [x] 합성 Nginx TLS·Gunicorn·PostgreSQL production 후보와 migration `head`·healthcheck
- [x] 합성 HTTPS 보안 헤더·HTTP redirect·관리자/상담/BYOK/A4 Playwright 8건 통과
- [x] 합성 OCR 업로드 검수 데스크톱·모바일·무JavaScript Playwright 3건 통과
- [x] Cloudflare/호스트 Nginx 원본 연결을 `127.0.0.1:8000`으로 제한하고 외부 직접 노출 차단
- [x] Flask 개발 서버 대신 호스트 Nginx 뒤 Gunicorn을 사용하는 production origin override 준비
- [x] Phase 10 최종 게이트 `PASS_NONPROD`(실제 운영 전환 별도 보류)
- [x] live 전용 PostgreSQL·업로드 named volume 생성과 Alembic `head` 적용
- [x] 웹 컨테이너 비root 실행, `0600` secret 읽기 및 `0700` 업로드 볼륨 권한 확인
- [x] 원본 포트 `127.0.0.1:8000`, 호스트 Nginx·Cloudflare 공인 HTTPS health 및 보안 헤더 확인
- [x] 실제 HTTPS 관리자 로그인·CSV 오류 처리·모바일·무JavaScript Playwright 3건 통과
- [x] live custom-format 백업·SHA-256·archive 목차 검증
- [x] live network·volume·secret과 분리된 network-none/tmpfs PostgreSQL 복원 검증
- [x] 복원 DB Alembic `e51f0b24c8aa`와 공개 스키마 35개 테이블 확인
- [x] 쿼리 원문·bind 값 없는 PostgreSQL 17 읽기 전용 집계 기준선 수집
- [x] 규칙의 전체 감사 생명주기·시각 순서와 동일 검수 ID 재검증
- [x] payload와 규칙·전형·citation·문서·승인 페이지·파일 hash의 계약 digest 결속
- [x] 승인 페이지·제한형 DSL·독립 `RuleReview`의 승인·게시·실행 시 재검증 구현
- [x] archive basename·원본 migration·`TABLE DATA` 수를 결속한 checksum·manifest 구현
- [x] 신규 head PostgreSQL 통합·migration drift·합성 sentinel 격리 복원 재검증
- [x] `Institution`·`Campus` canonical code와 ScoreRule 업무키 일치 검증
- [x] 독립 검수·payload·계약 버전·합성 suite·case 집계에 결속된 골든 artifact 저장
- [x] 8개 규칙 테이블의 `(golden_test_ref, rule_id, golden_test_rule_type)` 3열 FK·고정 유형 CHECK와 삭제 `RESTRICT`
- [x] 관리자 TESTED 자유 입력 제거 및 유효한 PASSED artifact 선택
- [x] legacy 임의 참조 upgrade·증거 포함 downgrade의 데이터 손실 차단

## Phase 11 완료 항목

- [x] live PostgreSQL custom-format 백업·checksum·archive·network-none/tmpfs 복원 재확인
- [x] 기존 8개 규칙 테이블 `golden_test_ref` 합계 0건 확인
- [x] 운영 백업 복제본에서 `e51f0b24c8aa → f76a91c3d2e8 → 0d9f4a7c2b11 → 6c1a2e9f4b73` migration 통과
- [x] 기존 live 이미지 불변 ID와 `rollback-pre-0d9-0cc429511fca` Docker 태그 확보
- [x] 로컬 교직원 가입과 기존 계정 존재 여부를 노출하지 않는 동일 접수 응답
- [x] 모든 신규 로컬·Google 계정의 `MEMBER/PENDING_APPROVAL` 강제
- [x] `ADMIN` 전체 회원·설정 관리, `ASSISTANT_ADMIN` 대기 일반 회원 승인 전용 관리 권한
- [x] 마지막 활성 관리자 강등·정지 차단과 역할·상태 변경 감사 기록
- [x] stale ORM identity 재적재, 일관된 row-lock 순서, 동시 승인·관리자 bootstrap 검증
- [x] 기존 환경변수 관리자 username 기반 `actor_ref`와 과거 검수·AI 소유권 호환
- [x] 상태·비밀번호 변경 세션 무효화와 SQLAlchemy parameter 비노출 503 처리
- [x] Google Discovery/JWKS·state·nonce·PKCE S256·검증 이메일·canonical issuer/sub 식별
- [x] OAuth token/code 미저장과 query 없는 앱·컨테이너 Nginx/Gunicorn 로그 계약
- [x] 컨테이너 Nginx의 callback 포함 모든 공개 인증 진입점 rate limit과 DB 복원·image ID·구버전 bootstrap 생략·`--no-build` 롤백 게이트
- [x] 승인 전 상담·검수·계산 차단과 검수 세션 소유자 경계
- [x] 외부 Tailwind 실행 제거와 로컬 CSS·비공개 캐시·CSP 적용
- [x] 정적·단위·PostgreSQL 통합·migration drift·규칙·민감자료 검사 통과
- [x] 합성 alpha 최종 이미지 health·migration head와 무JavaScript Playwright 2건 통과
- [x] Phase 11 최종 게이트 `PASS_NONPROD_PHASE_11`

직전 배포 기준선은 정적 검사·단위 248건·PostgreSQL 통합 53건·규칙·민감자료 검사와 실제 공인 HTTPS 관리자 smoke 3건을 통과했다. live DB와 기존 백업의 migration은 `e51f0b24c8aa`이며, 현재 작업 트리의 신규 head `6c1a2e9f4b73`과 회원 승인 코드는 아직 배포하지 않았다.

현재 작업 트리는 정적 검사·mypy·단위 273건·PostgreSQL 통합 112건·규칙·민감자료 검사와 합성 PostgreSQL 백업·격리 복원을 통과했다. 기존 관리자 username을 불변 `actor_ref`로 유지해 과거 검수·AI 소유권을 보존하고, 신규 계정은 UUID namespace를 사용한다. 합성 secret과 고유 port·network·volume만 사용한 최종 알파 image는 migration head `6c1a2e9f4b73`, health, 무JavaScript 회원가입→승인→로그인과 보조관리자 403 Playwright 2건을 통과했고 합성 자원을 제거했다. live 백업 복제본에서도 전체 신규 migration 체인과 `golden_test_ref=0` 유지가 확인됐다. 현재 변경은 `PASS_NONPROD_PHASE_11`이며 live DB·배포에는 적용하지 않았다. Google OIDC는 기본 비활성화 상태로, 실제 활성화 전 호스트 Nginx callback query 로그와 공개 로그인·가입 rate limit을 별도 운영 게이트로 처리한다. 공식 대학 규칙 게시 수는 계속 0건이며 AI는 `HUMAN_APPROVED` 또는 게시 상태를 설정하지 않는다.

## Phase 12 완료 항목

- [x] 관리자 전용 대학·캠퍼스·학과·모집시기·전형 기준정보의 JavaScript 없는 등록·즉시 조회 SSR
- [x] 상위 참조·전형의 대학 일치·중복·누락·ASCII 코드 검증과 DB 오류 원문 은닉
- [x] 비로그인·일반 회원 권한 차단, CSRF 보호, 오류 뒤 불필요한 재조회 방지
- [x] 기준정보 등록과 공식 규칙·상담 대상 게시의 분리 유지
- [x] 공개 합성 데모의 권한 오염 차단, 환경 제거 시 revoke, 선점 충돌 비치명·비탈취 처리
- [x] 데모 자격증명 DB 일치 렌더와 구이미지 롤백 fail-closed 검증
- [x] 독립 보안 검증 `APPROVE`

Phase 12 회귀는 단위 290건, PostgreSQL 통합 127건과 합성 백업·격리 복원, 규칙 검증, 민감자료 검사를 통과했다. Playwright는 데스크톱과 390px JavaScript 비활성 환경에서 비로그인·일반 회원·관리자 경계와 대학→캠퍼스→학과→모집시기→전형 5단계 등록을 확인했고, PostgreSQL에 두 세트 각 5종이 저장되며 관련 게시 규칙은 0건임을 검증했다. 브라우저 console·page error는 0건이었다.

`make lint`는 작업 트리를 변경하지 않았고 Phase 12 허용 범위 밖인 `scripts/check_google_oidc_https.py`, `scripts/check_production_https.py`의 import 정렬 2건 때문에 실패했다. 이 검사는 성공으로 기록하지 않는다.

구현 커밋 `a55e679a90492c431f7b7dff680f3b8099307b59`는 `main`과 `origin/main` 이력에 동기화했으며, 운영 결과는 후속 문서 커밋에 반영했다. 운영 직전 `backups/production/admission_20260718_120856_3870618.dump`를 생성해 SHA-256 `6f05d0a890bde0d82ba1b6360918ba61022177c66400bc9644af80ec033e58e2`, archive, network-none/tmpfs 격리 복원을 검증했다. 이전 이미지는 `sha256:0cc429511fca2a8b99d24986f111eaf287242714070e1ff39b8633cf9f4a2466`과 `rollback-f0ef03c-20260718` 태그로 보존했다.

신규 이미지 `sha256:5106fec82bbe9f703cd615312bde5671fd38855b50acab19884a95048cc0d6c2`로 web을 교체하고 live DB를 `e51f0b24c8aa → 6c1a2e9f4b73`으로 적용했다. Docker health, `127.0.0.1:8000` loopback, origin/public health, Cloudflare HTTPS, HTTP redirect, TLS, CSP·HSTS·nosniff·frame·referrer 헤더, host Nginx 설정과 active 상태를 확인했다. 운영 Playwright 3건과 Phase 12 비파괴 smoke에서 관리자 catalog 5개 SSR 폼·친화적 400 오류·모바일·무JavaScript, 비로그인 redirect, 데모 MEMBER 합성 상담·catalog 403, console/page error 0건을 확인했다. 최근 web·전용 Nginx 로그의 5xx·fatal·query·비밀값·학생 PII 패턴은 0건이다.

합성 기준정보를 live DB에 남기거나 삭제하지 않기 위해 운영에서는 성공 등록을 수행하지 않았다. 실제 5단계 저장은 격리 PostgreSQL E2E로, live에서는 동일 이미지·migration의 조회와 비파괴 오류 경로로 검증했다. live catalog 5종과 공식 게시 규칙은 모두 0건이며 Google OIDC는 비활성 상태다.

## Phase 14 완료 항목

- [x] 로그인 없는 빈 성적표·수정 가능한 합성 예시·표 붙여넣기·CSV/XLSX 입력 시작점
- [x] 5개 기본 학기 그리드, 행별 성적 출처·위탁학기, `0`·빈 값·`P` 분리와 Z점수 fail-closed
- [x] 원본 삭제 후 수정 가능한 검수 화면, 대학 선택·결과에서 같은 임시 입력으로 되돌아가기
- [x] 실제 4개 대학·캠퍼스·학과·모집시기·전형 기준정보와 공개 2025 결과 482행
- [x] 전형별 지원자격 우선 판정, 지원 가능한 `VERIFIED_SOURCE` 전형만 계산
- [x] 동양미래대·인하공전·연성대 실행 규칙, 명지전문대 비위탁 범위 실행·위탁 `NEEDS_REVIEW`
- [x] 인하공전 공식 Z점수 경계·등급 환산 trace와 누락·표준편차 0 fail-closed
- [x] 관리자별 `VERIFIED_SOURCE` 규칙 최종확인과 규칙 digest 변경 시 확인 무효화
- [x] 선택 학기·과목·이수단위·중간값·가중치·반올림·제외 이유·근거 페이지 trace
- [x] 학생용·교사용 별도 A4와 저장 시점 학생·교사 로그인 경계
- [x] 학생 자기 자료, 교사 관리 자료의 소유권 기반 저장·전체 필드 수정·조회·삭제
- [x] 관심 대학·학과, 계산 결과, 학생용·교사용 출력 snapshot, 교사 메모·상담 이력 저장
- [x] CSV/XLSX 시트·머리글 자동 탐지, canonical 정규화, 오류·중복·미매핑 미리보기
- [x] 결과연도와 상담연도 분리, 2027 결과→2028 기본 제안·관리자 수정·게시
- [x] 데이터셋 `STAGED`·`READY`·`PUBLISHED`·`SUPERSEDED`·`BLOCKED`와 해시 중복 식별
- [x] 기준 XLSX 1,818+1,652=3,470행 import 대조, 학생 성적 시트·계산 보조열 제외
- [x] 기준 XLSX 지원 수식 대표 11종 일치, `J18`·`J20` 공식 자동 게시 차단
- [x] 비파괴 migration과 기존 사용자·상담·PostgreSQL volume 보존 계약
- [x] 독립 Chromium 검증: 공개 흐름 3건, 관리자 import 2건, 무JavaScript·390px·A4·오류 0건
- [x] 단위 337건, PostgreSQL 통합 140건·격리 백업/복원, lint·mypy·규칙·민감자료 검사

### 기준 XLSX 대응

| XLSX 시트 | Phase 14 화면·서비스 |
|---|---|
| `성적 입력` | 공개 성적 그리드·붙여넣기·업로드·검수 임시 세션 |
| `대학별 등급` | 출처 버전이 있는 제한형 실행 규칙과 계산 trace |
| `2025 수시(1차) 결과` | canonical import 1,818행과 상담 비교 자료 |
| `2025 수시(2차) 결과` | canonical import 1,652행과 상담 비교 자료 |

동양미래대학교 호텔관광학과 대표 흐름에서 합성 예시의 첫 성적을 수정한 결과는 1.71등급이었고, `영어Ⅰ` 석차등급을 1에서 9로 바꾸면 2.00등급으로 변경됐다. 같은 화면에 2025 평균 5.7000, 최저 6.3000, 경쟁률 8.4000, 모집인원 47과 계산 trace가 표시됐다. 공식 범위가 확인되지 않은 전형은 가상 산식 대신 `계산 기준 준비 중` 또는 `NEEDS_REVIEW`로 표시한다.

익명 입력은 계정 학생 성적 테이블에 저장하지 않고 새 계산·완료 시 즉시 삭제하며 production 앱의 5분 주기 정리 loop가 30분 만료 자료를 트래픽 없이도 삭제한다. 학생은 본인 소유 자료만, 교사는 자신이 관리하는 자료만 다루며 관리자는 회원 승인·공개 데이터 import·규칙 최종확인을 담당한다.

### Phase 14 운영 배포

- Compose 프로젝트: `junior-college-admission-live`; `web-production`만 재빌드·재생성했으며 `db-production` 컨테이너와 PostgreSQL volume은 유지했다.
- 배포 전 백업: `admission_20260719_015836_2852233.dump`, SHA-256 `49a88630e5ab6629f222b7198ddd42e7e49c878f81b1c76826f984f6f216b44a`; archive 검사와 network-none/tmpfs 격리 복원 통과.
- migration: `6c1a2e9f4b73 → 2f8a4c6e91d3 (head)`; 기존 계정 2건과 학생 성적 0건을 보존했다.
- rollback 이미지: `sha256:7e9f1d0e130c8d9131dadcdaeb683520409c7269775f8aea1162630d9603a3d1`; 최종 이미지: `sha256:74edf6f9e007cfc70c5f1ff58f4a2177ebee40a902b8768d8928fbfdd83ae19c`.
- 첫 재빌드에서 새 파일의 런타임 읽기 권한이 부족해 health가 실패했다. 성공으로 기록하지 않고 Dockerfile에 공개 seed 포함과 비루트 읽기 권한을 명시한 뒤 재빌드해 `healthy`를 확인했다.
- 운영 공개 dataset: 2025 결과·2027 상담 대상, `PUBLISHED 482/482`; 대학 4곳·학과 128개이며 기존 원본이나 학생 성적 시트 값은 게시하지 않았다.
- `https://admission.memilmuk82.com`에서 TLS·health·보안 헤더, loopback health, 공개 Chromium 3건, JavaScript 비활성, 390px, 학생·교사 A4, 결과 변화 `1.71→2.00`, 완료 후 임시 세션 404 삭제와 console/page error 0건을 확인했다.
- 운영 관리자 자격으로 import SSR 화면 접근을 비밀값 출력 없이 확인했다. CSV/XLSX 게시 변경은 격리 PostgreSQL Playwright 2건으로 검증해 live에 합성 dataset을 추가하지 않았다.
- 최종 웹 로그에서 5xx·traceback·fatal 패턴은 0건이며 DB와 웹 컨테이너가 모두 `healthy`다.

## Phase 15 완료 항목

- [x] `/`에서 로그인 없는 2027 공개 상담으로 바로 진입하고 성적 우선·대학 검색 우선 시작점 통합
- [x] 고정 학생군 조건의 중복 입력 제거와 대학·학과 검색·필터·비교 선택, 사람 친화적 결과 상태로 UI 재구성
- [x] 핵심 흐름의 JavaScript 비의존 SSR과 학생용·교사용 A4 경계 유지
- [x] 학생 저장 상담의 원본 보존 복제, 개인 BYOK 설정·초안 조회·소유자 삭제 연결
- [x] 교사·관리자 전용 비식별 교내 지원 결과 등록·필터·집계·CSV 내보내기
- [x] 공식 공개 데이터와 교내 관찰 결과의 테이블·조회·공개 경계 분리
- [x] 관리자 근거 문서 업로드·hash 중복·버전 current 관리와 현재값/포털값/문서값 비교·검증 결정
- [x] 기존 전문대학포털 노트북의 POST·15열 표 계약을 timeout·재시도·rate limit·크기 상한이 있는 어댑터로 재사용
- [x] 포털 응답을 기존 raw 수집·staging·관리자 review/publish 흐름에 연결하고 자동 게시 금지
- [x] 기존 migration `2f8a4c6e91d3` 위 비파괴 Phase 15 migration과 PostgreSQL 모델 계약 검증
- [x] 새 Python·Node·시스템 의존성 없이 기존 Flask·Jinja2·SQLAlchemy·requests·openpyxl·pypdf·Pillow 재사용
- [x] 데스크톱·390px·JavaScript 비활성 공개 핵심 흐름과 결과 변화 `1.71→2.00`, A4, console/page error 0건 확인

### Phase 15 운영 배포

- 구현 커밋 `5a8036b`을 `origin/main`에 push했으며 로컬·원격 SHA 일치를 확인했다.
- 배포 전 백업 `admission_20260719_221535_1739324.dump`의 SHA-256 `a46eab1ed42b96710aa4f5493a4b445d1abf611e6d25e2e224c6dcf5a349072d`, archive와 network-none/tmpfs 격리 복원을 검증했다.
- `junior-college-admission-live`의 기존 `db-production` 컨테이너와 PostgreSQL·업로드 volume을 유지하고 `web-production`만 재빌드·재생성했다.
- migration은 `2f8a4c6e91d3 → 4a7c9e12d5f0 (head)`로 적용했고, 이전 이미지 `sha256:74edf6f9e007cfc70c5f1ff58f4a2177ebee40a902b8768d8928fbfdd83ae19c`를 rollback 태그로 보존했다.
- 최종 이미지는 `sha256:a2a04b05fd56f83c73b93c139d1d9261fb9d751cd79f9b8a93a4959599c3db9b`이며 웹·DB 모두 `healthy`다.
- loopback origin과 공인 HTTPS health·보안 헤더를 확인하고, 운영 Chromium에서 합성 익명 계산 `1.71→2.00`, 학생·교사 A4, JavaScript 비활성 SSR, 390px 모바일 3건을 통과했다.
- 전문대학포털 전체 네트워크 수집과 DNS·Cloudflare·호스트 Nginx 변경은 수행하지 않았다. 사용자 작성 파일 `codex_cli_admission_refactor_prompt.md`, `run_admission_codex_background.sh`는 수정·커밋하지 않고 보존했다.

## Phase 16 검증 완료 항목

- [x] `/account/records`의 공유 데모 403 제거와 계정 로그인 경계 복구
- [x] 기준 XLSX의 1-1~3-1 다섯 학기·학기당 10행·총 50과목 구조에 맞춘 성적 입력 그리드와 서버 한도·수정 가능한 합성 예시 복구
- [x] 선택되지 않던 임시 대학 선택 UI 제거, 서버 POST 기반 대학·학과 선택과 성적 상태 동기화
- [x] 학생·교사·보조 관리자·주 관리자별 업무 대시보드와 서버 권한 일치
- [x] 학생 개인 BYOK 분석, 교사 BYOK 상담자료 저장과 사용자별 암호화 키 격리
- [x] 교사의 학과·학급·비식별 학생·성적 관리와 학생의 명시적 전체 자료 공유 동의
- [x] 24시간 만료·원문 미저장·일회 사용 연결 코드와 연결/해제/정지/역할 변경 감사 이력
- [x] 연결 중 양방향 성적·학생용 상담 읽기와 상대방 자료 수정·삭제·복제 차단, 학생의 교사용 A4·상담 메모 비노출, 해제 즉시 공유 중단
- [x] 보조 관리자의 승인 대기 계정 승인 전용 경계와 주 관리자의 역할·입시결과·제한형 수집·근거 문서 관리
- [x] 손상 PDF/XLSX·malformed OOXML의 400 처리와 주 관리자 PDF·PNG·JPG·CSV·XLSX 업로드 경계
- [x] JavaScript 없는 생성·연결·성적 추가 흐름, 390px 가로 넘침 없음, 브라우저 오류 0건
- [x] 단위 342건, PostgreSQL 통합 159건과 합성 백업·격리 복원, Phase 16 Playwright 3건 통과
- [x] Ruff·포맷·mypy 146개 소스·규칙·민감자료·기준 XLSX 읽기 전용 검증 통과
- [x] 운영 custom-format 백업·archive·checksum·격리 복원 검증
- [x] 기존 DB·volume 보존, `web-production`만 재빌드하고 migration·공인 HTTPS 확인

사용자 작성 파일 `codex_cli_admission_refactor_prompt.md`, `run_admission_codex_background.sh`는 Phase 16 변경 범위에서 제외해 수정·커밋하지 않는다. 실제 학생 자료나 원본 XLSX/PDF는 Git에 추가하지 않았고 테스트는 합성 비식별 자료만 사용했다.

### Phase 16 운영 배포

- 구현 커밋 `5fbe150`을 `origin/main`에 push하고 로컬·원격 SHA 일치를 확인했다.
- 배포 전 백업 `admission_20260720_080035_3225129.dump`의 SHA-256 `12fdcd743b5fa1b8923d50b69093625ec419ac4fa5165648e9aadfb75493029a`, archive와 network-none/tmpfs 격리 복원을 검증했다. 복원 source migration은 `4a7c9e12d5f0`, 저장소 head는 `8e31b7c4d2a6`, 공개 테이블은 45개였다.
- 이전 웹 이미지 `sha256:a2a04b05fd56f83c73b93c139d1d9261fb9d751cd79f9b8a93a4959599c3db9b`를 `junior-college-admission-production-app:rollback-phase16-5fbe150-20260720`으로 보존했다. schema 변경 뒤 image-only rollback은 수행하지 않는다.
- 기존 `db-production` 컨테이너 ID와 `production_postgres_data`·`production_uploads` volume 이름을 전후 대조해 그대로 유지했고, `web-production`만 최종 이미지 `sha256:378fa56bcfe8d8f29a871301a864d84062df3d66a03d97bbb6c95d6d06e22bbb`로 교체했다.
- live migration을 `4a7c9e12d5f0 → 8e31b7c4d2a6 (head)`로 적용했고 웹·DB가 모두 `healthy`, 웹 restart 0건이다. 새 학급·연결·감사 테이블은 합성 운영 데이터를 만들지 않아 각각 0건이다.
- loopback·공인 HTTPS TLS/health/보안 헤더, 공개 `/calculate` 200과 기준 50칸, 비로그인 `/account/records`·`/dashboard` 302를 확인했다. 실제 주 관리자 비파괴 Chromium 3건에서 새 대시보드 메뉴, 규칙 CSV 검증, 390px, JavaScript 비활성 SSR과 console error 0건을 확인했다.
- 배포 시점 이후 web 로그의 5xx·traceback·fatal·critical·unhandled·exception 패턴은 0건이다. 실제 학생·교사 계정이나 학급·성적·상담 합성 자료는 운영 DB에 추가하지 않았다.

## Phase 17 배포 전 검증 완료 항목

- [x] 공개 상담 기본값을 직업위탁 재학생으로 고정하고 일반고 졸업생만 명시적 예외로 제공
- [x] 1·2학년은 원적교, 기본 학생의 3학년은 위탁기관 성적으로 서버에서 확정해 화면의 성적 구분 드롭다운 제거
- [x] 3학년 2학기 10칸을 포함한 6개 학기·60칸 입력과 3-2 전체 공란 상태의 검수·대학 선택·계산 허용
- [x] 일반고 졸업생 프로필의 입력→검수→계정 상담 저장→DB→복제 전 구간 보존
- [x] 확정 `INELIGIBLE` 전형을 공개 결과에서 제외하고 규칙·근거가 없는 전형은 계산하지 않은 채 `계산 기준 준비 중`으로 표시
- [x] 사용자 제공 공개 CSV 4,970행·42개 대학을 모두 선택 기준정보로 보존하고 기존 동양미래대를 합친 최종 43개 대학과 주야·지역을 구분한 1,048개 학과를 개별 검색·선택 가능하게 연결
- [x] 점수 척도·범위를 검수한 2026 결과 4,094행을 기본 연도로 게시할 seed와 idempotent CLI 작성, 2025 결과 482행 보존
- [x] 점수 기준 누락 572건·범위 오류 308건으로 876개 원본 행을 제외하고 두 사유가 겹친 4행과 함께 0 또는 범위 밖 값을 임의 보정하지 않은 audit 기록
- [x] `demo-student`·`demo-teacher`·`demo-main-admin`·`demo-assistant-admin` 네 공개 데모 계정과 역할별 대시보드·로그아웃 제공
- [x] 기존 `demo:public` 계정이 새 고정 로그인 ID를 보유한 운영 상태에서도 실제 계정 선점과 구분해 legacy만 안전하게 퇴역시키는 전환 회귀
- [x] `/account/records`의 로그인·가입 `next` 보존과 로그인 상태의 계정 메뉴·로그아웃 navigation 복구
- [x] 데모 주 관리자는 운영 회원·원문·규칙·입시결과를 변경할 수 없는 읽기 전용, 데모 보조 관리자는 승인 요청 목록만 확인하는 경계
- [x] 실제 학생·교사 BYOK 키의 actor별 암호화·마스킹·교체·삭제와 데모 브라우저 세션별 격리·로그아웃 삭제
- [x] AI 저장 payload v3에 2026 참고결과를 고정하고 기존 v2 저장 상담의 목록·인쇄 호환 유지
- [x] 대학·학과 검색은 전체 1,048개 대상을 유지하되 한 번의 계산 요청은 서버·JavaScript·무JavaScript 모두 최대 5개로 제한
- [x] Phase 16 DB 4개 대학·128개 학과·2025 결과 482행을 넣은 PostgreSQL에서 migration upgrade 후 전 행 보존과 새 분류값 변환 검증
- [x] 단위 361건, PostgreSQL 통합 180건과 합성 백업·격리 복원, Phase 17 Playwright 6건, Phase 14 공개 회귀 3건 통과
- [x] Ruff·포맷·mypy 151개 소스, 규칙·민감자료·공개 seed byte 재현성 검사 통과
- [x] `.env.local` OpenAI 키는 출력·저장 없이 비식별 합성 요청 검증에만 사용했고 `gpt-4.1-mini` 응답 계약 확인 후 폐기

공개 원본 `tmp/codex-reference/csv/result2026 (2).csv`는 603,788 bytes, SHA-256 `f8577f1e58dbcaa2d2e1bc11ea4ff68641f5e506466ab8d61c49c2ce65c3e8cd`이며 Git에 추가하지 않는다. 파생 catalog·result·audit의 SHA-256은 각각 `f45c3eedf7b41208bf4c25023dfdac657d6048bed5c0518c8eb874dd7e2a0d81`, `6546aedfd3aac0f4e051713f14aaaa3919d0b17b5060ec909be53fa3ac62215f`, `ddad414bee800ee3ed5ae650151febbb6a86260a645d24209ea503d74df3b42d`다. 사용자 작성 파일 `codex_cli_admission_refactor_prompt.md`, `run_admission_codex_background.sh`도 계속 수정·커밋하지 않는다.

### Phase 17 운영 배포

- 구현 커밋 `fd2e506`과 legacy 데모 전환 보완 커밋 `4399ece`를 `origin/main`에 push하고 각 시점의 로컬·원격 SHA 일치를 확인했다.
- 배포 전 백업 `phase17_predeploy_20260720_104018.dump`의 SHA-256 `2cd642771cfa1be288e386919985e5e303ff28d6087c6adf3665b3dc91180aa2`, archive와 network-none/tmpfs 격리 복원을 검증했다. 복원 source migration은 `8e31b7c4d2a6`, 저장소 head는 `b6f1e8a42c73`, 공개 테이블은 48개였다.
- 이전 웹 이미지 `sha256:378fa56bcfe8d8f29a871301a864d84062df3d66a03d97bbb6c95d6d06e22bbb`를 `junior-college-admission-production-app:rollback-phase17-fd2e506-20260720`으로 보존했다. schema 변경 뒤 DB 복원 없는 image-only rollback은 금지한다.
- 기존 DB 컨테이너 `072f1a30e7d5...`와 `junior-college-admission-live_production_postgres_data`·`junior-college-admission-live_production_uploads` volume을 유지하고 웹만 컨테이너 `b425d2f94758...`, 이미지 `sha256:0c8029b75788db7fc6a399a0270d2f452fbaef10db8cabdafbf60097f5632b3c`로 교체했다. DB·웹은 `healthy`, restart 0건이다.
- live migration을 `8e31b7c4d2a6 → b6f1e8a42c73 (head)`로 적용하고 idempotent seed를 실행했다. 운영 기준정보는 대학 43·캠퍼스 45·학과 1,079개이며 게시 결과는 2025 482행, 2026 4,094행이다. 2026 척도별 수는 석차등급 3,562·수능등급 208·점수 324행이다.
- 기존 실제 비데모 계정 1건을 보존했다. 네 고정 역할 데모는 모두 `ACTIVE`, legacy `demo:public`은 `SUSPENDED`이며 운영 E2E 종료 후 데모 세션 BYOK credential·초안은 각각 0건이다.
- loopback과 공인 HTTPS의 TLS·health·보안 헤더, host Nginx active·설정 문법을 확인했다. 운영 Chromium은 Phase 17 6건과 Phase 14 회귀 3건을 통과했고 로그인 20회/분 정책을 존중하는 간격, JavaScript 비활성, 390px, console/page error 0건을 검증했다.
- 운영 스크린샷 8장을 직접 확인해 성적 입력·대학 선택·2026 결과·일반고 예외·관리자 읽기 전용·BYOK 마스킹·모바일 배치 이상이 없음을 확인했다. 배포 뒤 web·DB 로그의 5xx·traceback·fatal·critical·unhandled 패턴은 0건이다.

## Phase 18 배포 전 검증 완료 항목

- [x] 활성 비데모 주 관리자를 교사 기능까지 가진 상위 역할로 정의하고 보조 관리자는 승인 업무만 유지
- [x] 주 관리자 대시보드에 회원·입시자료 관리와 학급·학생 성적·상담·BYOK 메뉴를 함께 제공
- [x] 주 관리자 소유 학급 생성, 비식별 학생 추가, 일회용 코드 학생 연결과 상호 자료 공유 범위 적용
- [x] 주 관리자 공개 계산 성적·상담 저장과 교사 관리 소유권·상담 메모 적용
- [x] `TEACHER ↔ ADMIN` 역할 전환의 학급 연결 보존과 비교사 역할·비활성 전환의 기존 연결 폐기
- [x] 공개 데모 주 관리자의 교사 화면·unsafe POST·BYOK 차단 유지
- [x] 실제 주 관리자 actor 범위의 기존 Fernet BYOK 암호화·마스킹·교체·삭제 계약 재사용
- [x] 단위 361건, PostgreSQL 통합 191건과 합성 백업·격리 복원 통과
- [x] Ruff·포맷·mypy 151개 소스와 독립 권한 diff 감사 통과, HIGH·MEDIUM 문제 없음
- [x] 실사용 계정 로그인→관리자·교사 메뉴→학급 GET→OPENAI 마스킹→관리 화면→로그아웃 운영 Playwright 작성

Phase 18은 단일 `role` 스키마를 변경하지 않고 비데모 `ADMIN`에 교사 capability를 포함한다. 공개 데모 `ADMIN`은 capability에서 제외하고 전역 데모 요청 차단도 유지한다. 실제 운영 계정은 교사 가입→기존 주 관리자 승인→주 관리자 승격의 감사 이력을 남기고, 사용자 제공 OpenAI 키를 출력·로그·임시파일 없이 해당 계정 actor에만 암호화 저장한 뒤 공인 HTTPS로 검증한다.

### Phase 18 운영 배포

- 구현 커밋 `8f101f8`을 `origin/main`에 push하고 로컬·원격 SHA 일치를 확인했다.
- 배포 전 백업 `admission_20260720_113828_3857650.dump`의 SHA-256 `4e8064f4874246fe1d5883555bc449c230909e64b95303f2c3b6880c6c3b6ab7`, archive와 network-none/tmpfs 격리 복원을 검증했다. source와 repository migration은 모두 `b6f1e8a42c73`, 공개 테이블은 48개였다.
- 기존 DB 컨테이너 `072f1a30e7d5...`와 PostgreSQL·upload volume을 그대로 유지했다. 기존 웹 이미지 `sha256:0c8029b75788db7fc6a399a0270d2f452fbaef10db8cabdafbf60097f5632b3c`를 rollback 태그로 보존하고 웹만 컨테이너 `95e773e062ea...`, 이미지 `sha256:6fa832729850500104c73c36349f303520a3362f4a0bbc31b8caa4374f7f1062`로 교체했다.
- 교사 가입→기존 주 관리자 승인→주 관리자 승격의 감사 이력을 가진 실사용 계정 1건을 추가했다. 운영 활성 비데모 주 관리자는 2건이며 새 계정의 교사 capability를 확인했다.
- 사용자 제공 OpenAI 키를 stdout·argv·환경변수·임시파일·로그에 기록하지 않는 stdin 파이프로 전달해 새 계정 actor에 Fernet 암호문 1건으로 저장했다. 저장 직후 암호문 비동일·복호화 일치 boolean을 확인했고 문서에는 키·마스킹 끝자리·임시 비밀번호를 남기지 않았다.
- 공인 HTTPS Phase 18 Chromium 1건에서 로그인, 주 관리자·교사 카드, 학급 추가 폼, OPENAI 마스킹과 원문 DOM 부재, 회원·근거자료 관리, 로그아웃을 확인했다. 세 화면을 직접 검토했고 console/page error는 0건이었다.
- TLS·health·보안 헤더, migration `b6f1e8a42c73 (head)`, DB·웹 health와 restart 0건을 확인했다. 배포 이후 로그에 HTTP 5xx·traceback·fatal·critical·unhandled·exception·키 패턴은 0건이다.

최종 판정은 `PASS_PRODUCTION_PHASE_18`이다.

### Phase 18 로그인 403 후속 보완

- 사용자 브라우저에서 `/auth/login` 화면을 연 뒤 제출하면 403이 발생하는 현상을 운영 access log의 `GET 200 → POST 403`으로 확인했다.
- 원인은 기존 공개 데모 로그인 쿠키였다. 로그인 GET은 열렸지만 전역 데모 unsafe 요청 차단기가 새 계정으로 전환하는 `POST /auth/login`까지 막았다.
- CSRF·로그인 검증·공개 rate limit은 유지하고 `auth.login`과 호환 `admin.login`만 데모 세션의 안전한 계정 전환 예외로 추가했다. 다른 데모 쓰기 차단은 그대로다.
- 수정 전 `403 != 302` 실패와 수정 후 실사용 관리자 `user_id`·`auth_version` 세션 교체, 대시보드 200을 PostgreSQL 회귀로 고정했다. 단위 361건, PostgreSQL 191건, Ruff·포맷·mypy·민감자료 검사를 통과했다.
- 후속 커밋 `379e57f`을 `origin/main`에 push했다. 실사용 계정·BYOK 포함 백업 `admission_20260720_115319_3899759.dump`의 SHA-256 `2a35f5b8d7e9099f0c8148221982d4368c8a93086107e61fab812d7c2e04faeb`, archive와 격리 복원을 확인했다.
- 기존 DB 컨테이너 `072f1a30e7d5...`와 volume을 유지하고 웹만 컨테이너 `ccbc036a4579...`, 이미지 `sha256:d117c49d03bcdb080303f99fb047ea1dcb7c7d7e13589176edb6d93ae6f560ec`로 교체했다.
- 공인 HTTPS Chromium 2건에서 기본 실사용 관리자 흐름과 `demo-main-admin 로그인 → 로그아웃하지 않고 /auth/login → 실사용 관리자 로그인 → 대시보드`를 통과했다. 운영 access log는 해당 POST를 모두 302로 기록했고 403·console·page error는 없었다.
