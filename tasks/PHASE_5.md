# Phase 5 작업 카드

## 목표

제공된 2027학년도 공식 자료 범위에서 동양미래대·명지전문대·인하공전·연성대·폴리텍 서울정수 파일럿을 `문서 → 자격 → 성적 범위 → 계산 → 골든 후보 → 사람 승인 대기`로 연결한다.

## 선행조건과 근거

- `PROJECT_STATUS.md`의 Phase 4 `PASS`
- 실행 개발 문서 v2의 `Phase 5 실제 대학 수직 슬라이스`
- 마스터 프롬프트 v3의 `Phase 5 파일럿 수직 슬라이스`
- 제공된 참고자료만 읽기 전용으로 사용하고 다른 PDF를 수집하지 않음

## 허용 수정 경로

- 파일럿 규칙 서비스: `app/services/`
- 검수 완료 공개 seed 계약: `data/seed/`
- 규칙·DB 계약: `app/models.py`, `migrations/`, `scripts/validate_rules.py`
- 합성·공식 예시 기반 검증: `tests/`, `Makefile`
- 기록: `README.md`, `PROJECT_STATUS.md`, `DEVELOPMENT_LOG.md`, `docs/`, `tasks/PHASE_5.md`

`data/seed/`에는 사람 검수와 공개 가능성이 확인된 자료만 둘 수 있다. 현재 단계에서 AI가 추출한 후보나 원본·추출문은 seed로 만들지 않는다.

## 금지 사항

- 두 기준 원본 문서와 Phase 0~4 작업 카드 수정
- 참고 PDF·XLSX·CSV·노트북 또는 추출본의 Git 추가
- 2026학년도 자료를 2027학년도 규칙 근거로 자동 사용
- 대학명 조건 분기, 자유 수식, `eval()`, 누락값 추정
- 자격 미확정 전형의 성적 계산
- AI의 `HUMAN_APPROVED` 설정이나 자동 게시
- 공식 PDF가 없는 규칙을 대학 공식 산식으로 표시

## 파일럿 처리 순서

1. 문서 내부 모집학년도·발행 주체·문서 상태 확인
2. 캠퍼스·모집시기·전형과 지원자격 식별
3. 직업위탁 학생의 지원 가능성과 적용 전형 확인
4. 성적 출처·학년·학기·과목·가중치·반올림·Z점수·출결 추출
5. 현재 제한형 DSL 표현 가능 여부 확인
6. 엑셀 참고식과 공식 문서의 일치·불일치 기록
7. 합성 입력으로 골든 후보 작성
8. 독립 원문 검증과 사람 승인 대기 상태로 종료

## 수용 기준

- 각 파일럿은 `UNIVERSITY_OFFICIAL 후보`, `VERIFIED_REFERENCE 후보`, `MANUAL_REVIEW` 중 하나로 근거가 분류된다.
- 최종 모집요강과 시행계획을 같은 확정도로 취급하지 않는다.
- 자격·성적 범위·계산 규칙의 문서 페이지와 표 위치가 분리 기록된다.
- 공식 문서와 참고 엑셀이 충돌하면 공식 문서 후보를 우선하되 자동 게시하지 않는다.
- 폴리텍처럼 내부 연도가 혼재하면 2027 규칙을 추정하지 않고 `MANUAL_REVIEW`로 둔다.
- 공개 seed가 없더라도 합성 골든 후보와 게시 차단 테스트로 승인 대기 상태를 검증한다.

## 실행 명령

```bash
make test-unit
make test-integration
make lint
make validate-rules
make check-sensitive-data
make check
```

## 게이트

- AI 추출 후보는 최대 `EXTRACTED` 또는 `VERIFIED` 후보이며 `HUMAN_APPROVED`가 아니다.
- 사람 승인 전 실제 대학 규칙은 `PUBLISHED`로 전환하지 않는다.
- 공식 근거를 확정할 수 없는 파일럿이 있으면 해당 항목만 `MANUAL_REVIEW`로 남기고 다른 파일럿의 검증을 막지 않는다.
