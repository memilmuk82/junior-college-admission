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

Phase 1에서 Alembic 설정과 최초 migration을 추가한다. 개발·운영 모두 다음 실행 형태를 사용한다.

```bash
docker compose run --rm web uv run alembic upgrade head
```

## 백업

DB 이미지에 포함된 `pg_dump`를 사용하며 비밀번호를 명령 인자로 노출하지 않는다.

```bash
./scripts/backup_postgres.sh
```
