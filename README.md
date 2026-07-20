# 2027 전문대 입시 상담 앱

학생과 교사가 로그인 없이 1회 성적 계산을 시작할 수 있는 Flask 기반 전문대 입시 상담 보조 시스템입니다. 이 시스템은 합격 예측기가 아니며, 전형별 지원자격을 먼저 판정한 뒤 근거가 확인된 전형만 결정론적으로 계산합니다.

현재 공개 핵심 흐름은 첫 화면에서 바로 시작하는 `성적 직접 입력·표 붙여넣기·CSV/XLSX 업로드 → 추출값 검수 → 대학·학과 검색 및 비교 선택 → 지원자격 판정 → 대학별 반영 평균등급과 2026 공개 입시결과 참고 → 계산 trace와 학생용·교사용 A4`입니다. 이름·학번·학교명을 요구하지 않으며, 1회 입력은 30분 만료·새 계산·완료 시 삭제됩니다. 공개 상담은 로그인 없이 끝까지 이용하고, 저장할 때만 학생 또는 교사 계정으로 로그인합니다.

공개 선택 범위는 사용자 제공 공개 2026 자료의 42개 대학·1,048개 지역/주야 구분 학과와 기존 동양미래대학교를 합친 43개 대학입니다. 제공된 4,970행은 모두 선택 기준정보로 보존하고, 척도와 범위가 검증된 4,094행만 2026 참고 결과로 게시합니다. `RANK_GRADE` 3,562행은 석차등급으로 표시하며 `CSAT_GRADE` 208행과 `POINT_SCORE` 324행은 학생부 반영등급과 직접 비교하지 않는 참고자료입니다. 기존 2025 결과 482행도 연도 선택으로 유지합니다. 2026 결과를 2027 모집요강이나 계산 규칙으로 복사하지 않으며, 공식 근거가 확인된 규칙만 `VERIFIED_SOURCE`로 실행합니다.

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

## 공개 계산과 계정 경계

- 서비스: `https://admission.memilmuk82.com`
- `/`: 별도 홍보 페이지 없이 공개 계산 화면으로 이동
- 공개 상담: 직업위탁 재학생을 기본값으로 두고 1·2학년 원적교 성적과 3학년 위탁 성적을 서버에서 구분합니다. 3학년 2학기는 선택 입력이며 비워도 대학 선택과 적용 가능한 계산을 계속합니다. 일반고 졸업생은 명시적 예외 프로필입니다.
- 학생 계정: 자신의 성적·상담 저장, 교사 학급 연결과 읽기 전용 공유자료 확인, 개인 BYOK 키·검증 결과 상담 문장 관리
- 교사 계정: 학과·학급·비식별 학생 명단과 성적, 학생별 저장 상담자료·BYOK 초안, 별도 비식별 교내 지원 결과 관리
- 보조 관리자: 승인 대기 일반·학생·교사 계정 승인만 수행
- 주 관리자: 회원 역할·상태, 공개 기준정보·규칙, 연도별 입시결과 import·제한형 포털 수집, PDF·PNG·JPG·CSV·XLSX 근거 문서 등록·검증 관리

학생·교사 가입은 역할을 명시해 승인 대기로 생성하며, 관리자 승인 후 저장 기능을 사용합니다. 로그인 화면에는 학생 `demo-student`, 교사 `demo-teacher`, 주 관리자 `demo-main-admin`, 보조 관리자 `demo-assistant-admin`과 공통 공개 비밀번호가 표시됩니다. 데모 관리자는 실제 회원·업로드 원문·내부 결과를 볼 수 없는 읽기 전용 showcase이며, 데모 학생·교사의 BYOK 키는 브라우저 로그인 세션별 actor에 암호화 저장되고 로그아웃 시 삭제됩니다. 실제 학생·교사 키는 각 계정 actor에 암호화 저장됩니다. 네 데모 계정은 공개 계산의 필수 입구가 아닙니다. Google OIDC는 기본 비활성 상태입니다.

교사는 이름·학번 대신 학급 내부 비식별 코드를 사용하며 학생에게 24시간 유효한 일회용 연결 코드를 발급합니다. 학생이 전체 성적·상담 공유 범위를 확인하고 직접 동의한 뒤에만 연결되며, 연결 중 상대 소유 자료는 읽기 전용입니다. 연결 해제나 계정 정지·역할 변경 시 공유와 미사용 코드가 즉시 폐기되고 원본 소유권은 바뀌지 않습니다.

