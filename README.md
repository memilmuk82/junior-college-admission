# 2027 전문대 입시 상담 앱

고등학교 3학년 직업위탁 학생을 상담하는 교사를 위한 Flask 기반 상담 보조 시스템입니다. 이 시스템은 합격 예측기가 아니며, 지원자격 판정과 근거가 확인된 전형만 계산 대상으로 다룹니다.

현재 상태는 **Phase 9: BYOK AI 진행 중**입니다. Phase 8의 지원자격 우선 판정·결정론적 성적 계산·입시결과 비교·학생용/교사용 A4는 AI 키 없이 그대로 동작합니다. Phase 9에서는 검증된 결과만 비식별 payload로 문장화하고, 사용자별 공급자 키 암호화와 교사 수정·확정 경계, OpenAI·Gemini·Anthropic 공식 HTTP 어댑터를 제공합니다. AI는 자격·점수·합격 가능성을 결정하지 않습니다. 운영 자격증명 성공 smoke test 전까지 Phase 9 최종 게이트는 통과로 표시하지 않습니다.

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

브라우저에서 `http://127.0.0.1:5000`을 열고, 상태 확인은 `http://127.0.0.1:5000/health`를 사용합니다.

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

`docker-compose.yml`은 외부에 `5000` 포트만 공개합니다. `db` 서비스는 호스트 포트를 열지 않고 전용 `backend` 네트워크에서 `db:5432`로만 접근하며, 데이터는 `postgres_data` named volume에 유지됩니다.

실제 `SECRET_KEY`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DATABASE_URL`는 Git에서 제외되는 `.env`에 설정합니다.

```bash
# DB healthcheck 통과 후 web 시작
docker compose up --build

# pg_dump custom-format 백업, 결과는 Git 제외 backups/에 저장
./scripts/backup_postgres.sh

# PostgreSQL Flask-Migrate/Alembic 마이그레이션
docker compose run --rm web uv run flask --app wsgi db upgrade
```
