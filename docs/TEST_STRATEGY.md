# 테스트 전략

Phase 0 검증 범위는 다음과 같다.

- Flask 앱 셸과 `/health` 응답
- Git 포함 대상의 원본 문서·스프레드시트·DB·환경 파일·API 키 패턴 검사
- `.gitignore`와 `.dockerignore` 정책의 수동 검토

후속 기능은 기준 문서에 따라 `Red → Green → Refactor → Regression → Independent check → Record` 순서를 적용한다.

## Phase 1 검증 범위

- 단위 테스트: Flask 셸, 임시 원본·파생물 삭제, 규칙 seed 계약
- PostgreSQL 17 통합 테스트: Alembic 최초 migration과 필수 테이블 전체
- Flask-Migrate 통합 테스트: `flask db upgrade`, schema drift 없는 `flask db migrate`
- PostgreSQL 제약 테스트: 혼합연도 문서 게시, 근거 없는 규칙 게시 차단
- 학생 성적 출처 분리 저장과 앱 팩토리 DB 연결
- Ruff 형식·정적 검사와 mypy 타입 검사
- Git 포함 대상 민감정보 검사

## Phase 2 완료 검증 범위

- 합성 CSV·표 붙여넣기의 표준 필드 변환
- 빈칸과 `P` 보존, 잘못된 숫자의 검수 이슈 분리
- 동일 입력 SHA-256 재현과 알 수 없는 열 값 미보존
- 합성 XLSX 복수 시트·앞부분 설명 행·머리글 미발견 검증
- 합성 CSV·XLSX 학급표의 대상 학생 외 행 제거와 식별자 미반환
- PostgreSQL에 확인 행만 저장하고 미확인 행은 제외
- 원본·파생물 삭제 성공과 삭제 실패 시 DB rollback
- `P`의 비수치 라벨 보존과 DB CHECK 제약
- 합성 텍스트 PDF의 교과 표 위치 변화와 페이지 trace
- 세부능력 및 특기사항 제외, 암호화·과대 PDF 거부
- `text_pdf` ImportBatch 저장과 Flask-Migrate schema drift 검사
- 합성 PNG·JPEG·클립보드 입력의 동일 정규화 결과와 signature 검증
- 이미지 픽셀 제한, 세부능력 및 특기사항 제외, OCR 검수 필수 표시
- 컨테이너 Tesseract `kor+eng` 언어팩과 실제 stdin OCR 실행
- 합성 다중 페이지 이미지형 PDF의 교과 구간 위치 변화와 페이지 trace
- EOF 누락 경미 손상 복구, 암호화·복구 불가·페이지 초과 PDF 거부
- PDFium 메모리 렌더링과 `scanned_pdf` ImportBatch 저장
- 검수 상태 파일의 크기·권한·직렬화와 원문 미보존
- SSR 행 수정·선택 저장·빈 선택·CSRF·폐기와 임시자료 삭제
- 검수 응답의 비공개 캐시·referrer·CSP 정책
- Playwright 데스크톱·모바일·JavaScript 비활성 사용자 흐름
- 브라우저 콘솔 오류, 모바일 가로 넘침, 입력·버튼의 접근 가능한 이름

## Phase 3 완료 검증 범위

- 같은 합성 일반고 직업위탁생의 전형별 독립 결과
- 일반고·특성화고 합성 전형의 동시 지원 가능 상태
- 마이스터고·종합고 직업계열·검정고시·학과 예외 사실
- 5개 지원자격 상태와 확정 결과 여부
- `all`·`any`·`not`의 누락값 3값 논리와 반례
- 허용하지 않은 사실·연산자·문자열 수식·추가 사실 이름 거부
- 비게시 또는 근거·검증·골든·사람 승인이 누락된 규칙 실행 거부
- 동일 사실·규칙의 설명 trace 재현과 실제 사실값 미포함
- 지원 불가·검토 필요·정보 부족 상태의 계산 진입 차단
- 전형별 활성 게시 규칙 단일 버전 PostgreSQL 제약과 Alembic drift 없음
- 게시 규칙 조회, DRAFT 제외, 규칙 없음·잘못된 payload의 명시적 실패
- 복수지원 총 횟수·캠퍼스 횟수·금지 조합과 불완전 이력 검토
- 결격 `CLEAR`·`DISQUALIFIED`·`NEEDS_REVIEW`·`INSUFFICIENT_DATA`
- 민감 결격 실제 값의 규칙 payload·trace·DB 비저장
- 게시 seed의 지원자격·복수지원·결격 payload 계약 검사

## Phase 4 진행 중 검증 범위

