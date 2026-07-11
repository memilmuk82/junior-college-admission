# 2027 전문대 입시 상담 앱

고등학교 3학년 직업위탁 학생을 상담하는 교사를 위한 Flask 기반 상담 보조 시스템입니다. 이 시스템은 합격 예측기가 아니며, 지원자격 판정과 근거가 확인된 전형만 계산 대상으로 다룹니다.

현재 상태는 **Phase 2: 입력 게이트웨이 진행 중**입니다. PostgreSQL 기반 위에 CSV·표 붙여넣기·XLSX·텍스트 PDF·PNG/JPEG·클립보드 이미지 미리보기와 확인 행 저장·원본 삭제 계약까지 제공하며, 이미지형 PDF·전형 판정·점수 계산 기능은 아직 제공하지 않습니다.

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
