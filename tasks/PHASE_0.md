# Phase 0 작업 카드

## 목표

저장소와 자료 취급 경계를 안전하게 초기화하고 최소 Flask 앱 셸을 검증한다.

## 선행조건과 근거

- 실행 개발 문서 v2의 `Phase 0 저장소·자료 안전화`
- 마스터 프롬프트 v3의 `Phase 0 저장소·자료 안전화`
- 사용자 요청의 프로젝트 초기화 필수 작업

## 허용 수정 경로

초기 설정 파일, `app/`, `tests/`, `scripts/`, `docs/`, `tasks/`, `data/seed/`, `data/sources/` 및 상태 문서.

## 금지 사항

- 기존 기준 문서 수정·이동·삭제
- 실제 전형 규칙, 지원자격 엔진, 점수 계산 구현
- 실제 학생 자료나 원본 모집요강 커밋
- 사람이 검수하지 않은 전형 데이터 공개

## 수용 기준

- Given 빈 초기 저장소, When 앱을 실행하면, Then `/`과 `/health`가 정상 응답한다.
- Given Git 포함 대상, When 민감자료 검사를 실행하면, Then 차단 파일과 API 키가 없어야 한다.
- Given 공개 정제 데이터, When 추후 커밋하면, Then `data/seed/`만 허용된다.

## 먼저 작성할 테스트

- 초기 화면 응답 테스트
- 헬스체크 JSON 응답 테스트
- 저장소 민감자료 검사

## 실행 명령

```bash
uv run pytest
uv run python scripts/check_sensitive_data.py
```

## 독립 검증과 남은 위험

- 독립 검증: Git 포함 목록, ignore 규칙, 테스트 결과, 브라우저 렌더링을 별도로 확인한다.
- 남은 위험: Tailwind CDN은 초기 화면용이며 운영 자산 빌드는 후속 Phase에서 고정해야 한다.
