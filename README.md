# 2027 전문대 입시 상담 앱

학생과 교사가 로그인 없이 1회 성적 계산을 시작할 수 있는 Flask 기반 전문대 입시 상담 보조 시스템입니다. 이 시스템은 합격 예측기가 아니며, 전형별 지원자격을 먼저 판정한 뒤 근거가 확인된 전형만 결정론적으로 계산합니다.

현재 공개 핵심 흐름은 첫 화면에서 바로 시작하는 `성적 직접 입력·표 붙여넣기·CSV/XLSX 업로드 → 추출값 검수 → 대학·학과 검색 및 비교 선택 → 지원자격 판정 → 대학별 반영 평균등급과 2026 공개 입시결과 참고 → 계산 trace와 학생용·교사용 A4`입니다. 이름·학번·학교명을 요구하지 않으며, 1회 입력은 30분 만료·새 계산·완료 시 삭제됩니다. 공개 상담은 로그인 없이 끝까지 이용하고, 저장할 때만 학생·교사 또는 교사 기능을 겸하는 주 관리자 계정으로 로그인합니다.

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
- 주 관리자: 교사 학급·학생 성적·상담·개인 BYOK 업무를 겸하며, 회원 역할·상태, 공개 기준정보·규칙, 연도별 입시결과 import·제한형 포털 수집, PDF·PNG·JPG·CSV·XLSX 근거 문서 등록·검증 관리

학생·교사 신규 가입은 이메일과 비밀번호를 사용하며, 이메일 소유 확인과 관리자 승인을 모두 마친 뒤 저장 기능을 사용합니다. Phase 19 이전 계정은 기존 아이디 로그인을 유지하고 계정 보안 화면에서 실제 이메일을 인증할 수 있습니다. 사용자는 같은 화면에서 현재 비밀번호를 재확인해 비밀번호를 변경하고, 검증 이메일로 일회용 비밀번호 재설정 링크를 받을 수 있습니다. Google 계정은 로그인한 로컬 계정에서 다시 비밀번호를 확인한 뒤 같은 검증 이메일의 Google subject를 명시적으로 연결합니다. 이메일이 같다는 이유만으로 계정이나 학생·성적·상담 자료를 자동 병합하지 않습니다.

운영 로그인 화면의 `전체 기능 체험` 링크는 `/demo/`의 격리된 체험 서비스로 이동합니다. 여기서는 학생 `demo-student`, 교사 `demo-teacher`, 주 관리자 `demo-main-admin`, 보조 관리자 `demo-assistant-admin`을 버튼 한 번으로 시작하거나 화면에 표시된 공통 비밀번호로 로그인할 수 있습니다. 네 계정은 읽기 전용 구경 계정이 아닙니다. 각 역할에 허용된 성적·학급·학생·상담·BYOK·계정 보안·관리 기능을 직접 입력하고 저장하며 다시 확인할 수 있습니다.

체험 계정은 공개 계산의 필수 입구가 아닙니다. 공개 성적 계산·대학 선택·결과 비교·A4 출력은 로그인 없이 끝까지 이용할 수 있고, 결과를 다시 열어 보관하려는 경우에만 계정 저장을 선택합니다.

체험 서비스의 대학·학과·전형은 2026 공개 자료 42개 대학·1,048개 학과 선택지에 기존 2025 공개 자료를 합친 최종 43개 대학·1,079개 학과 선택지·5,092개 전형입니다. 2025·2026 입시결과도 검수한 공개 seed를 그대로 사용합니다. 실제 자료가 존재하지 않거나 공개하면 안 되는 개인 영역인 학급·학생·성적·교내 지원 결과만 `체험용 합성 익명 자료`라고 명시하고, 사용자가 새로 추가·수정할 수 있게 했습니다. 즉 대학 데이터까지 임의의 가상 값으로 대체하지 않습니다. 메일은 외부로 보내지 않고 체험 메일함에서 인증·재설정 링크를 열며, Google 연결은 실제 Google 계정 없이 동의 화면과 계정 연결 DB 흐름을 실행합니다. 크롤링은 2026 공개 seed를 포털 응답처럼 제공해 원문→미리보기→검수 흐름을 재현합니다. BYOK 키와 입력값은 운영과 다른 체험 DB·암호화 키·세션·업로드 영역에만 저장됩니다.

체험 공간은 여러 방문자가 함께 쓰므로 실제 이름·이메일·API 키는 입력하지 말아야 합니다. 기준 로그인 정보는 새 체험 시작 때 복구되며, 전체 공간은 운영자가 `make demo-reset`으로 공개 seed와 합성 초기자료 상태로 되돌릴 수 있습니다. 보조 관리자는 승인 대기 계정 승인만 가능하고 학급·성적·상담·BYOK·교내 결과·역할 변경·입시자료 등록·크롤링은 금지됩니다. 주 관리자만 관리자 기능과 교사 업무를 함께 사용할 수 있습니다.

SMTP와 Google OIDC는 외부 자격증명이 준비되기 전까지 기본 비활성 상태입니다. SMTP는 `docker-compose.smtp.yml`, Google은 `docker-compose.google-oidc.yml` override와 Git 제외 secret 파일로만 활성화합니다. 인증·재설정 링크는 요청 Host가 아니라 고정 `PUBLIC_BASE_URL`을 사용하고 원문 token은 DB 대신 SHA-256 digest로만 저장합니다.

