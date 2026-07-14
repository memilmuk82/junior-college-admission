# Phase 9 작업 카드

## 목표

검증된 상담 결과만 비식별 고정 payload로 변환하고, 관리자가 선택적으로 등록한 공급자 키를 사용자별로 서버 측 암호화해 보관한다. AI 출력은 상담 문장 초안과 추가 확인 항목으로만 취급하며 교사가 수정·확정하기 전에는 학생용 결과나 계산 trace를 변경하지 않는다.

## 선행조건

- `PROJECT_STATUS.md`의 Phase 8 `PASS`
- AI 키가 없어도 지원자격·성적 계산·입시결과 비교·A4 출력이 모두 동작함
- 지원자격과 점수는 기존 결정론적 엔진의 결과만 사용함
- 실제 학생 자료와 상담 메모는 외부 AI payload에서 제외함

## 근거 문서

- `2027_전문대_입시상담앱_실행개발문서_v2.md` FR-09 및 Phase 9
- `CODEX_MASTER_PROMPT_2027_전문대_입시상담앱_v3.md` 10장 및 Phase 9

## 허용 수정 경로

- 익명화·키 관리·초안 생명주기·공급자 계약: `app/services/`
- Flask SSR route·template·CSS: `app/`
- 사용자별 암호화 키와 초안 저장 계약: `app/models.py`, `migrations/`
- 암호화 라이브러리와 환경 계약: `pyproject.toml`, `uv.lock`, `.env.example`
- 합성 검증: `tests/`, `e2e/`, `Makefile`
- 기록: `README.md`, `PROJECT_STATUS.md`, `DEVELOPMENT_LOG.md`, `docs/`, `tasks/PHASE_9.md`

## 금지 사항

- 두 기준 원본 문서와 Phase 0~8 작업 카드 수정
- AI의 지원자격·점수 계산, 합격 확률·추천·안정/적정/소신/위험 생성
- 학생 이름·학번·익명 학생 코드·생기부 원문/이미지·세특·건강·가정정보·상담 메모 전송
- API 키 평문 저장·표시·로그 기록 또는 Flask 세션 저장
- 교사 확인 전 AI 초안의 학생용 출력 반영
- 외부 AI 응답으로 기존 자격·점수·규칙 버전·근거 trace 변경
- 실제 API 키 또는 실제 학생 자료를 테스트·Git에 추가
- JavaScript가 없으면 키 삭제·초안 수정·확정을 할 수 없는 구조

## 비식별 payload 계약

- 고정 schema version과 허용 키만 직렬화한다.
- 대학·캠퍼스·모집학년도·모집시기·전형·학과, 결정론적 자격 상태, 계산 상태, 검증 점수, 규칙 ID/버전, 비교 가능 입시결과와 공개 근거 상태만 포함할 수 있다.
- 학생 코드·성적 행·과목명·원점수·상담 메모·자유 입력은 포함하지 않는다.
- 누락값은 `null`로 보존하고 0과 구분한다.
- payload digest를 저장해 어떤 입력으로 초안을 생성했는지 재현한다.

## 초안 생명주기

```text
GENERATED_DRAFT -> TEACHER_CONFIRMED
                -> REJECTED
```

- 생성 원문과 교사 수정문을 구분한다.
- 확정 시 관리자 식별자와 시각을 기록한다.
- 확정된 문장은 기존 계산 결과를 덮어쓰지 않는다.

## 먼저 작성할 실패 테스트

1. payload 화이트리스트에 학생 코드·상담 메모·성적 원문이 없음
2. 자격·점수 결과를 payload 생성기가 재계산하지 않음
3. 누락과 숫자 0을 서로 다르게 직렬화
4. 공급자·사용자별 키를 평문 없이 암호화 저장하고 마스킹 표시
5. 잘못된 master key와 변조 ciphertext 복호화 차단
6. 키 삭제 뒤 ciphertext가 DB에 남지 않음
7. 공급자 어댑터가 허용된 구조화 payload만 입력받음
8. 금지 표현 또는 결과 필드 변경을 포함한 응답 거부
9. 교사 수정 전 초안이 확정/학생용으로 노출되지 않음
10. 교사 수정·확정 시 actor·시각·payload digest 보존
11. AI 키가 없어도 Phase 8 상담·출력 회귀 통과
12. 관리자 route의 인증·CSRF·비공개 캐시 유지

## 검증 명령

```bash
make test-unit
make test-integration
make test-e2e
make lint
make validate-rules
make check-sensitive-data
make check
```

## 게이트

- 실제 외부 공급자 호출은 각 공급자 공식 API 계약과 운영 BYOK 자격증명 절차를 확인한 뒤 별도 어댑터에서만 수행한다.
- 합성 어댑터 테스트만으로 외부 공급자 연결 완료를 주장하지 않는다.
- 공급자별 유료 실키 성공 호출은 선택 검증이며 Phase 완료의 필수 조건이 아니다. 실키를 검증하지 않은 공급자는 관리자 화면에서 사용자가 유효한 키를 등록할 때까지 `UNVERIFIED_EXTERNAL`로 표시한다.
- 교사가 확정하지 않은 AI 출력은 참고 초안이며 학생용 출력에 포함하지 않는다.
- 금지 필드나 금지 역할이 감지되면 초안 생성을 실패시키고 결정론적 상담 결과는 그대로 유지한다.

## 구현 현황

- [x] Phase 9 작업 카드와 보안 경계 확정
- [x] 비식별 payload 화이트리스트와 digest
- [x] 사용자별 공급자 키 암호화·마스킹·삭제
- [x] 공급자 중립 어댑터와 응답 검증
- [x] 교사 수정·확정·거부 생명주기
- [x] 관리자 SSR 설정·초안 화면
- [x] 단위·PostgreSQL 통합·Chromium 보안 기반 회귀
- [x] OpenAI·Gemini·Anthropic 실제 HTTP 어댑터
- [x] 고정 HTTPS 엔드포인트·구조화 출력·크기·timeout·무자동재시도 계약
- [x] OpenAI 운영 자격증명 성공 smoke test(비식별 합성 payload)
- [x] Gemini·Anthropic 유료 실키 smoke를 완료 조건에서 제외하고 합성 HTTP 계약 검증으로 한정
- [x] Phase 9 최종 게이트 `PASS`(OpenAI 실호출·세 공급자 합성 계약·BYOK 보안·교사 확정 경계)
