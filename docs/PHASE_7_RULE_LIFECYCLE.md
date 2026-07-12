# Phase 7 규칙 버전·감사 계약

게시 규칙은 직접 수정하지 않는다. 관리자가 변경을 시작하면 기존 `PUBLISHED` 규칙의 payload와 근거 연결을 새 레코드로 복제하고 다음 값은 초기화한다.

- lifecycle: `DRAFT`
- 독립 검증: `FALSE`
- 골든 테스트 참조: 빈 값
- 사람 승인 시각: 빈 값

`rule_version_lineages`는 새 규칙 ID와 이전 규칙 ID, 변경 사유를 보존한다. `rule_audit_events`는 DRAFT 복제, 사람 승인, 게시, 이전 버전 대체를 관리자 식별자·시각·payload SHA-256과 함께 기록한다.

payload 비교는 중첩 경로 단위로 변경 전후 값을 표시한다. 계산 영향도는 `synthetic-` 식별자를 가진 합성 표본만 허용하며 기존·신규 결과와 Decimal 차이를 제공한다.

사람 승인은 다음을 모두 요구한다.

- 현재 상태 `TESTED`
- 공식 근거 연결
- 독립 검증 완료
- 골든 테스트 참조
- timezone이 있는 승인 시각
- 명시적 `HUMAN_APPROVED` 확인값

새 규칙 게시 시 같은 전형의 기존 `PUBLISHED` 규칙을 먼저 `SUPERSEDED`로 바꾸고 새 규칙을 게시한다. PostgreSQL partial unique index는 전형별 활성 게시 규칙 한 건만 허용한다.

이 계약은 AI의 사람 승인 대행이나 자동 게시를 허용하지 않는다. 관리자 SSR의 명시적 POST 동작만 이후 승인 서비스에 연결한다.