두 기능을 운영에서 함께 활성화할 때는 `PRODUCTION_SECRETS_DIR`에 권한 `0600`인 `smtp_username`, `smtp_password`, `google_oidc_client_id`, `google_oidc_client_secret` 파일을 준비하고, Git 제외 `.env.production`에는 비밀값이 아닌 `SMTP_HOST`, `SMTP_PORT`, `EMAIL_FROM_ADDRESS`, `GOOGLE_REDIRECT_URI`만 설정합니다. 저장소의 host Nginx 설정 설치·`nginx -t`·reload, 변경 직전 DB 백업과 격리 복원을 먼저 완료한 뒤 아래 전용 target을 사용합니다. 이 target은 SMTP와 Google override를 항상 함께 유지하므로 한 기능을 켜면서 다른 기능의 secret mount를 제거하지 않습니다.

```bash
ACCOUNT_AUTH_CHANGE_APPROVED=APPROVED \
ACCOUNT_AUTH_HOST_GATE_CONFIRMED=PASSED \
ACCOUNT_AUTH_BACKUP_RESTORE_CONFIRMED=VERIFIED \
PRODUCTION_ENV_FILE=.env.production \
make production-origin-account-auth-preflight

# up은 같은 preflight를 항상 다시 실행한 뒤 서비스를 교체합니다.
ACCOUNT_AUTH_CHANGE_APPROVED=APPROVED \
ACCOUNT_AUTH_HOST_GATE_CONFIRMED=PASSED \
ACCOUNT_AUTH_BACKUP_RESTORE_CONFIRMED=VERIFIED \
PRODUCTION_ENV_FILE=.env.production \
make production-origin-account-auth-up

PRODUCTION_ENV_FILE=.env.production \
PRODUCTION_URL=https://service.example.org \
PRODUCTION_CA_CERT=/approved/path/fullchain.pem \
make production-origin-account-auth-check

# 공급자 장애 시 두 외부 인증 기능과 secret mount를 함께 제거합니다.
ACCOUNT_AUTH_CHANGE_APPROVED=APPROVED \
PRODUCTION_ENV_FILE=.env.production \
make production-origin-account-auth-disable
```

preflight는 두 override의 필수값과 네 secret 파일 mount를 확인하고, 새 이미지를 빌드한 뒤 일회성 컨테이너에서 SMTP·Google 기능이 모두 production fail-closed 검사를 통과하는지 확인합니다. 배포 후 check는 공인 HTTPS, Google redirect 계약, 실행 중인 두 기능의 구성과 migration head를 확인합니다. 실제 SMTP 수신과 Google 동의·연결은 승인된 합성 계정으로 별도 인수 확인합니다. disable은 현재 이미지·DB를 유지한 채 두 외부 기능과 secret mount만 함께 제거합니다. 외부 자격증명이 없는 기본 배포에서는 base compose의 두 기능이 모두 비활성이므로 preflight/up을 실행하지 않습니다.

교사와 주 관리자는 이름·학번 대신 학급 내부 비식별 코드를 사용하며 학생에게 24시간 유효한 일회용 연결 코드를 발급합니다. 학생이 전체 성적·상담 공유 범위를 확인하고 직접 동의한 뒤에만 연결되며, 연결 중 상대 소유 자료는 읽기 전용입니다. 연결 해제, 계정 정지 또는 교사 기능이 없는 역할로 변경되면 공유와 미사용 코드가 즉시 폐기되고 원본 소유권은 바뀌지 않습니다. `TEACHER ↔ ADMIN` 전환은 같은 교사 기능 범위이므로 기존 학급 연결을 보존하고, `ASSISTANT_ADMIN` 전환 시에는 교사 연결과 미사용 코드를 폐기합니다.

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
make test-phase19-e2e  # URL과 PHASE19_ACCOUNT_IDENTIFIER/PASSWORD 필요
make test-phase20-e2e  # PHASE20_E2E_URL 필요
make check
```

격리 체험 런타임은 운영 secret·DB·volume을 참조하지 않는 별도 Compose 프로젝트입니다. 최초 한 번 설정을 만들고 실행한 뒤 상태를 확인합니다. `demo-reset`은 고정된 체험 프로젝트와 체험 DB volume만 삭제·재생성하며 운영 DB에는 접근하지 않습니다.

```bash
make demo-bootstrap
make demo-up
make demo-check
make demo-status

# 체험 입력을 모두 지우고 기준 상태로 재생성할 때만 실행
make demo-reset
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

Phase 18의 교사 기능을 겸하는 비데모 주 관리자, 학급 연결 연속성, 운영 계정 BYOK 절차는 [작업 카드](tasks/PHASE_18_TEACHER_CAPABLE_MAIN_ADMIN.md)에 기록되어 있습니다.

Phase 19의 이메일 로그인·소유 확인·비밀번호 변경/재설정·명시적 Google 연결 경계는 [작업 카드](tasks/PHASE_19_ACCOUNT_SECURITY.md)에 기록되어 있습니다.

Phase 20의 네 역할 전체 기능 체험, 운영 격리, 공개 입시자료와 합성 개인정보의 구분은 [작업 카드](tasks/PHASE_20_FULL_DEMO_SANDBOX.md)에 기록되어 있습니다.

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
