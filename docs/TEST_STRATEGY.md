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

## Phase 2 진행 중 검증 범위

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
