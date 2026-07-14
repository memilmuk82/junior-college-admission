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

비밀값은 Git, Compose 파일, 이미지, 명령 인자와 로그에 기록하지 않는다. 실제 배포 환경에서는 secret manager가 프로세스 환경으로 주입해야 한다.

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
