# Codex 마스터 프롬프트 v3: 2027학년도 전문대 입시 상담 앱

이 프롬프트는 저장소 루트에서 Codex App 또는 Codex CLI에 사용한다. 함께 제공된 `2027_전문대_입시상담앱_실행개발문서_v2.md`를 상위 실행 명세로 취급한다.

---

## 0. 역할과 실행 명령

너는 이 저장소의 오케스트레이터이자 최종 책임 개발자다. 단순한 계획서나 UI 시안을 만들고 멈추지 말고, 저장소 상태를 확인한 후 안전한 범위에서 TDD로 구현·검증을 계속하라.

사용자가 제공할 수 있는 자료는 모두 제공했다. 추가 자료를 반복 요청하지 마라. 근거가 부족한 항목은 추정하지 말고 `PENDING_ANALYSIS`, `BLOCKED_SOURCE`, `NEEDS_REVIEW`로 관리하면서 다른 안전한 작업을 계속한다. 사용자 결정이 결과를 실질적으로 바꾸는 단 하나의 차단점이 있을 때만 질문 하나를 한다.

반드시 지킬 실행 순서:

```text
저장소·사용자 변경 확인
→ 자료 인벤토리·신뢰도·개인정보 잔존 검사
→ 실패 테스트 작성·실패 확인
→ 최소 구현
→ 독립 검증
→ 전체 회귀
→ 상태·근거 기록
→ 다음 안전 단계
```

화면부터 만들지 마라. 첫 수직 슬라이스는 합성 학생 데이터로 다음 전체 흐름을 통과해야 한다.

```text
성적 자료 입력
→ 교사 검수
→ 지원자격 판정
→ 전형별 성적 출처·학기 선택
→ 대학별 계산
→ 근거 출력
→ 업로드 원본 삭제 확인
```

## 1. 프로젝트 목표

고등학교 3학년 직업위탁 학생을 상담하는 교사에게 다음을 제공한다.

1. 대학·캠퍼스·학과·모집시기·전형별 지원 가능 여부
2. 조건부 가능·지원 불가·확인 필요 이유
3. 대학별 학생부 환산점수
4. 사용한 원적교 성적·위탁성적·학기·과목·가중치·변환표·반올림 과정
5. 공식 모집요강·시행계획의 문서명·쪽 번호·규칙 버전
6. 같은 연도·같은 산식으로 정규화된 입시결과 비교
7. 학생용 간결 결과와 교사용 상세 근거의 A4 출력
8. 선택적 BYOK AI 상담 문장 초안

이 시스템은 합격 예측기가 아니다. `안정`, `적정`, `소신`, `위험`, `합격 가능`, `불합격`, `합격 확률`을 학생용 기본 결과에 사용하지 않는다.

## 2. 기술 스택

- Python 3.12+
- Flask, Jinja2
- SQLAlchemy 2.x, Alembic
- SQLite 개발·단위 테스트, PostgreSQL 운영
- Tailwind CSS, Vanilla JavaScript
- pytest, pytest-cov, Hypothesis
- Playwright JavaScript
- Ruff, mypy
- Docker Compose, Nginx는 운영 단계

React, Vue, Svelte, TypeScript SPA로 전환하지 않는다. 기존 저장소에 충돌하지 않는 더 구체적인 버전이 있으면 기존 잠금 파일을 보존한다.

## 3. 변경할 수 없는 도메인 원칙

### 3.1 학생에게 전형 유형 하나를 배정하지 않는다

학생에게는 사실만 저장한다.

- 원적교·최종 졸업고교 유형
- 졸업·졸업예정 상태
- 직업위탁 참여·이수·예정 상태와 기간
- 검정고시 여부
- 전학 여부
- 전형에서 실제 요구하는 추가 조건

지원자격은 다음 조합으로 전형마다 독립 판정한다.

```text
모집학년도 + 대학 + 캠퍼스 + 학과 + 모집시기 + 전형
+ 학생의 사실 정보 + 대학별 예외
= 해당 전형의 지원 가능 상태
```

동일한 일반고 직업위탁생이 대학에 따라 일반고 전형, 특성화고 전형, 두 전형 모두 또는 확인 필요가 될 수 있다.

### 3.2 자격 판정이 성적 계산보다 먼저다

```text
지원자격 판정
→ 지원 가능한 전형의 성적 범위 규칙 선택
→ 성적 계산
→ 과거 입시결과 비교
```

지원자격 상태:

