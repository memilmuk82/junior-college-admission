# 프로젝트 상태

- 기준일: 2026-07-11
- 현재 단계: Phase 2 입력 게이트웨이 진행 중
- 단계 판정: IN_PROGRESS
- 현재 작업: 텍스트 PDF 입력 완료
- 다음 게이트: 이미지·클립보드 입력

## 저장소 인벤토리

| 구분 | 상태 | 비고 |
|---|---|---|
| 실행 개발 문서 v2 | `REFERENCE_ONLY` | 변경 금지 기준 문서 |
| Codex 마스터 프롬프트 v3 | `REFERENCE_ONLY` | 변경 금지 실행 지침 |
| 공식 모집요강·시행계획 원본 | `PENDING_ANALYSIS` | 저장소에 없음 |
| 학생 개인정보·업로드 원본 | `BLOCKED_SOURCE` | 저장소 반입 금지, 현재 미발견 |
| 공개 정제 전형 데이터 | `PENDING_ANALYSIS` | `data/seed/`에 아직 없음 |

## Phase 0 완료 항목

- [x] 기존 Git 상태와 사용자 파일 확인
- [x] 두 기준 문서 원문 확인 및 충돌 검토
- [x] 개인정보·원본·파생 파일 잔존 검사
- [x] Git·Docker 제외 정책 구성
- [x] 공개 정제 데이터 경로 분리
- [x] 최소 Flask 앱 셸과 헬스체크 작성
- [x] 테스트와 민감자료 검사 통과
- [x] Git 변경 검토, 단일 커밋, 원격 push

## Phase 1 완료 항목

- [x] PostgreSQL 전용 SQLAlchemy 2.x 핵심 스키마와 Alembic 최초 migration
- [x] Flask-SQLAlchemy·Flask-Migrate 앱 팩토리 및 `flask db migrate/upgrade` 연동
- [x] 문서 혼합연도 게시 및 근거 없는 규칙 게시의 DB 제약 차단
- [x] 원적교·위탁기관 학생 성적 출처 분리
- [x] 임시 원본·파생물 세션 저장과 삭제 검증 서비스
- [x] PostgreSQL 17 `tmpfs` 통합 테스트 컨테이너
- [x] `make` 자동 실행 하네스와 Ruff·mypy·pytest 구성
- [x] 단위 7건·PostgreSQL 통합 7건·규칙·민감정보 검사 통과
- [x] 실제 학생 자료·원본·DB 파일 Git 포함 0건

## Phase 2 진행 항목

- [x] CSV·표 붙여넣기 표준 필드 정규화와 누락 보존
- [x] XLSX 복수 시트 및 앞부분 설명 행 이후 머리글 탐지
- [x] 동일 원본 SHA-256과 입력 크기·시트·행 제한
- [x] CSV·XLSX 학급표에서 대상 학생 외 행 제거와 과목 통계 추출
- [x] 교사 확인 행만 PostgreSQL 저장하고 원본·파생물 삭제 검증
- [x] 삭제 실패 시 DB transaction rollback과 명시적 오류
- [x] `P`를 0점으로 바꾸지 않는 원문 라벨 저장 제약
- [x] 텍스트 PDF의 페이지 비고정 교과 표 탐색과 페이지 trace
- [x] 세부능력 및 특기사항 원문 입력 제외
- [x] 암호화·무텍스트·과대 PDF 명시적 분기
- [ ] 이미지·클립보드 로컬 OCR 미리보기