## 검증

```bash
make test-unit
make test-integration
make lint
make validate-rules
make check-sensitive-data
make test-phase14-e2e
make test-phase16-e2e  # DATABASE_URL과 PHASE16_E2E_URL 필요
make test-phase17-e2e  # PHASE17_E2E_URL 필요
make check
```

기준 XLSX 계약은 원본 값을 출력하지 않는 다음 명령으로 확인합니다.

```bash
python scripts/verify_phase14_reference_xlsx.py
```

입시결과의 수집 단계, 품질 차단, 과거 규칙 버전 연결은 [Phase 6 입시결과 수집·분석 계약](docs/PHASE_6_ADMISSION_RESULTS.md)에 정리되어 있습니다.

CSV/XLSX 자동 탐지, 2027 결과→2028 상담 연도 제안, 검수·게시·이전 버전 보존 절차는 [Phase 14 연도별 공개 입시결과 import](docs/PHASE_14_ADMISSION_RESULT_IMPORT.md)에 정리되어 있습니다.

관리자 import 화면의 전문대학포털 수집은 기존 노트북에서 확인한 요청·표 구조를 제한형 어댑터로 옮긴 것입니다. 응답은 기존 raw→staging→review→publish 흐름으로만 전달하며 timeout·재시도·rate limit·페이지·응답 크기 상한을 둡니다. 실제 전체 포털 수집은 이 저장소 구현 과정에서 실행하지 않았습니다.

Phase 15 구조 재설계 범위와 비변경 경계는 [작업 카드](tasks/PHASE_15_STRUCTURE_REBUILD.md)에 기록되어 있습니다. 새 Python·Node·시스템 의존성과 Docker·Compose·Nginx 구성 변경은 없습니다.

Phase 16 역할별 업무공간·학생/교사 연결·관리자 권한 경계는 [계정 협업 계약](docs/PHASE_16_ACCOUNT_COLLABORATION.md)과 [작업 카드](tasks/PHASE_16_ACCOUNT_COLLABORATION.md)에 기록되어 있습니다.

Phase 17의 위탁 기본 성적표, 2026 공개 참고결과, 전체 대학 선택, 네 역할 데모와 세션 BYOK 경계는 [작업 카드](tasks/PHASE_17_PUBLIC_VERIFICATION.md)에 기록되어 있습니다.

Phase 9의 비식별 payload, 사용자별 키 암호화, 교사 확정 경계는 [BYOK AI 보안·데이터 계약](docs/BYOK_AI.md)에 정리되어 있습니다.

## 데이터 취급

- 원본 PDF·엑셀, 학생 개인정보, 업로드 파일, OCR 파생물, 로컬 DB 파일, `.env`, API 키는 Git과 Docker 이미지에 포함하지 않습니다.
- 외부 공개가 가능한 정제·검수 완료 전형 데이터만 `data/seed/`에 둘 수 있습니다.
- `data/raw/`, `data/staging/`, `data/published/`, `uploads/`, `instance/`의 실제 내용은 로컬 전용입니다.
- 실제 학생 자료는 테스트 픽스처로 사용하지 않습니다. 테스트에는 합성 익명 자료만 허용합니다.

상세 요구사항의 기준 문서는 저장소 루트의 기존 문서 두 개입니다. 두 문서는 수정·이동하지 않고 원문 그대로 유지합니다.


## PostgreSQL 운영

`docker-compose.yml`의 웹 원본은 호스트 Nginx만 접근하도록 `127.0.0.1:8000`에 바인딩합니다. 외부 인터페이스에 8000번을 직접 공개하지 않습니다. `db` 서비스도 호스트 포트를 열지 않고 전용 `backend` 네트워크에서 `db:5432`로만 접근하며, 데이터는 `postgres_data` named volume에 유지됩니다. 기본 Compose는 로컬 개발용이며 실제 서비스에는 Gunicorn production 구성을 사용합니다.

실제 `SECRET_KEY`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DATABASE_URL`는 Git에서 제외되는 `.env`에 설정합니다.

```bash
# DB healthcheck 통과 후 web 시작
docker compose up --build

# pg_dump custom-format 백업, 결과는 Git 제외 backups/에 저장
./scripts/backup_postgres.sh

# PostgreSQL Flask-Migrate/Alembic 마이그레이션
docker compose run --rm web uv run flask --app wsgi db upgrade
```