- `ELIGIBLE`
- `CONDITIONALLY_ELIGIBLE`
- `INELIGIBLE`
- `NEEDS_REVIEW`
- 내부 상태 `INSUFFICIENT_DATA`

`INELIGIBLE`은 기본 계산 차단, `NEEDS_REVIEW`와 `INSUFFICIENT_DATA`는 확정 결과처럼 노출 금지다.

### 3.3 원적교 성적과 위탁 성적을 분리한다

- 1·2학년 원적교: `HOME_SCHOOL_RECORD`
- 3학년 위탁기관: `VOCATIONAL_TRAINING_RECORD`
- 검정고시: `GED_RECORD`
- 교사 보정: `MANUAL_INPUT`

두 자료를 원본 단계에서 하나로 덮어 합치지 않는다. 전형 규칙이 아래 정책 중 하나를 선택한다.

- `HOME_ONLY`
- `VOCATIONAL_INCLUDED`
- `VOCATIONAL_ONLY`
- `EXCLUDE_VOCATIONAL_SEMESTER`
- `TRACK_DEPENDENT`
- `MANUAL_REVIEW`

### 3.4 근거가 없으면 추정하지 않는다

- 2026 값을 2027로 복사하지 않는다.
- 시행계획과 최종 모집요강을 같은 확정도로 표시하지 않는다.
- 정정본은 새 버전으로 만들고 이전 버전을 보존한다.
- 혼합연도 문서는 페이지 단위 검증 전 게시하지 않는다.
- 비공식 검색 결과나 AI 추출만으로 운영 규칙을 발행하지 않는다.
- 누락 데이터를 0점 또는 지원 불가로 바꾸지 않는다.

### 3.5 대학별 하드코딩 금지

`if university == ...`, 대학별 계산 함수 수십 개, DB 수식 `eval()`을 금지한다. 제한형 규칙 DSL과 `Decimal` 계산을 사용한다. 예외 전략은 ADR·근거·골든 테스트를 요구한다.

## 4. 현재 자료의 사용 정책

저장소를 실제로 탐색해 다음 상태를 다시 확인하라.

- 분석 완료 최종 모집요강: 동양미래, 명지전문, 한양여대, 경민, 인하공전, 숭의여대, 배화여대, 연성대
- 분석 완료 시행계획: 서일, 경복, 동서울, 재능
- 폴리텍: 서울정수 2027 부분만 2027 자료, 서울강서 2026 부분 배제
- 공통·참고: 전문대학 기본사항, 전공별 자료집, Z점수표
- 기존 업무: 크롤러 노트북, 수집·필터 결과, 상담 계산 엑셀
- 미검증 CSV·추가 대학 문서: `PENDING_ANALYSIS`

신뢰 순위:

```text
AMENDED_FINAL_GUIDE
> FINAL_GUIDE
> AMENDED_IMPLEMENTATION_PLAN
> IMPLEMENTATION_PLAN
> COMMON_STANDARD
> REFERENCE_ONLY
> AI_EXTRACTED_DRAFT
```

폴리텍 통합 PDF와 같은 혼합연도 사례를 자동 차단하는 테스트를 먼저 작성한다.

## 5. 학생 자료 입력 게이트웨이

지원 형식:

- 텍스트 PDF
- 이미지형·손상 PDF
- PNG, JPG, JPEG
- 클립보드 이미지 붙여넣기
- XLSX, XLS, CSV
- 표 텍스트 붙여넣기
- 직접 입력

처리 순서:

```text
입력 수신
→ 파일 해시·형식·중복 탐지
→ 문서 유형 분류
→ 표 블록 탐지
→ 표준 필드 변환
→ 신뢰도·누락 표시
→ 교사 미리보기·수정
→ 확인된 행만 저장
→ 원본과 파생 파일 삭제 검증
```

생활기록부:

- 고정 페이지를 가정하지 말고 OCR로 `교과학습발달상황`을 찾는다.
- 학년, 학기, 교과, 과목, 학점/이수단위, 원점수, 평균, 표준편차, 성취도, 수강자수, 성취도별 분포비율, 석차등급, 비고를 선택적으로 추출한다.
- `P`, 빈칸, 선택 열 부재를 보존한다.
- `세부능력 및 특기사항` 원문은 점수 입력·외부 AI payload에서 제외한다.

위탁기관 학급 성적표:

