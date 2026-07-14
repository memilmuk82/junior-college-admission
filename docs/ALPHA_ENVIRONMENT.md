# 내부 알파 컨테이너

알파 환경은 독립 Compose 프로젝트 `junior-college-admission-alpha`의 `web-alpha`·`db-alpha` 서비스로 기존 `web`·`db` 및 운영 데이터와 분리한다. PostgreSQL과 임시 업로드는 각각 `alpha_postgres_data`, `alpha_uploads` named volume에 저장하며 호스트에는 앱의 loopback 포트만 연다.

## 준비

`.env.example`을 Git 제외 파일 `.env.alpha`로 복사하고 `ALPHA_*` 값만 채운다. 값은 문서·로그·명령 인자에 출력하지 않는다.

- `ALPHA_DATABASE_URL`의 호스트는 `db-alpha`를 사용한다.
- 관리자 비밀번호는 평문이 아니라 Werkzeug password hash만 저장한다. Compose가 해시의 `$`를 변수로 해석하지 않도록 `.env.alpha` 값 전체를 작은따옴표로 감싼다.
- `ALPHA_BYOK_MASTER_KEY`는 Fernet 형식의 알파 전용 키로 운영 키와 분리한다.
- OpenAI·Gemini·Anthropic 공급자 키는 compose나 이미지에 넣지 않는다. 알파 관리자 화면에서 사용자별로 암호화 저장한다.
- 개발자의 `.env.local` `OPENAI_API_KEY`는 비식별 외부 smoke에만 사용하며 앱 컨테이너에 자동 주입하지 않는다.

## 실행과 점검

```bash
make alpha-up
make alpha-status
make alpha-check
```

`alpha-up`은 `db-alpha` healthcheck 후 마이그레이션을 적용하고 `web-alpha`를 시작한다. `alpha-check`는 `/health`와 Alembic 현재 revision을 확인한다.

평문 테스트 비밀번호는 파일에 저장하지 않고 현재 셸에만 둔다. 기본 smoke는 빈 알파 DB에서도 가능한 관리자 인증, 잘못된 CSV 처리, 모바일 레이아웃과 JavaScript 비활성 SSR을 확인한다.

```bash
ALPHA_ADMIN_USERNAME=synthetic-admin \
ALPHA_ADMIN_PASSWORD=synthetic-password \
make alpha-e2e
```

합성 상담 seed까지 준비된 내부 인수 환경에서는 전체 브라우저 검증을 실행한다.

```bash
ALPHA_ADMIN_USERNAME=synthetic-admin \
ALPHA_ADMIN_PASSWORD=synthetic-password \
make alpha-e2e-full
```

전체 검증 항목은 CSV 오류 처리, BYOK 마스킹·삭제, 지원자격 우선 상담, 학생·교사 A4 출력, 모바일, JavaScript 비활성 흐름과 브라우저 콘솔 오류다. 실제 대학 규칙이나 학생 자료를 seed로 사용하지 않는다.

## 종료와 데이터 보존

```bash
make alpha-logs
make alpha-down
```

`alpha-down`은 컨테이너만 중지하고 alpha volume을 삭제하지 않는다. volume 삭제, DB 초기화, 실제 학생 자료 투입은 별도 명시 승인 없이는 수행하지 않는다.

## 베타 전환 게이트

- 전체 `make check` 통과
- 기본 알파 Playwright smoke 실패 0건
- 합성 seed 기반 전체 Playwright 실패 0건
- 외부 LLM 비식별 smoke 통과 또는 네트워크 차단 사유 기록
- 실제 학생 자료 없이 PDF·CSV 검토 흐름 통과
- 지원자격 판정 전 성적 계산 차단과 근거 trace 확인
- 민감자료 검사 통과
- 장애·복구·남은 위험 기록

알파 통과만으로 실제 서비스를 배포하지 않는다. 베타에서 WSGI 서버, 운영 secret manager, 보유기간, 백업, 장애 대응, 공식 자료 승인 체계를 별도 확정한다.

2026-07-14 알파 검증에서는 OpenAI 키 인증과 `gpt-4.1-mini` 비식별 구조화 응답이 통과했다. `gpt-5-mini`는 애플리케이션의 15초 제한을 초과했으므로 현재 알파 권장 모델로 사용하지 않는다.
