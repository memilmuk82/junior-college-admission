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

## Phase 3 진행 중 검증 범위

- 같은 합성 일반고 직업위탁생의 전형별 독립 결과
- 일반고·특성화고 합성 전형의 동시 지원 가능 상태
- 마이스터고·종합고 직업계열·검정고시·학과 예외 사실
- 5개 지원자격 상태와 확정 결과 여부
- `all`·`any`·`not`의 누락값 3값 논리와 반례
- 허용하지 않은 사실·연산자·문자열 수식·추가 사실 이름 거부
- 비게시 또는 근거·검증·골든·사람 승인이 누락된 규칙 실행 거부
- 동일 사실·규칙의 설명 trace 재현과 실제 사실값 미포함
- 지원 불가·검토 필요·정보 부족 상태의 계산 진입 차단
