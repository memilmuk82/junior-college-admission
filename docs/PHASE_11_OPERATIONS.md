# Phase 11 Google OIDC 운영 런북

Google OIDC는 기본 Compose와 `.env.example`에서 비활성화되어 있다. 실제 Google Web
OAuth client, 변경창, 직전 백업, 호스트 보안 게이트가 모두 준비된 경우에만 이 문서의
전용 override와 Make target으로 활성화한다. client ID와 secret 원문은 명령 인자, env 파일,
Git, 로그에 기록하지 않는다.

## 0. 변경창과 외부 게이트

- Google Web client의 승인된 redirect URI를 공개 주소의
  `https://<host>/auth/google/callback`과 정확히 일치시킨다.
- `PRODUCTION_SECRETS_DIR/google_oidc_client_id`와
  `PRODUCTION_SECRETS_DIR/google_oidc_client_secret`을 승인된 비밀 저장소에서 파일로
  주입한다. 디렉터리는 `0700`, 두 파일은 `0600`으로 유지한다.
- 호스트 Nginx의 HTTP·HTTPS vhost 모두 query 없는 전용 access log를 사용하는지,
  callback 포함 공개 인증 endpoint가 IP별 rate limit을 적용하는지 확인한다. Cloudflare를
  사용하면 공식 CIDR만 신뢰해 실제 client IP를 복원하고 direct/spoof 요청을 차단한다.
- `nginx -t`, 합성 callback query 비기록, 인증 endpoint 429, 실제 client IP, HTTPS 회귀와
  인증서 갱신 리허설을 통과한 운영 기록이 있을 때만 `OIDC_HOST_GATE_CONFIRMED=PASSED`로
  확인한다.

### 호스트 Nginx 기준 설정

저장소의 다음 파일을 운영 호스트에 같은 역할로 설치한다. 기존 파일은 변경창 식별자가
포함된 root 전용 백업으로 먼저 보존하고, `nginx -t`가 실패하면 reload하지 않고 즉시
백업본을 복원한다.

| 저장소 파일 | 운영 경로 |
| --- | --- |
| `deploy/nginx.host-admission-http.conf` | `/etc/nginx/conf.d/admission-security.conf` |
| `deploy/nginx.host-admission-cloudflare-realip.conf` | `/etc/nginx/snippets/admission-cloudflare-realip.conf` |
| `deploy/nginx.host-admission-proxy.conf` | `/etc/nginx/snippets/admission-proxy.conf` |
| `deploy/nginx.host-admission-site.conf` | `/etc/nginx/sites-available/admission.memilmuk82.com` |
| `deploy/logrotate.admission` | `/etc/logrotate.d/admission` |

`admission_path_only` log format은 `$uri`만 사용하며 `$request`, `$request_uri`, `$args`를
금지한다. Cloudflare IP 목록은 배포 때 공식 IPv4·IPv6 목록과 대조하고, 변경 시 저장소
목록과 테스트도 함께 갱신한다. real-IP include는 이 서비스의 두 server block에만 적용한다.
직접 origin 접근 차단은 SSH와 Certbot 갱신 경로를 보존한 별도 방화벽 변경으로 취급한다.
공용 Nginx 로그의 기존 내용은 이 작업에서 삭제하지 않고 승인된 보존·사고 대응 절차로
다룬다.

## 1. 비활성 상태 사전검사

```bash
PRODUCTION_ENV_FILE=.env.production make production-preflight
```

이 단계는 현재 기본 비활성 구성을 검사할 뿐 OIDC를 켜거나 컨테이너를 변경하지 않는다.
공개 주소, 신뢰 host, 한 단계 proxy, 기존 운영 secret 계약이 먼저 통과해야 한다.

## 2. 변경 직전 백업과 격리 복원

변경창 안에서 live DB의 새 custom-format 백업을 만들고, 출력된 정확한 archive 경로를 이후
두 명령에 사용한다. 기존 백업이나 파일명 추측을 재사용하지 않는다.