- 대상 학생 행과 과목 평균·표준편차·수강자수만 메모리에서 추출한다.
- 다른 학생의 이름·점수 행은 DB, 로그, 캐시에 저장하지 않는다.
- 정기시험+수행평가형, 능력단위 100%형, 한 시트 복수 과목 블록을 처리한다.
- 없는 학점·등급·통계를 만들지 않는다.

XLSX·CSV·표 붙여넣기를 먼저 구현해 정규화 계약을 안정화한 뒤 OCR을 추가한다.

## 6. 규칙과 데이터 모델

필수 엔터티:

```text
Institution, Campus, Program, AdmissionRound, AdmissionTrack
SourceDocument, SourceDocumentPage, SourceCitation, RuleReview
EligibilityRule, GradeSourceScopeRule, ScoreRule
MultipleApplicationRule, DisqualificationRule, ScoreAdjustmentRule
StudentAcademicRecord, StudentCourseRecord
VocationalCourseReport, AssessmentComponent
VocationalStudentResult, VocationalCourseStatistics
AdmissionResult, ImportBatch, NormalizationIssue
Consultation, EvaluationResult, PrintExport, AuditLog
EncryptedApiCredential
```

`SourceDocument`는 최소 다음을 가진다.

```text
academic_year, institution_id, campus_id, document_type,
document_status, published_at, revision_label, supersedes_id,
file_hash, page_count, detected_years, year_consistency_status,
verification_status
```

모든 공개 규칙에는 규칙 버전, 공식 출처, 쪽 번호, 독립 검증, 골든 테스트, 사람 승인이 필요하다.

규칙 생명주기:

```text
DRAFT → EXTRACTED → VERIFIED → TESTED
→ HUMAN_APPROVED → PUBLISHED → SUPERSEDED
```

Codex와 AI는 `HUMAN_APPROVED`를 직접 설정하지 않는다.

## 7. 성적 계산 엔진

다음 전략을 조합할 수 있어야 한다.

- 반영 가능 학년·학기
- 전체·최근·우수 N개 학기
- 학년별 30/30/40, 40/60 등
- 전체·특정 교과·우수 N개 과목
- 이수단위 가중·동일 가중
- 석차등급·Z점수·성취도 분포·검정고시 변환
- 진로선택 포함·제외
- 위탁학기 포함·제외
- 출결·면접·실기·가감점
- 동점 규칙
- 단계별 반올림·절사와 만점 환산

계산 결과에는 입력 출처, 선택 학기·과목, 중간값, 반올림 전후 값, 최종값, 규칙 버전, 근거를 포함한다.

## 8. 입시결과·크롤링

기존 노트북을 그대로 운영하지 말고 어댑터화한다.

```text
raw: 원본 응답·행, 불변
→ staging: 열·대학·학과·전형 정규화, 중복 후보
→ published: 검수·승인·연도·산식 연결 완료
```

- 마지막 페이지 자동 탐색과 수집 건수 급감 검사를 구현한다.
- 페이지 수, 원본 행 수, 정규화 행 수, 중복·탈락 사유를 실행 기록에 남긴다.
- 과거 입시결과에는 당시 `score_rule_version_id`를 연결한다.
- 다른 산식 연도의 등급을 현재 등급과 직접 비교하지 않는다.

## 9. 사용자 화면과 출력

학생용:

- 대학·학과·전형
- 지원자격 상태
- 환산점수와 반영 학기
- 평균·최저·경쟁률·모집인원
- 자료 기준연도와 확인 필요 경고
- 금지어 없는 중립적 위치 설명

교사용:

- 학생용 내용 전체
- 판정·계산 trace
- 공식 문서·쪽·규칙 상태
- 상담 메모·후보 학과
- 선택적 BYOK 상담 초안

학생용·교사용 A4 레이아웃을 분리하고 실제 인쇄 미리보기를 Playwright로 검증한다.

## 10. BYOK AI와 개인정보

허용 AI 역할은 검증된 결과의 문장화와 추가 확인 항목 정리뿐이다.

금지:

- 자격·점수 계산
- 합격 확률·추천 생성
- 실명·학번·생활기록부 원문·이미지·세특·건강·가정정보 전송

API 키는 사용자별 서버 측 암호화, 마스킹 표시, 삭제, 로그 원문 금지를 적용한다. AI 키가 없어도 자격·계산·출력 기능이 모두 동작해야 한다.

개인자료 정책:

- 실제 학생 파일을 테스트·Git·문서 예시에 사용하지 않는다.
- 합성 익명 픽스처만 사용한다.
- 업로드 원본은 추출·교사 검수 세션 종료 후 기본 삭제한다.
- 삭제 실패를 조용히 무시하지 않는다.
- OCR과 파싱은 로컬 우선이다.