- 자격 미확정 상태의 DB 조회 이전 차단
- 원적교 전용·위탁 포함·위탁 전용·위탁학기 제외 정책
- 전형 의존·수동 검토 정책의 `NEEDS_REVIEW`
- 검증되지 않은 학기·과목 제외와 빈 범위 `INSUFFICIENT_DATA`
- `P` 원문 라벨 보존과 0점 변환 없음
- 선택 출처·학기·과목·제외 이유 trace
- 게시 성적 범위 규칙 조회·단일 활성 버전·Alembic drift
- 규칙 seed의 성적 범위 payload 검증
- 표준 성적 규칙 CSV의 UTF-8·UTF-8 BOM 왕복
- 고정 헤더·중복 업무키·행별 오류와 유효 행 분리
- TRUE/FALSE, 선택 코드, Decimal 범위·합계, 빈값과 0 구분
- 자유 수식 열·수식형 셀·canonical payload 추가 필드 거부
- 관리자 직접 생성 규칙의 동일 CSV 재내보내기
- 별도 Z점수 표의 열린 경계와 구간 중복 차단
- 전체·최초·최근·우수 N개 학기와 우수 N개 과목의 결정적 선택
- 학점 가중 학기 비교와 동일 점수 tie-break trace 재현
- 학년·학기 가중치의 상호 배타성, 누락·0·합계 오류 및 Decimal 계산
- 반올림·절사의 선언된 최종 단계 적용과 면접·실기 비합산
- `LOWER_IS_BETTER` 등급과 `HIGHER_IS_BETTER` 점수의 결정적 선택
- 전역 학기 가중치와 학년 내부 학기 가중치의 구분 및 계층 곱
- 학년별 최우수 학기 선택 후 학년 가중치 적용
- 학기 중간 반올림, 최종 반올림과 표시 전용 자릿수 분리
- 제한형 선형 환산과 자유 수식 부재
- Z점수 공식 버전·반올림·±3 절단·경계 포함 여부·표 버전 trace
- 참고 Z표의 `UNIVERSITY_OFFICIAL` 위장 차단
- `score_rules`의 전형별 활성 게시 버전 단일 PostgreSQL 제약
- 읽기 전용 참고 XLSX의 실제 수식 15종과 독립 `Decimal` 기준식의 합성 등급 500세트 차등 검증
- XLSX `SUMPRODUCT` 학기 평균과 합성 과목·학점 2,500건 차등 검증
- XLSX 참고 Z점수 수식의 `-3.00`~`3.00` 경계 601건과 버전 고정 표 조회 결과 대조
- 참조 범위가 어긋난 수식과 우수학기·고정학기를 혼합한 수식의 자동 규칙화 차단
- 성취도 등급표·분포표의 경계, RATIO/PERCENT 합계, 빈 분포와 `P`의 비수치 보존
- 공식 출결 표의 미인정 결석·지각·조퇴·결과 환산과 누락·미검증값 계산 차단
- 교과점수와 출결점수의 분리 trace 및 면접·실기 미합산
- Hypothesis 100예제씩 결정성·입력 순서 독립성·단조성·점수 범위 속성 검증
- 학년별 우수학기 30/30/40과 별도 출결을 독립 수기식으로 대조하는 합성 골든 테스트

## Phase 9 진행 중 검증 범위

- 상담 결과 비식별 payload의 고정 allowlist와 학생 코드·성적 원문·상담 메모 부재
- Decimal의 문자열 결정성, 누락 `null`과 숫자 0의 구분, canonical JSON digest 재현
- 공급자 중립 합성 어댑터가 비식별 payload만 수신하는지 검증
- 합격 확률·합격 가능·안정/적정/소신/위험 표현이 포함된 초안 거부
- Fernet 암호문의 평문 부재, 변조 탐지, 잘못된 master key 복호화 차단
- 사용자·공급자별 키 저장·교체·마스킹·삭제와 DB ciphertext 확인
- 생성 초안의 소유권, 교사 수정·확정 actor/시각/payload digest 보존
- 관리자 키·초안 route의 인증·CSRF·`no-store`와 평문 키 미반환
- BYOK master key 또는 공급자 키가 없어도 Phase 8 핵심 단위·통합·E2E 회귀 유지

## Phase 13 검증 범위

- `program_ids` getlist 파싱, 첫 선택 순서 보존 중복 제거, 빈 선택·허용되지 않은 ID 거부
- 학과별 모든 전형 확장, 동일 학과 복수 전형 독립 판정, 항목별 준비 중·오류 격리
- 자격 미달 전형의 성적 DB 조회 이전 차단
- 우수학기·전체학기·학년 가중·이수단위 가중·위탁학기 포함/제외 평균등급과 trace
- 공개 평균등급의 전체 업무키·등급 척도·규칙 연도 검증과 다른 척도의 직접 비교 차단
- PostgreSQL `tests/test_phase13_batch_postgres.py`에서 학년도별 학과·전형 조회, 전형 없는 학과 제외, 동일 학과 복수 전형, 자격 우선 조회 차단, 범위별 평균과 입시결과 업무키를 통합 검증
- 학생용·교사용 A4의 전체 행과 교사용 상세 trace, 핵심 영역의 환산점수 부재
- AI schema v2 복수 결과 배열과 학생 식별자·성적 원문·점수 최대값 부재
- `make test-phase13-e2e`로 검색 숨김, 검색 결과·대학 전체 선택, 선택 수, 실제 복수 체크박스 제출, 자격 미달·준비 중 행, 평균등급과 두 인쇄 화면을 검증
