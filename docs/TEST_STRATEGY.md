# 테스트 전략

Phase 0 검증 범위는 다음과 같다.

- Flask 앱 셸과 `/health` 응답
- Git 포함 대상의 원본 문서·스프레드시트·DB·환경 파일·API 키 패턴 검사
- `.gitignore`와 `.dockerignore` 정책의 수동 검토

후속 기능은 기준 문서에 따라 `Red → Green → Refactor → Regression → Independent check → Record` 순서를 적용한다.
