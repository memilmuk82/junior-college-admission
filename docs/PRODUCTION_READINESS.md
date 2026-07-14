# 실제 서비스 전환 사전 게이트

내부 알파·베타 통과 후에도 실제 서비스 프로세스는 운영 시작 조건을 모두 만족해야 기동된다. 이 문서는 배포 실행 명령이 아니라 구성 사전검사 계약이다.

## 필수 구성

- `APP_ENV=production`
- 32자 이상의 운영 전용 `SECRET_KEY`
- PostgreSQL `DATABASE_URL`
- 운영 관리자 `ADMIN_USERNAME`과 Werkzeug scrypt `ADMIN_PASSWORD_HASH`
- 유효한 Fernet `BYOK_MASTER_KEY`
- 쿼리·경로가 없는 HTTPS `PUBLIC_BASE_URL`
- 공개 주소와 일치하는 쉼표 구분 `TRUSTED_HOSTS`
- 애플리케이션 앞의 신뢰 reverse proxy 한 대를 뜻하는 `TRUST_PROXY_HOPS=1`

비밀값은 Git, Compose 파일, 이미지, 명령 인자와 로그에 기록하지 않는다. 실제 배포 환경에서는 secret manager가 파일로 주입하고 애플리케이션에는 `SECRET_KEY_FILE`, `DATABASE_URL_FILE`, `ADMIN_USERNAME_FILE`, `ADMIN_PASSWORD_HASH_FILE`, `BYOK_MASTER_KEY_FILE` 경로만 전달한다. 직접 값과 대응하는 `*_FILE`을 동시에 지정하면 시작을 거부한다.

## 사전검사

현재 셸에 secret manager가 값을 주입한 뒤 실행한다.

```bash
make production-preflight
```

로컬에서 Git 제외 env 파일의 변수명과 형식만 확인할 때는 다음처럼 파일 경로만 전달할 수 있다.

```bash
PRODUCTION_ENV_FILE=.env.production make production-preflight
```

검사는 비밀값을 출력하지 않고 누락·오류 변수명만 반환한다. 통과하면 secure·HTTP-only·SameSite=Lax session cookie, HTTPS URL scheme, 신뢰 호스트 검증과 정확히 한 단계의 `ProxyFix`가 활성화된다.

## 여전히 별도 확인할 항목

- reverse proxy 제품·버전, TLS 인증서 발급·갱신과 HSTS
- 방화벽, 공개 포트, DNS와 허용 호스트의 실제 일치
- secret manager 접근 정책과 키 회전
- PostgreSQL 백업·복구, 보유기간과 삭제 예외
- 최종 모집요강 사람 승인과 게시 롤백
- 운영 변경창, 관찰 지표, 장애 대응 담당자

사전검사 통과만으로 외부 배포나 실제 모집요강 게시를 실행하지 않는다.

## production 후보 Compose

`docker-compose.production.yml`은 stable `nginx:1.30.3-alpine` reverse proxy, Gunicorn 앱, PostgreSQL 17을 서로 분리한다. 앱과 DB는 호스트 포트를 열지 않고 Nginx만 HTTP·HTTPS 포트를 공개한다. HTTP는 HTTPS로 영구 전환하며 TLS 1.2·1.3, HSTS와 기본 보안 헤더를 적용한다.

모든 비밀값과 TLS 인증서는 `PRODUCTION_SECRETS_DIR` 아래 Git 제외 파일로 준비하고 컨테이너에는 `/run/secrets`로 읽기 전용 전달한다. 호스트에서 실행되는 `production-preflight`가 동일한 값을 검증할 수 있도록 `.env.production`의 각 `*_FILE`에는 해당 파일의 호스트 절대경로를 설정한다. `PRODUCTION_PROXY_UID`·`PRODUCTION_PROXY_GID`는 TLS 개인키를 읽을 수 있는 전용 비root 소유자와 일치해야 한다. 실제 서비스에서는 승인된 secret manager가 같은 파일 계약과 소유권을 제공해야 한다.

