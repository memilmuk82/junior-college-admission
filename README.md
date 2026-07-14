# 2027 전문대 입시 상담 앱

고등학교 3학년 직업위탁 학생을 상담하는 교사를 위한 Flask 기반 상담 보조 시스템입니다. 이 시스템은 합격 예측기가 아니며, 지원자격 판정과 근거가 확인된 전형만 계산 대상으로 다룹니다.

현재 상태는 **Phase 10 개발·비운영 준비 `PASS_NONPROD`**입니다. Phase 8의 지원자격 우선 판정·결정론적 성적 계산·입시결과 비교·학생용/교사용 A4는 AI 키 없이 그대로 동작합니다. Phase 9는 OpenAI 비식별 실호출과 OpenAI·Gemini·Anthropic 합성 HTTP 계약을 통과했습니다. Gemini·Anthropic 유료 실키 검증은 완료 조건에서 제외하며 실제 연결 성공을 주장하지 않습니다. 실제 도메인·공인 TLS·secret manager·운영 DB 정책·공식 자료 사람 승인은 별도 운영 전환 게이트입니다.

학교별 성적 규칙은 향후 관리자 메뉴 직접 편집을 기본으로 하며, 대량 작업에는 같은 canonical 스키마의 고정 CSV를 사용합니다. Phase 4는 CSV schema와 검증 codec만 제공하고 업로드·미리보기·DRAFT 생성·승인 화면은 Phase 7에서 구현합니다. XLSX는 규칙 운영의 필수 입력 형식이 아닙니다.

## 기술 방향

- Python 3.12+, Flask, Jinja2
- SQLAlchemy 2.x, Flask-SQLAlchemy, Alembic, Flask-Migrate
- Flask Jinja2 서버 렌더링(SSR), HTML, Tailwind CSS
- 필요한 상호작용만 Vanilla JavaScript와 fetch API 사용
- SPA 프레임워크와 TypeScript 미사용
- PostgreSQL 17, 애플리케이션과 분리된 DB 컨테이너 및 named volume
- pytest, Ruff, mypy와 PostgreSQL 17 통합 테스트

## 로컬 실행

```bash
uv sync
uv run flask --app wsgi run --debug

# PostgreSQL 포함 전체 구성
docker compose up --build
```

브라우저에서 `http://127.0.0.1:8000`을 열고, 상태 확인은 `http://127.0.0.1:8000/health`를 사용합니다.

내부 알파는 운영 구성과 분리된 `docker-compose.alpha.yml`을 사용합니다. Git 제외 `.env.alpha`를 준비한 뒤 `make alpha-up`, `make alpha-check`로 시작·검증합니다. 상세 절차는 [내부 알파 컨테이너](docs/ALPHA_ENVIRONMENT.md)를 참고합니다.

내부 베타는 Gunicorn WSGI와 별도 PostgreSQL을 사용하는 `docker-compose.beta.yml`로 다시 격리합니다. 알파 게이트 통과 후에만 [내부 베타 컨테이너](docs/BETA_ENVIRONMENT.md)의 절차를 수행합니다.

실제 서비스 프로세스는 [운영 전환 사전 게이트](docs/PRODUCTION_READINESS.md)의 필수 구성이 모두 유효할 때만 시작할 수 있습니다. `make production-preflight`는 값 대신 오류 변수명만 보고합니다.

production 후보는 `docker-compose.production.yml`의 Nginx TLS → Gunicorn → PostgreSQL 구조로 분리되며, 실제 비밀값과 인증서는 Git 제외 secret 파일로만 주입합니다.

## 검증

```bash
make test-unit
make test-integration
make lint
make check
```

입시결과의 수집 단계, 품질 차단, 과거 규칙 버전 연결은 [Phase 6 입시결과 수집·분석 계약](docs/PHASE_6_ADMISSION_RESULTS.md)에 정리되어 있습니다.

Phase 9의 비식별 payload, 사용자별 키 암호화, 교사 확정 경계는 [BYOK AI 보안·데이터 계약](docs/BYOK_AI.md)에 정리되어 있습니다.

## 데이터 취급

- 원본 PDF·엑셀, 학생 개인정보, 업로드 파일, OCR 파생물, 로컬 DB 파일, `.env`, API 키는 Git과 Docker 이미지에 포함하지 않습니다.
- 외부 공개가 가능한 정제·검수 완료 전형 데이터만 `data/seed/`에 둘 수 있습니다.
- `data/raw/`, `data/staging/`, `data/published/`, `uploads/`, `instance/`의 실제 내용은 로컬 전용입니다.
- 실제 학생 자료는 테스트 픽스처로 사용하지 않습니다. 테스트에는 합성 익명 자료만 허용합니다.

상세 요구사항의 기준 문서는 저장소 루트의 기존 문서 두 개입니다. 두 문서는 수정·이동하지 않고 원문 그대로 유지합니다.


## PostgreSQL 운영

`docker-compose.yml`은 Cloudflare 원본 연결과 맞춘 `8000` 포트만 공개합니다. `db` 서비스는 호스트 포트를 열지 않고 전용 `backend` 네트워크에서 `db:5432`로만 접근하며, 데이터는 `postgres_data` named volume에 유지됩니다.

실제 `SECRET_KEY`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DATABASE_URL`는 Git에서 제외되는 `.env`에 설정합니다.

```bash
# DB healthcheck 통과 후 web 시작
docker compose up --build

# pg_dump custom-format 백업, 결과는 Git 제외 backups/에 저장
./scripts/backup_postgres.sh

# PostgreSQL Flask-Migrate/Alembic 마이그레이션
docker compose run --rm web uv run flask --app wsgi db upgrade
```