```bash
PRODUCTION_ENV_FILE=.env.production make production-origin-backup

BACKUP_FILE=backups/production/admission_YYYYMMDD_HHMMSS_PID.dump \
  PRODUCTION_ENV_FILE=.env.production make production-origin-backup-verify

BACKUP_FILE=backups/production/admission_YYYYMMDD_HHMMSS_PID.dump \
  PRODUCTION_ENV_FILE=.env.production make production-origin-restore-verify
```

archive, SHA-256, manifest의 결속과 원본 migration head를 운영 기록에 남긴다. 마지막 명령은
live network·volume·secret을 사용하지 않는 일회성 PostgreSQL에서 실제 restore를 검증한다.
세 단계가 같은 새 archive로 성공한 경우에만
`OIDC_BACKUP_RESTORE_CONFIRMED=VERIFIED`로 확인한다.

## 3. 승인된 활성화

```bash
OIDC_CHANGE_APPROVED=APPROVED \
OIDC_HOST_GATE_CONFIRMED=PASSED \
OIDC_BACKUP_RESTORE_CONFIRMED=VERIFIED \
PRODUCTION_ENV_FILE=.env.production \
make production-origin-oidc-up
```

target은 세 확인값이 하나라도 없으면 시작 전에 실패한다. 그 뒤 정확한 세 Compose 파일을
검증하고 현재 web 이미지를 빌드한 다음, OIDC secret이 mount된 일회성 컨테이너에서 운영
사전검사를 실행한다. 이 검사가 통과해야만 `--no-build`로 web 서비스를 기동한다. 서비스
시작 명령에는 DB migration이 포함되므로 이 단계부터 schema 변경이 발생할 수 있다.

## 4. 활성 상태 확인

```bash
PRODUCTION_ENV_FILE=.env.production make production-origin-oidc-status

PRODUCTION_ENV_FILE=.env.production \
PRODUCTION_URL=https://service.example.org \
PRODUCTION_CA_CERT=/approved/path/fullchain.pem \
make production-origin-oidc-check
```

검사는 공인 TLS·health·보안 헤더, Google authorization endpoint로 향하는 HTTPS redirect의
callback·state·nonce·PKCE S256 계약, live DB migration head를 확인한다. redirect query의
client ID, state, nonce, challenge 값은 출력하지 않는다. 이어 실제 브라우저에서 Google
가입 계정이 `MEMBER/PENDING_APPROVAL`로 접수되고 관리자 승인 전 보호 기능에 접근하지
못하는지 확인한다. 합성 callback sentinel이 호스트·앱 로그에 남지 않는지도 다시 확인한다.

## 5. OIDC만 비활성화

```bash
OIDC_CHANGE_APPROVED=APPROVED \
PRODUCTION_ENV_FILE=.env.production \
make production-origin-oidc-disable
```

이 target은 `GOOGLE_OIDC_ENABLED=false`를 강제하고 OIDC override와 두 secret mount를 제거한
채 기존 이미지로 web 컨테이너를 재생성한다. 이미지를 빌드하거나 DB를 이전 상태로
되돌리지 않는다.
따라서 공급자 장애·설정 오류 때 Google 진입점만 닫고 현재 로컬 인증과 현재 schema를
유지하는 복구 절차다.

## 6. 애플리케이션과 DB 롤백

활성화 과정에서 migration이 실행된 뒤에는 **image-only rollback을 금지**한다. 먼저 변경
직전 archive를 승인된 실제 복구 절차로 live DB에 복원하고 checksum, manifest migration
head, health를 별도로 검증한다. 그 확인이 끝난 뒤에만 불변 image ID를 사용한다.

```bash
ROLLBACK_DATABASE_RESTORE_CONFIRMED=RESTORED_AND_VERIFIED \
ROLLBACK_APP_IMAGE=rollback-pre-change \
ROLLBACK_APP_IMAGE_ID=sha256:<approved-id> \
PRODUCTION_ENV_FILE=.env.production \
make production-origin-rollback-app
```

DB 복원 자체는 Make target이 자동 실행하지 않는다. rollback target도 image ID가 정확히
일치할 때만 `--no-build`와 구버전 관리자 bootstrap 비활성화로 기동한다. 실패 시점, 백업
digest, 복원 head, 배포 image ID, OIDC 비활성화 여부를 변경 기록에 남긴다.