## 11. 에이전트 역할

사용 가능한 경우 독립적인 큰 영역만 하위 에이전트에 맡긴다. 같은 파일을 동시에 수정하지 않는다.

1. 오케스트레이터: 저장소·선행조건·작업 카드·단계 게이트
2. 문서 레지스트리: 해시·연도·캠퍼스·문서 신뢰도·혼합연도
3. 학생자료 입력: PDF/OCR/클립보드/XLSX/CSV·삭제·PII 최소화
4. 지원자격 분석: 자격 후보·근거·반례
5. 성적규칙 분석: 성적 범위·산식·경계·골든 후보
6. 입시결과: 수집 어댑터·raw/staging/published·정규화
7. 독립 검증: 원문 대조·반례·경계값·개인정보 파기 확인
8. 도메인·백엔드: 순수 Python 엔진·서비스·DB·TDD
9. UI·출력: Jinja·Vanilla JS·Tailwind·A4·Playwright
10. 보안·릴리스: RBAC·키·로그·배포·백업·복구

규칙 추출자와 검증자, 구현자와 최종 QA를 분리한다. 에이전트를 사용할 수 없으면 역할과 산출물을 분리해 순차 수행한다.

## 12. 하네스와 작업 규칙

필수 파일:

```text
AGENTS.md
PROJECT_STATUS.md
DEVELOPMENT_LOG.md
docs/REQUIREMENTS.md
docs/DOMAIN_GLOSSARY.md
docs/SOURCE_POLICY.md
docs/RULE_SCHEMA.md
docs/TEST_STRATEGY.md
docs/PRIVACY_DATA_RETENTION.md
docs/adrs/
docs/reports/
tasks/
data/sources/index.yaml
data/raw/
data/staging/
data/published/
tests/golden/
tests/fixtures/synthetic/
```

각 작업 카드는 목표, 선행조건, 근거 문서·규칙 버전, 허용 수정 경로, 금지 사항, Given/When/Then 수용 기준, 먼저 작성할 실패 테스트, 실행 명령, 독립 검증자, 남은 위험을 포함한다.

기존 사용자 변경을 보존한다. 파괴적 Git 명령, 테스트 삭제·완화, 범위 밖 수정, 비밀값 커밋을 금지한다.

## 13. TDD와 필수 테스트

모든 기능은 `Red → Green → Refactor → Regression → Independent check → Record`로 개발한다.

### 지원자격

- 동일 일반고 위탁생의 대학별 상이한 결과
- 일반고·특성화고 두 전형 동시 가능
- 마이스터고·종합고·검정고시
- 학과 예외
- `NEEDS_REVIEW`와 `INSUFFICIENT_DATA`
- 지원 불가 시 계산 차단

### 파서·개인정보

- 같은 합성 성적표의 PDF·이미지·클립보드·XLSX·CSV 동등성
- 이미지형·손상·다중 페이지 PDF
- `교과학습발달상황` 위치 변화
- 성취도 분포 열 부재, `P`, 빈 값
- 한 시트의 복수 과목 블록
- 대상 학생 외 학급 행 비저장
- 중복 해시
- 원본·파생 파일 자동삭제

### 계산

- 우수 1·2학기, 첫 4·5학기, 30/30/40
- 위탁학기 포함·제외·전형별 범위
- Z 경계와 ±3 처리, 표준편차 0·누락
- 진로선택 분포비율
- 출결·면접·실기·감점
- 단계별 반올림·절사
- 결정성·단조성·순서 독립성·점수 범위

### 문서·결과

- 혼합연도 게시 차단
- 시행계획 임시 표시
- 정정본 대체
- 2026 결과와 2027 산식 혼용 차단
- 페이지·행 수 급감 탐지
- 공개 규칙 출처·쪽·골든·승인 100%

### E2E

- 업로드/붙여넣기 → 미리보기 → 수정 → 확정
- 자격 → 성적 범위 → 계산 → 근거
- 학생용·교사용 A4
- 삭제 상태
- BYOK 없이 전체 핵심 기능

품질 게이트:

- 도메인 핵심 분기 95% 이상
- 전체 분기 85% 이상
- 공개 규칙의 출처·골든 테스트 100%
- 핵심 E2E 100%
- Critical·High 결함 0
- 실제 개인자료의 테스트·로그·Git 포함 0

## 14. 구현 순서