```bash
PRODUCTION_ENV_FILE=.env.production make production-up
PRODUCTION_ENV_FILE=.env.production \
PRODUCTION_URL=https://service.example.org \
PRODUCTION_CA_CERT=/approved/path/fullchain.pem \
make production-check
```

합성 로컬 인증서 리허설에서만 `E2E_IGNORE_HTTPS_ERRORS=true`를 사용할 수 있다. 실제 서비스 인증서 검증에서는 이를 사용하지 않는다.

## 호스트 Nginx 원본 모드

호스트 Nginx가 이미 공인 TLS를 종료하고 `127.0.0.1:8000`으로 전달하는 서버에서는 `docker-compose.host-nginx.yml`을 함께 사용한다. 이 override는 컨테이너 TLS proxy를 기본 profile에서 제외하고 Gunicorn `web-production`만 loopback 원본 포트에 게시한다. Flask 개발 서버를 외부에 노출하지 않으며 PostgreSQL은 계속 호스트 포트를 열지 않는다.

```bash
PRODUCTION_ENV_FILE=.env.production make production-origin-up
PRODUCTION_ENV_FILE=.env.production make production-origin-status
PRODUCTION_ENV_FILE=.env.production \
PRODUCTION_URL=https://service.example.org \
PRODUCTION_CA_CERT=/approved/path/fullchain.pem \
make production-origin-check
```

호스트 Nginx는 정확히 한 단계의 신뢰 proxy로 `Host`, `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Host`, `X-Forwarded-Port`를 설정해야 한다. production 앱도 HSTS·nosniff·referrer·frame 헤더를 반환한다. 8000번 원본은 `127.0.0.1` 외 주소에 바인딩하면 안 된다.

### 초기 secret 부트스트랩

실제 값은 명령 출력이나 Git에 남기지 않는다. 아래 명령은 기존 `.env.production` 또는 `secrets/production`이 있으면 덮어쓰지 않고 실패하며, 신규 live 프로젝트 전용 secret과 최초 관리자 비밀번호 파일을 권한 `0600`으로 생성한다.

```bash
PRODUCTION_HOST=service.example.org make production-bootstrap
```

최초 관리자 비밀번호는 `secrets/production/initial_admin_password`에서 운영 담당자만 확인한다. 채팅·로그·티켓에 복사하지 않으며 별도 승인된 비밀 저장소로 옮긴 뒤 원문 파일의 처리 정책을 확정한다. host Nginx override의 Compose 프로젝트명은 `junior-college-admission-live`로 고정해 기존 합성 production volume을 재사용하지 않는다.

부트스트랩은 secret 파일을 생성한 호스트 계정의 UID/GID를 `PRODUCTION_APP_UID`·`PRODUCTION_APP_GID`로 기록한다. 웹 컨테이너는 해당 비root 사용자로 실행하므로 capability를 모두 제거한 상태에서도 권한 `0600`인 secret만 읽을 수 있다. 별도 `init-production-uploads` 컨테이너는 네트워크 없이 `CHOWN`·`FOWNER` capability만 잠시 사용해 업로드 named volume을 같은 UID/GID와 권한 `0700`으로 맞춘 뒤 종료한다. 웹 서비스는 이 초기화 성공과 PostgreSQL health를 모두 확인한 후 시작한다.

2026-07-14 실제 서비스 기반 부트스트랩에서는 live 전용 빈 PostgreSQL volume에 Alembic `head`를 적용하고, Gunicorn health와 `127.0.0.1:8000` 원본 제한, 호스트 Nginx·Cloudflare 공인 HTTPS 보안 헤더를 확인했다. 관리자 Playwright smoke 3건도 통과했다. 이 결과는 인프라 경로 검증이며 공식 규칙 게시·학생 실데이터 반입·운영 정책 승인까지 자동 완료했다는 의미는 아니다.
