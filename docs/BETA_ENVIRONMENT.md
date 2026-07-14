# 내부 베타 컨테이너

베타는 알파 검증을 통과한 동일 애플리케이션을 독립 Compose 프로젝트 `junior-college-admission-beta`에서 실행한다. Flask 개발 서버 대신 Gunicorn WSGI를 사용하고, `db-beta`와 PostgreSQL·업로드 named volume을 알파 및 운영 환경과 분리한다. 호스트에는 loopback 앱 포트만 공개한다.

## 진입 조건

- 알파 앱·PostgreSQL healthcheck와 Alembic `head`
- 전체 `make check`
- 합성 seed 기반 알파 Playwright 실패 0건
- 비식별 외부 LLM smoke 또는 명시적인 공급자 보류 판정
- 실제 학생 자료·원본 입시자료·운영 비밀값 Git 포함 0건

## 준비와 시작

`.env.example`의 `BETA_*` 항목만 Git 제외 `.env.beta`에 설정한다. 알파·운영 비밀값을 재사용하지 않는다. `BETA_ADMIN_PASSWORD_HASH`는 `$` 문자가 Compose 변수로 해석되지 않도록 값 전체를 작은따옴표로 감싼다. 공급자 API 키는 Compose나 이미지에 넣지 않고 관리자 BYOK 화면을 통해 저장한다.

```bash
make beta-up
make beta-status
make beta-check
```

`beta-check`는 HTTP health, Alembic 현재 revision과 Gunicorn 설치 상태를 확인한다. worker 수는 기본 2, thread 수는 worker당 2이며 부하 측정 없이 임의로 늘리지 않는다.

## 브라우저 인수

```bash
BETA_ADMIN_USERNAME=synthetic-admin \
BETA_ADMIN_PASSWORD=synthetic-password \
make beta-e2e
```

합성 상담 seed와 일회성 업로드 검수 세션이 준비된 경우 `make beta-e2e-full`로 전체 상담·출력·업로드 흐름을 확인한다. 실제 학생 자료나 실제 대학 규칙은 사용하지 않는다.

## 종료와 보존

```bash
make beta-logs
make beta-down
```

`beta-down`은 컨테이너만 중지하고 volume을 삭제하지 않는다. DB 초기화와 volume 삭제는 별도 명시 승인 없이는 수행하지 않는다.

## 실제 서비스 전환 차단 조건

- reverse proxy·TLS·허용 호스트·보안 헤더의 배포 환경 검증 미완료
- secret manager 주입·회전·폐기 리허설 미완료
- 공식 보유기간·삭제 예외·백업·복구 정책 미승인
- 최종 모집요강의 출처·쪽·골든·사람 승인 미완료
- 실제 게시 버전 교체와 롤백 리허설 미완료
- 합성 업로드 검수 세션을 포함한 Playwright 실패 또는 skip
- Critical·High 결함 존재

내부 베타 통과는 실제 서비스 배포의 자동 승인이 아니다. 위 조건과 변경창·담당자·롤백 책임자가 확인된 뒤 별도 운영 전환 게이트를 통과해야 한다.

2026-07-14 합성 베타 리허설에서 Gunicorn 23, PostgreSQL 17, Alembic `head`, HTTP health와 상담·BYOK·A4 Playwright 8건을 확인했다. 별도 합성 OCR 업로드 검수 세션의 데스크톱·모바일·무JavaScript Playwright 3건도 통과해 브라우저 인수 결과는 총 11건 실패·skip 0이다.
