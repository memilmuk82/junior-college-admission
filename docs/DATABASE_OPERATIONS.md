# PostgreSQL 운영 구조

## 연결

- `web`과 `db`는 Docker Compose의 전용 `backend` 네트워크에 연결한다.
- PostgreSQL 포트는 호스트에 공개하지 않는다.
- `web`은 `db:5432`로 연결하며 접속 값은 Git 제외 `.env`에서 Compose가 주입한다.
- `web`은 PostgreSQL healthcheck가 성공한 뒤 시작한다.

## 영속성

- PostgreSQL 데이터 디렉터리는 `postgres_data` named volume에 저장한다.
- 컨테이너 재생성은 volume 삭제를 포함하지 않아야 한다.
- 실제 DB dump는 `backups/`에 저장하고 Git과 Docker build context에서 제외한다.

## 마이그레이션

Flask-Migrate가 Alembic을 Flask 애플리케이션 팩토리와 연결한다. PostgreSQL 전용 연결 문자열을 설정한 뒤 개발·운영 모두 다음 실행 형태를 사용한다.

```bash
docker compose run --rm web uv run flask --app wsgi db upgrade
```

모델 변경 후 migration 후보를 만들 때는 자동 생성 결과를 반드시 검토한 뒤 적용한다.

```bash
docker compose run --rm web uv run flask --app wsgi db migrate -m "변경 내용"
docker compose run --rm web uv run flask --app wsgi db upgrade
```

## PostgreSQL 통합 테스트

`db-test`는 호스트 loopback에만 포트를 열고 `tmpfs`를 사용한다. 테스트 종료 시 컨테이너를 제거하며 운영 `postgres_data` volume에 접근하지 않는다.

```bash
make test-integration
```

## 백업

DB 이미지에 포함된 `pg_dump`를 사용하며 비밀번호를 명령 인자로 노출하지 않는다.

```bash
./scripts/backup_postgres.sh
```
