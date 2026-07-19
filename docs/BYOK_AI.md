# BYOK AI 보안·데이터 계약

Phase 9 AI 기능은 지원자격이나 점수를 계산하는 엔진이 아니다. 기존 결정론적 상담 결과 중 공개 가능한 고정 필드만 문장 초안으로 바꾸며, 공급자 키가 없거나 AI 호출이 실패해도 자격 판정·성적 계산·입시결과 비교·A4 출력은 영향을 받지 않는다.

## 외부 전송 payload

schema version 1의 최상위 필드는 다음으로 고정한다.

- `consultation_status`
- `target`: 모집학년도·대학·캠퍼스·학과·모집시기·전형 표시명
- `eligibility`: 결정론적 상태·사유 코드·누락 사실 이름·규칙 버전
- `score`: 검증된 최종/표시/최대 점수·반올림·규칙 버전·면접/실기 안내 비율
- `admission_result`: 직접 비교 가능한 같은 연도·규칙 버전의 게시 결과만 포함
- `evidence`: 규칙 종류·버전·공개 문서 종류/상태·쪽

내부 학생 코드, 학생 이름, 학번, 성적 행, 과목명, 원점수, 생활기록부 원문·이미지, 세특, 건강·가정정보, 상담 메모와 자유 입력은 payload에 없다. canonical JSON과 SHA-256 digest를 호출 직전에 다시 대조하고 중첩 필드 allowlist를 통과한 복제본만 공급자 어댑터에 전달한다.

## 공급자 키

- 키는 로그인 계정의 불변 actor 식별자와 `OPENAI`·`GEMINI`·`ANTHROPIC` 공급자 조합별로 한 건만 둔다. 학생·교사 키는 서로 조회하거나 사용하지 못한다.
- PostgreSQL에는 `Fernet` 인증 암호문, `FERNET_V1` 버전, 끝 4자리 마스킹 힌트만 저장한다.
- `BYOK_MASTER_KEY`는 공급자 키와 별개의 배포 secret이며 DB·Git·HTML·로그·Flask 세션에 기록하지 않는다.
- master key가 없거나 잘못되면 신규 키 저장을 실패시키고 AI 이외 기능은 계속 제공한다.
- 키 교체는 새 암호문으로 갱신하며 삭제는 해당 암호문 레코드를 제거한다.

운영 master key의 생성·보관·백업·교체는 배포 secret manager 절차에 포함해야 한다. key rotation 시에는 기존 암호문을 구키로 복호화하고 신키로 재암호화하는 별도 원자적 작업과 복구 검증이 필요하며, 현재 초기 계약은 이를 자동 수행하지 않는다.

## 초안 생명주기

AI 응답은 `GENERATED_DRAFT`로 저장한다. 교사는 상담 문장을 직접 검토·수정하고, 학생은 본인 성적의 상담 문장을 직접 검토한 뒤 명시적으로 확정한다. 기존 DB 호환 상태 코드는 두 경우 모두 `TEACHER_CONFIRMED`를 유지하며 화면에는 `사용자 확정`으로 표시한다. 사용하지 않으면 `REJECTED`가 된다. 확정문은 actor·시각·입력 payload digest를 보존하고 기존 자격·점수·근거 trace를 수정하지 않는다.

합격 확률, 합격 가능, 불합격, 안정/적정/소신 지원, 위험·추천 표현은 Unicode 정규화와 제로폭 문자 제거 후 생성 응답과 사용자 확정문 모두에서 차단한다. 공급자 응답의 숫자는 payload에 실제 존재하는 값만 허용한다. 미확정 또는 거부 초안은 확정 상담자료로 취급하지 않는다.

## 외부 공급자 어댑터

- OpenAI는 고정 `https://api.openai.com/v1/responses` 엔드포인트와 `Authorization` 헤더를 사용하고, Responses API의 `text.format` JSON Schema를 강제한다. 서버 측 저장은 `store: false`로 요청한다.
- Gemini는 고정 `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` 엔드포인트와 `x-goog-api-key` 헤더를 사용하고, `responseMimeType: application/json`과 `responseJsonSchema`를 강제한다.
- Anthropic은 고정 `https://api.anthropic.com/v1/messages` 엔드포인트와 `x-api-key`·`anthropic-version` 헤더를 사용하고, `output_config.format` JSON Schema를 강제한다.
- 모델 ID는 영문·숫자로 시작하는 영문·숫자·점·밑줄·하이픈 128자 이하만 허용해 경로 또는 쿼리 주입을 차단한다.
- 요청 timeout은 15초, 요청 본문은 64 KiB, 응답 본문은 128 KiB로 제한한다. JSON이 아닌 응답과 불완전 종료를 거부한다.
- 자동 재시도는 중복 과금과 중복 초안 생성 위험 때문에 수행하지 않는다. 실패한 생성은 저장하지 않으며 관리자가 원래 상담 결과를 확인한 뒤 명시적으로 다시 요청한다.
- 공급자 오류 본문, API 키, 요청 헤더는 관리자 화면·예외 메시지·로그에 포함하지 않는다.

계약 기준은 [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create), [Gemini generateContent API](https://ai.google.dev/api/generate-content), [Anthropic Messages API](https://platform.claude.com/docs/en/api/messages/create) 및 [Anthropic Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) 공식 문서다.

## 운영 게이트

- 충전 후 새 `.env.local` 키는 공식 Models API 인증에 성공했다. 2026-07-14 알파 재검증에서 `gpt-4.1-mini`에 개인정보 없는 합성 payload를 전송해 구조화 JSON·금지 표현·숫자 검증까지 통과하는 `OPENAI_ALPHA_SMOKE_PASS`를 확인했다. 키와 응답 원문은 출력하지 않았다. 같은 환경의 `gpt-5-mini`는 15초 응답 제한을 초과했으므로 현재 알파 권장 모델에서 제외한다.
- Gemini·Anthropic은 유료 실키 성공 호출을 수행하지 않는다. 실제 연결 성공은 `UNVERIFIED_EXTERNAL`이며, 고정 endpoint·header·schema·timeout·오류 은닉·비밀값 비노출 합성 HTTP 계약만 검증한다.
- 기준 명세는 세 공급자 어댑터를 허용하지만 모든 공급자의 유료 실호출을 완료 조건으로 요구하지 않는다. 따라서 OpenAI 비식별 실호출과 세 공급자 합성 계약, BYOK 보안, 교사 확정 경계를 근거로 Phase 9를 `PASS`로 판정한다.
- master key rotation 운영 절차와 복구 훈련