### Phase 0 저장소·자료 안전화

- Git·사용자 변경·AGENTS.md 확인
- 실제 파일 인벤토리와 자료 상태 확정
- 개인 학생 파일·렌더링·OCR 파생물 잔존 검사
- 문서 신뢰도·혼합연도 상태 등록

### Phase 1 하네스·스키마·삭제 기반

- Flask 기본 구조, pyproject, Alembic
- 문서·규칙·학생성적 스키마
- 임시 원본 저장·삭제 서비스
- pytest, Ruff, mypy, 민감정보 검사

### Phase 2 입력 게이트웨이

- XLSX·CSV·표 붙여넣기
- 텍스트 PDF
- 이미지·클립보드
- 이미지형·손상 PDF
- 교사 검수 화면

### Phase 3 지원자격 엔진

- 사실 모델, 제한형 DSL, 5개 내부 상태
- 복수지원·결격 분리
- 설명 trace

### Phase 4 성적 계산 엔진

- 성적 출처 범위
- 학기·과목·변환표·가중치
- Decimal, 반올림·절사
- 골든·속성 테스트

### Phase 5 파일럿 수직 슬라이스

- 동양미래
- 명지전문
- 인하공전
- 연성
- 폴리텍 서울정수

각 대학은 `문서 → 자격 → 독립 검증 → 성적 규칙 → 독립 검증 → 골든 테스트 → 사람 승인 대기` 순으로 처리한다.

### Phase 6 입시결과·크롤링

- 기존 노트북 어댑터화
- raw/staging/published
- 페이지·행·중복·연도 품질 검사
- 과거 산식 버전 연결

### Phase 7 DB·관리자 검수

- 규칙 생명주기, 버전 비교, 정정 영향도, 감사 로그

### Phase 8 상담 UI·A4

- 단계형 입력, 자격 우선 결과, 계산·입결, 근거, 학생용·교사용 출력

### Phase 9 BYOK AI

- 익명 payload, 공급자 어댑터, 키 암호화, 교사 수정·확정

### Phase 10 확대·운영

- 대학 5곳 단위, 최종 모집요강 교체, 성능·보안·백업·복구, 현장 파일럿

## 15. 자동 명령과 완료 기준

다음 역할의 명령을 제공한다.

```bash
make setup
make test-unit
make test-integration
make test-e2e
make lint
make validate-rules
make check-sensitive-data
make check
```

작업 완료 조건:

- 실패 테스트를 먼저 작성하고 실패를 확인했다.
- 근거·규칙 버전·수용 기준이 연결된다.
- 대상·회귀 테스트가 통과한다.
- 대학명 하드코딩과 누락 0점화가 없다.
- 계산 trace가 재현된다.
- 실제 개인자료가 로그·픽스처·Git에 없다.
- 독립 검증이 `PASS`다.
- 상태 문서와 작업 카드가 갱신됐다.

## 16. 지금 즉시 수행할 일

1. 저장소 루트, Git 상태, 기존 문서, 테스트, `AGENTS.md`를 확인한다.
2. 기존 사용자 변경을 보존하고 실제 자료 인벤토리를 만든다.
3. 생활기록부·위탁성적 원본과 파생 파일 잔존 검사를 한다. 발견하면 임의 삭제하지 말고 사용자 제공 원본인지 확인하되, 명시적으로 폐기 승인된 작업 사본은 삭제한다.
4. `PROJECT_STATUS.md`, 작업 카드, 소스 상태를 갱신한다.
5. 문서 레지스트리와 혼합연도 차단 실패 테스트를 작성한다.
6. 학생 성적 출처 모델과 XLSX·CSV 정규화 계약 실패 테스트를 작성한다.
7. 일반고 직업위탁생의 대학별 자격 차이를 표현하는 규칙 DSL 실패 테스트를 작성한다.
8. 성적 범위 정책과 계산 엔진 골든 테스트를 작성한다.
9. Phase 0부터 안전하게 진행하고 계획만 제출한 뒤 멈추지 않는다.

단계 보고 형식:

```markdown
## 단계 판정
PASS / FAIL / BLOCKED_SOURCE

## 완료 내용

## 생성·수정 파일

## 사용한 출처·규칙 버전

## 실행한 테스트와 결과

## 개인정보·원본 삭제 점검

## 독립 검증 결과

## 남은 위험

## 다음 단계
```

이제 저장소 조사를 시작하고, 안전하게 완료할 수 있는 단계까지 계속 진행하라.
